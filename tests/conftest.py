import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import create_app
from app.models.identity import Membership, Organization, User
from app.security.dependencies import get_db
from app.security.passwords import hash_password
from app.security.rate_limit import check_login_rate

API_ROOT = Path(__file__).resolve().parents[1] / "services/api"
PASSWORD = "test-only-password-42!"
ORIGIN = "http://localhost:3000"


@pytest.fixture(scope="session")
def identity_engine():
    url = make_url(get_settings().database_url.get_secret_value())
    name = "identity_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"CREATE DATABASE {name}"))
    engine = create_engine(url.set(database=name))
    try:
        env = dict(
            os.environ,
            DATABASE_URL=url.set(database=name).render_as_string(hide_password=False),
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=API_ROOT,
            env=env,
            check=True,
            capture_output=True,
        )
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE {name} WITH (FORCE)"))
        admin.dispose()


@pytest.fixture
def identities(identity_engine, monkeypatch):
    from app.core.database import Base

    with Session(identity_engine) as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(delete(table))
        encoded = hash_password(PASSWORD)
        users = [
            User(
                email=f"user{i}@example.com",
                full_name=f"User {i}",
                password_hash=encoded,
            )
            for i in range(5)
        ]
        orgs = [
            Organization(name="Organization A"),
            Organization(name="Organization B"),
        ]
        db.add_all(users + orgs)
        db.flush()
        for i, role in [(0, "owner"), (1, "member"), (2, "viewer"), (4, "admin")]:
            db.add(Membership(organization_id=orgs[0].id, user_id=users[i].id, role=role))
        db.add(Membership(organization_id=orgs[1].id, user_id=users[3].id, role="owner"))
        db.add(Membership(organization_id=orgs[1].id, user_id=users[1].id, role="member"))
        db.commit()
        ids = {"users": [u.id for u in users], "orgs": [o.id for o in orgs]}
    app = create_app()

    def test_db(request: Request):
        with Session(identity_engine, expire_on_commit=False) as db:
            db.info["request_id"] = request.state.request_id
            yield db

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[check_login_rate] = lambda: None
    monkeypatch.setattr("app.security.tasks.get_engine", lambda: identity_engine)
    clients = []

    def login(index=0):
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": f"user{index}@example.com", "password": PASSWORD},
        )
        assert response.status_code == 200, response.text
        client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]})
        clients.append(client)
        return client

    yield {**ids, "app": app, "login": login, "engine": identity_engine}
    for client in clients:
        client.close()


@pytest.fixture
def catalog(identities):
    with Session(identities["engine"]) as db:
        db.get(User, identities["users"][0]).is_data_curator = True
        db.commit()
    client = identities["login"]()
    response = client.post(
        "/api/v1/catalog/sources",
        json={
            "source_name": "Synthetic test source",
            "source_type": "manual",
            "license_type": "synthetic_demo",
            "permitted_use": "Synthetic data for automated tests only",
            "public_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    source_id = response.json()["id"]

    def create(name="示例先进封装企业", **overrides):
        response = client.post(
            "/api/v1/companies",
            json={
                "canonical_name": name,
                "source_id": source_id,
                "reason": "自动化测试资料录入",
                **overrides,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    return {**identities, "client": client, "source_id": source_id, "create": create}


@pytest.fixture
def knowledge(identities):
    import base64

    from app.services.dependencies import storage_client

    owner = identities["login"]()
    org = identities["orgs"][0]
    project = owner.post(
        f"/api/v1/organizations/{org}/projects", json={"name": "Private test project"}
    ).json()["id"]
    base = f"/api/v1/organizations/{org}/projects/{project}/documents"
    for number, role in [(1, "editor"), (2, "viewer")]:
        assert (
            owner.put(
                f"/api/v1/organizations/{org}/projects/{project}/members",
                json={"user_id": str(identities["users"][number]), "role": role},
            ).status_code
            == 200
        )

    def upload(
        text="企业盈利能力与半导体设备客户验证需要核实。",
        filename="研究资料.md",
        client=None,
        **extra,
    ):
        raw = text if isinstance(text, bytes) else text.encode()
        payload = {
            "filename": filename,
            "title": "私有研究资料",
            "content_base64": base64.b64encode(raw).decode(),
            "idempotency_key": str(uuid4()),
            **extra,
        }
        result = (client or owner).post(base, json=payload)
        assert result.status_code == 202, result.text
        return result.json(), payload

    yield {
        **identities,
        "owner": owner,
        "org": org,
        "project": project,
        "base": base,
        "upload": upload,
    }
    storage = storage_client()
    for org_id in identities["orgs"]:
        token = None
        while True:
            args = {"Bucket": get_settings().s3_bucket, "Prefix": f"private/{org_id}/"}
            if token:
                args["ContinuationToken"] = token
            page = storage.list_objects_v2(**args)
            if page.get("Contents"):
                storage.delete_objects(
                    Bucket=get_settings().s3_bucket,
                    Delete={"Objects": [{"Key": o["Key"]} for o in page["Contents"]]},
                )
            token = page.get("NextContinuationToken")
            if not token:
                break
