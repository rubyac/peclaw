import base64
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError
from fixtures.private_documents import office_bytes
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.knowledge.workflow import execute_ingestion
from app.models.identity import AuditLog, User, now
from app.models.knowledge import DocumentChunk, DocumentVersion
from app.services.dependencies import storage_client

pytestmark = pytest.mark.integration


def run_all(k):
    for _ in range(20):
        if not execute_ingestion(k["engine"]):
            return
    raise AssertionError("Worker did not drain finite test jobs")


def search(k, query, client=None, mode="hybrid", org=None, project=True):
    return (client or k["owner"]).post(
        f"/api/v1/organizations/{org or k['org']}/knowledge/search",
        json={
            "query": query,
            "mode": mode,
            "project_id": k["project"] if project else None,
        },
    )


def test_upload_real_index_download_citation_and_idempotency(knowledge):
    k = knowledge
    doc, payload = k["upload"]()
    owner = k["owner"]
    path = f"{k['base']}/{doc['id']}"
    assert owner.post(k["base"], json=payload).json()["id"] == doc["id"]
    assert owner.post(k["base"], json={**payload, "title": "different"}).status_code == 409
    run_all(k)
    current = owner.get(path).json()
    assert current["current"]["status"] == "indexed"
    assert current["current"]["chunk_count"] > 0
    chunks = owner.get(path + "/chunks").json()
    assert chunks[0]["locator"]["type"] == "md"
    assert chunks[0]["excerpt"] == "企业盈利能力与半导体设备客户验证需要核实。"
    assert "embedding" not in chunks[0] and "object_key" not in str(current)
    result = search(k, "企业盈利能力").json()
    assert result["items"] and result["semantic_available"]
    assert "semantic" in result["items"][0]["matched_by"]
    download = owner.get(path + "/download")
    assert download.status_code == 200
    assert download.content == base64.b64decode(payload["content_base64"])
    assert (
        "attachment" in download.headers["content-disposition"]
        and download.headers["cache-control"] == "no-store"
    )


@pytest.mark.parametrize("kind", ["pdf", "docx", "xlsx", "pptx", "txt"])
def test_full_pipeline_all_supported_formats(knowledge, kind):
    raw = office_bytes(kind) if kind != "txt" else "机构财务分析仍需验证数据来源。".encode()
    doc, _ = knowledge["upload"](raw, filename=f"测试文件.{kind}")
    run_all(knowledge)
    current = knowledge["owner"].get(f"{knowledge['base']}/{doc['id']}").json()
    assert current["current"]["status"] == "indexed", current
    assert current["current"]["chunk_count"] > 0


def test_new_version_excludes_old_index_until_ready(knowledge):
    k = knowledge
    owner = k["owner"]
    doc, _ = k["upload"]("旧版机密代号绿竹，仅供历史研究。")
    run_all(k)
    path = f"{k['base']}/{doc['id']}"
    response = owner.post(
        path + "/versions",
        json={
            "filename": "新版本.txt",
            "content_base64": base64.b64encode(
                "新版机密代号红杉，取代以前资料。".encode()
            ).decode(),
            "idempotency_key": str(uuid4()),
            "expected_revision": doc["revision"],
        },
    )
    assert response.status_code == 202 and response.json()["current_version"] == 2
    assert search(k, "旧版机密代号绿竹", mode="keyword").json()["items"] == []
    run_all(k)
    assert search(k, "旧版机密代号绿竹", mode="keyword").json()["items"] == []
    results = search(k, "新版机密代号红杉", mode="keyword").json()["items"]
    assert results and results[0]["version_number"] == 2
    assert "绿竹" in owner.get(path + "/chunks", params={"version": 1}).json()[0]["excerpt"]


