"""Operator-side browser fixtures. Never reachable through HTTP; no fixed passwords."""

import json
import secrets
import sys
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_engine
from app.models.catalog import (
    CatalogImport,
    Company,
    DataSource,
    IndustryNode,
    Technology,
)
from app.models.identity import AuditLog, Membership, Organization, User
from app.models.knowledge import PrivateDocument
from app.security.passwords import hash_password
from app.services.dependencies import storage_client

mode = sys.argv[1]
key = str(UUID(sys.argv[2])) if mode == "cleanup" else str(uuid4())
emails = [f"browser-{key}-{role}@example.com" for role in ("owner", "viewer")]
with Session(get_engine()) as db:
    if mode in {"create", "create-catalog", "create-reports"}:
        password = secrets.token_urlsafe(24)
        encoded = hash_password(password)
        users = [
            User(
                email=email,
                full_name=f"Browser {role}",
                password_hash=encoded,
                is_data_curator=mode == "create-catalog" and role == "owner",
            )
            for email, role in zip(emails, ("owner", "viewer"))
        ]
        orgs = [Organization(name=f"BrowserTest {key} {suffix}") for suffix in ("A", "B")]
        db.add_all(users + orgs)
        db.flush()
        for org in orgs:
            db.add(Membership(organization_id=org.id, user_id=users[0].id, role="owner"))
        db.add(
            Membership(
                organization_id=orgs[0].id,
                user_id=users[1].id,
                role="member" if mode == "create-reports" else "viewer",
            )
        )
        db.commit()
        print(
            json.dumps(
                {
                    "key": key,
                    "email": emails[0],
                    "viewer_email": emails[1],
                    "viewer_id": str(users[1].id),
                    "password": password,
                    "org_name": orgs[0].name,
                    "org_id": str(orgs[0].id),
                    "other_org_name": orgs[1].name,
                    "other_org_id": str(orgs[1].id),
                }
            )
        )
    elif mode == "cleanup":
        user_ids = db.scalars(select(User.id).where(User.email.in_(emails))).all()
        source_ids = db.scalars(
            select(DataSource.id).where(DataSource.created_by.in_(user_ids))
        ).all()
        db.execute(delete(CatalogImport).where(CatalogImport.requested_by.in_(user_ids)))
        db.execute(delete(Company).where(Company.source_id.in_(source_ids)))
        db.execute(delete(DataSource).where(DataSource.id.in_(source_ids)))
        db.execute(delete(Technology).where(Technology.name.like(f"Browser%{key}%")))
        db.execute(delete(IndustryNode).where(IndustryNode.name.like(f"Browser%{key}%")))
        org_ids = db.scalars(
            select(Organization.id).where(Organization.name.like(f"BrowserTest {key} %"))
        ).all()
        client = storage_client()
        bucket = get_settings().s3_bucket
        for org_id in org_ids:
            for page in client.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=f"private/{org_id}/"
            ):
                for item in page.get("Contents", []):
                    client.delete_object(Bucket=bucket, Key=item["Key"])
        db.execute(delete(PrivateDocument).where(PrivateDocument.organization_id.in_(org_ids)))
        db.execute(delete(AuditLog).where(AuditLog.actor_id.in_(user_ids)))
        db.execute(delete(Organization).where(Organization.name.like(f"BrowserTest {key} %")))
        db.execute(delete(User).where(User.id.in_(user_ids)))
        db.commit()
    else:
        raise SystemExit("Unknown fixture mode")