def test_delete_revokes_content_immediately_and_purges_raw_objects(knowledge):
    k = knowledge
    doc, _ = k["upload"]("删除验证原文独有词句。")
    run_all(k)
    path = f"{k['base']}/{doc['id']}"
    with Session(k["engine"]) as db:
        key = db.get(DocumentVersion, UUID(doc["current"]["id"])).object_key
    assert storage_client().head_object(Bucket=get_settings().s3_bucket, Key=key)
    assert (
        k["owner"].request("DELETE", path, json={"expected_revision": doc["revision"]}).status_code
        == 202
    )
    assert k["owner"].get(path + "/download").status_code == 404
    assert k["owner"].get(path + "/chunks").status_code == 404
    assert search(k, "删除验证原文独有词句", mode="keyword").json()["items"] == []
    run_all(k)
    with Session(k["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 0
        version = db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == UUID(doc["id"]))
        )
        assert version.status == "deleted" and version.object_key is None
    with pytest.raises(ClientError) as missing:
        storage_client().head_object(Bucket=get_settings().s3_bucket, Key=key)
    assert missing.value.response["Error"]["Code"] in {"404", "NoSuchKey"}
    listing = k["owner"].get(k["base"], params={"include_deleted": True}).json()
    assert listing[0]["is_deleted"] and not listing[0]["can_read"]


def test_queued_job_revalidates_actor_and_retry_can_use_new_editor(knowledge):
    k = knowledge
    doc, _ = k["upload"]()
    with Session(k["engine"]) as db:
        db.get(User, k["users"][0]).is_active = False
        db.commit()
    run_all(k)
    editor = k["login"](1)
    path = f"{k['base']}/{doc['id']}"
    failed = editor.get(path).json()
    assert failed["current"]["error_code"] == "ACCESS_REVOKED"
    assert (
        editor.post(path + "/retry", json={"expected_revision": doc["revision"]}).status_code == 202
    )
    run_all(k)
    assert editor.get(path).json()["current"]["status"] == "indexed"


def test_parser_failure_retry_limit_and_recovery(knowledge):
    k = knowledge
    doc, _ = k["upload"](b"%PDF-1.7\nnot a real pdf", filename="损坏.pdf")
    path = f"{k['base']}/{doc['id']}"
    for attempt in range(1, 4):
        run_all(k)
        current = k["owner"].get(path).json()["current"]
        assert current["status"] == "failed" and current["attempts"] == attempt
        if attempt < 3:
            assert (
                k["owner"].post(path + "/retry", json={"expected_revision": 1}).status_code == 202
            )
    assert k["owner"].post(path + "/retry", json={"expected_revision": 1}).status_code == 409
    fresh, _ = k["upload"]()
    with Session(k["engine"]) as db:
        version = db.get(DocumentVersion, UUID(fresh["current"]["id"]))
        version.status = "parsing"
        version.attempts = 1
        version.lease_until = now() - timedelta(minutes=5)
        db.commit()
    run_all(k)
    assert k["owner"].get(f"{k['base']}/{fresh['id']}").json()["current"]["status"] == "indexed"


def test_delete_during_parse_does_not_resurrect_chunks(knowledge, monkeypatch):
    from app.knowledge import workflow

    k = knowledge
    doc, _ = k["upload"]()
    path = f"{k['base']}/{doc['id']}"
    original = workflow.parse_local

    def delete_while_parsing(raw, kind):
        assert k["owner"].request("DELETE", path, json={"expected_revision": 1}).status_code == 202
        return original(raw, kind)

    monkeypatch.setattr(workflow, "parse_local", delete_while_parsing)
    run_all(k)
    with Session(k["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 0
    assert k["owner"].get(path).status_code == 404


def test_search_audit_never_contains_private_text(knowledge):
    k = knowledge
    secret = "私有研究绝密测试数据不得写日志"
    k["upload"](secret)
    run_all(k)
    search(k, secret)
    with Session(k["engine"]) as db:
        rows = db.scalars(select(AuditLog)).all()
        assert any(r.action == "knowledge.search" for r in rows)
        assert secret not in str([r.details for r in rows])


def test_corrupted_original_is_never_indexed_or_downloaded(knowledge):
    k = knowledge
    doc, _ = k["upload"]()
    with Session(k["engine"]) as db:
        key = db.get(DocumentVersion, UUID(doc["current"]["id"])).object_key
    storage_client().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=b"corrupted")
    run_all(k)
    path = f"{k['base']}/{doc['id']}"
    current = k["owner"].get(path).json()["current"]
    assert current["status"] == "failed" and current["error_code"] == "RAW_FILE_HASH_MISMATCH"
    assert k["owner"].get(path + "/download").status_code == 503
    assert search(k, "企业盈利").json()["items"] == []
