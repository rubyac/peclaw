import base64
import io
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.imports import execute_import
from app.models.catalog import CatalogImport, Company
from app.models.identity import User, now

pytestmark = pytest.mark.integration


def test_source_permission_and_unknown_fields(catalog):
    client = catalog["client"]
    company = catalog["create"](aliases=["示例旧名"])
    assert (
        company["listing_status"]
        == company["company_stage"]
        == company["financing_stage"]
        == "unknown"
    )
    assert company["sources"][0]["license_type"] == "synthetic_demo"
    assert company["source_status"] == "unverified"
    assert "organization_id" not in company
    assert catalog["login"](3).get(f"/api/v1/companies/{company['id']}").status_code == 200
    assert client.get("/api/v1/companies", params={"q": "示例旧名"}).json()["total"] == 1
    assert (
        client.get("/api/v1/companies", params={"listing_status": "unlisted"}).json()["total"] == 0
    )
    assert (
        client.post(
            "/api/v1/catalog/sources",
            json={
                "source_name": "Unlicensed",
                "source_type": "official",
                "source_url": "https://example.com",
                "license_type": "authorized",
                "permitted_use": "private only",
                "public_confirmed": False,
            },
        ).status_code
        == 422
    )


def test_update_version_history_and_archive(catalog):
    client = catalog["client"]
    initial = catalog["create"](province="江苏", aliases=["曾用名"])
    body = {
        "canonical_name": "示例新名称",
        "aliases": ["新别名"],
        "source_id": catalog["source_id"],
        "reason": "人工核验后修正企业名称",
        "expected_version": 1,
    }
    updated = client.patch(f"/api/v1/companies/{initial['id']}", json=body)
    assert updated.status_code == 200 and updated.json()["version"] == 2
    assert updated.json()["province"] == "江苏"  # Omitted fields must not silently disappear.
    assert client.patch(f"/api/v1/companies/{initial['id']}", json=body).status_code == 409
    history = client.get(f"/api/v1/companies/{initial['id']}/history").json()
    assert history[0]["before"]["canonical_name"] == initial["canonical_name"]
    assert history[0]["after"]["canonical_name"] == "示例新名称"
    response = client.post(
        f"/api/v1/companies/{initial['id']}/archive",
        json={
            "source_id": catalog["source_id"],
            "reason": "过期档案归档处理",
            "expected_version": 2,
        },
    )
    assert response.status_code == 200 and response.json()["is_archived"]
    assert client.get("/api/v1/companies").json()["total"] == 0
    assert client.get("/api/v1/companies", params={"include_archived": True}).json()["total"] == 1


def evidence(client, record, source_id, **extra):
    response = client.post(
        f"/api/v1/companies/{record['id']}/evidence",
        json={
            "source_id": source_id,
            "claim_text": "仅用于测试的来源主张",
            "excerpt": "这是合成资料中的引用原文，不代表真实企业情况。",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_taxonomy_products_evidence_conflicts_and_natural_search(catalog):
    client, source_id = catalog["client"], catalog["source_id"]
    node = client.post("/api/v1/catalog/taxonomy/industries", json={"name": "先进封装"}).json()
    tech = client.post(
        "/api/v1/catalog/taxonomy/technologies",
        json={"name": "混合键合", "aliases": ["Hybrid Bonding"]},
    ).json()
    record = catalog["create"](
        province="江苏",
        listing_status="unlisted",
        company_stage="pilot",
        industry_ids=[node["id"]],
    )
    ev = evidence(
        client,
        record,
        source_id,
        field_name="listing_status",
        field_value="unlisted",
        verification_status="verified",
        classification="fact",
        page_number=3,
    )
    evidence(client, record, source_id, field_name="listing_status", field_value="unknown")
    assert (
        client.post(
            f"/api/v1/companies/{record['id']}/technologies",
            json={
                "technology_id": tech["id"],
                "evidence_id": ev,
                "relation_type": "announced",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v1/companies/{record['id']}/products",
            json={
                "name": "演示设备",
                "product_category": "键合设备",
                "source_id": source_id,
                "evidence_id": ev,
            },
        ).status_code
        == 201
    )
    result = client.post(
        "/api/v1/companies/search",
        json={"query": "寻找江苏先进封装混合键合未上市中试企业"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 1 and len(result.json()["matched_intent"]) >= 4
    result = client.get(f"/api/v1/companies/{record['id']}").json()
    assert result["conflicts"][0]["field_name"] == "listing_status"
    assert result["evidence"][1]["reviewer_id"] == str(catalog["users"][0])
    assert result["products"][0]["commercialization_stage"] == "unknown"
    assert result["technologies"][0]["evidence_id"] == ev


def test_evidence_cannot_be_borrowed_from_unrelated_company(catalog):
    client = catalog["client"]
    first, second = catalog["create"]("甲示例企业"), catalog["create"]("乙示例企业")
    ev = evidence(client, first, catalog["source_id"])
    assert (
        client.post(
            f"/api/v1/companies/{second['id']}/products",
            json={
                "name": "错误引用设备",
                "product_category": "测试",
                "source_id": catalog["source_id"],
                "evidence_id": ev,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/companies/{first['id']}/evidence",
            json={
                "source_id": catalog["source_id"],
                "claim_text": "测试推断",
                "excerpt": "仅是推断，不应作为已核验事实。",
                "classification": "inference",
                "verification_status": "verified",
            },
        ).status_code
        == 422
    )


def test_manual_merge_and_undo_preserve_originals(catalog):
    client = catalog["client"]
    target = catalog["create"]("示例企业甲", website="https://www.example.com/one")
    duplicate = catalog["create"](
        "示例企业甲旧名", aliases=["合并前别名"], website="https://example.com/two"
    )
    ev = evidence(client, duplicate, catalog["source_id"])
    candidates = client.get(f"/api/v1/companies/{target['id']}/duplicates").json()
    assert candidates["items"][0]["id"] == duplicate["id"] and not candidates["automatic_merge"]
    result = client.post(
        f"/api/v1/companies/{target['id']}/merge",
        json={
            "duplicate_id": duplicate["id"],
            "source_id": catalog["source_id"],
            "reason": "人工确认同一企业的历史名称",
            "expected_target_version": 1,
            "expected_duplicate_version": 1,
            "confirm": True,
        },
    )
    assert result.status_code == 200, result.text
    merged = result.json()
    assert client.get("/api/v1/companies").json()["total"] == 1
    assert merged["company"]["evidence"][0]["id"] == ev
    assert "合并前别名" in merged["company"]["aliases"]
    assert (
        client.get("/api/v1/companies", params={"q": "合并前别名"}).json()["items"][0]["id"]
        == target["id"]
    )
    child = client.get(f"/api/v1/companies/{duplicate['id']}").json()
    assert (
        child["canonical_name"] == duplicate["canonical_name"]
        and child["merged_into_id"] == target["id"]
    )
    result = client.post(
        f"/api/v1/catalog/merges/{merged['merge_id']}/undo",
        json={
            "source_id": catalog["source_id"],
            "reason": "人工复核后撤销测试合并",
            "expected_target_version": 2,
            "expected_duplicate_version": 2,
        },
    )
    assert result.status_code == 200, result.text
    assert client.get("/api/v1/companies").json()["total"] == 2
    assert client.get(f"/api/v1/companies/{duplicate['id']}").json()["evidence"][0]["id"] == ev


def queue(catalog, content: bytes, format="csv", key=None):
    payload = {
        "source_id": catalog["source_id"],
        "reason": "批量导入合成测试档案",
        "format": format,
        "content_base64": base64.b64encode(content).decode(),
        "idempotency_key": str(key or uuid4()),
        "public_confirmed": True,
    }
    result = catalog["client"].post("/api/v1/catalog/imports", json=payload)
    assert result.status_code == 202, result.text
    return result.json(), payload


def test_csv_worker_idempotency_and_row_validation(catalog):
    content = (
        "canonical_name,aliases,listing_status,industries,technologies,technology_excerpt\n"
        "导入示例企业,旧名|别名,unknown,先进封装,混合键合,合成文档标注混合键合研究方向。\n"
        "错误行,,definitely_not_a_status,,,\n"
    ).encode()
    job, payload = queue(catalog, content)
    assert catalog["client"].post("/api/v1/catalog/imports", json=payload).json()["id"] == job["id"]
    changed = {**payload, "reason": "改变同一个幂等键内容"}
    assert catalog["client"].post("/api/v1/catalog/imports", json=changed).status_code == 409
    assert execute_import(catalog["engine"])
    result = catalog["client"].get(f"/api/v1/catalog/imports/{job['id']}").json()
    assert result["state"] == "completed" and result["result"]["counts"] == {
        "created": 1,
        "skipped": 0,
        "review_required": 0,
        "error": 1,
    }
    second, _ = queue(catalog, content)
    execute_import(catalog["engine"])
    assert (
        catalog["client"]
        .get(f"/api/v1/catalog/imports/{second['id']}")
        .json()["result"]["counts"]["skipped"]
        == 1
    )
    with Session(catalog["engine"]) as db:
        assert len(db.scalars(select(Company)).all()) == 1


def test_xlsx_import_and_no_automatic_merge(catalog):
    catalog["create"]("重复示例企业")
    book = Workbook()
    book.active.append(["canonical_name", "listing_status"])
    book.active.append(["重复示例企业", "unknown"])
    book.active.append(["XLSX示例企业", "unknown"])
    data = io.BytesIO()
    book.save(data)
    job, _ = queue(catalog, data.getvalue(), "xlsx")
    execute_import(catalog["engine"])
    result = catalog["client"].get(f"/api/v1/catalog/imports/{job['id']}").json()
    assert (
        result["result"]["counts"]["created"] == 1
        and result["result"]["counts"]["review_required"] == 1
    )


def test_invalid_file_retries_and_revoked_curator(catalog):
    job, _ = queue(catalog, b"unsupported_column\nvalue\n")
    for attempt in range(1, 4):
        execute_import(catalog["engine"])
        result = catalog["client"].get(f"/api/v1/catalog/imports/{job['id']}").json()
        assert result["state"] == "failed" and result["attempts"] == attempt
        if attempt < 3:
            assert (
                catalog["client"].post(f"/api/v1/catalog/imports/{job['id']}/retry").status_code
                == 200
            )
    assert catalog["client"].post(f"/api/v1/catalog/imports/{job['id']}/retry").status_code == 409
    other, _ = queue(catalog, b"canonical_name\nNot allowed\n")
    with Session(catalog["engine"]) as db:
        db.get(User, catalog["users"][0]).is_data_curator = False
        db.commit()
    execute_import(catalog["engine"])
    with Session(catalog["engine"]) as db:
        result = db.get(CatalogImport, UUID(other["id"]))
        assert result.state == "failed" and result.error_code == "CURATOR_ACCESS_REVOKED"
        assert db.scalar(select(Company)) is None


def test_stale_running_import_is_recovered(catalog):
    job, _ = queue(catalog, b"canonical_name\nRecovered example\n")
    with Session(catalog["engine"]) as db:
        stored = db.get(CatalogImport, UUID(job["id"]))
        stored.state = "running"
        stored.attempts = 1
        stored.started_at = now() - timedelta(minutes=5)
        db.commit()
    assert execute_import(catalog["engine"])
    result = catalog["client"].get(f"/api/v1/catalog/imports/{job['id']}").json()
    assert result["state"] == "completed" and result["attempts"] == 2


def test_last_crashed_attempt_becomes_failed(catalog):
    job, _ = queue(catalog, b"canonical_name\nNever execute\n")
    with Session(catalog["engine"]) as db:
        stored = db.get(CatalogImport, UUID(job["id"]))
        stored.state = "running"
        stored.attempts = 3
        stored.started_at = now() - timedelta(minutes=5)
        db.commit()
    execute_import(catalog["engine"])
    result = catalog["client"].get(f"/api/v1/catalog/imports/{job['id']}").json()
    assert result["state"] == "failed" and result["error_code"] == "MAX_ATTEMPTS_EXHAUSTED"


def test_china_search_does_not_treat_unknown_country_as_china(catalog):
    catalog["create"]("中国示例企业", country="中国")
    catalog["create"]("未知国家示例企业")
    result = catalog["client"].post("/api/v1/companies/search", json={"query": "寻找中国境内企业"})
    assert result.status_code == 200 and result.json()["total"] == 1
    assert result.json()["applied_filters"]["country"] == "中国"


def test_parent_industry_includes_children(catalog):
    client = catalog["client"]
    parent = client.post("/api/v1/catalog/taxonomy/industries", json={"name": "设备产业"}).json()
    child = client.post(
        "/api/v1/catalog/taxonomy/industries",
        json={"name": "封装设备", "parent_id": parent["id"]},
    ).json()
    catalog["create"](industry_ids=[child["id"]])
    result = client.get("/api/v1/companies", params={"industry_id": parent["id"]})
    assert result.status_code == 200 and result.json()["total"] == 1


def test_natural_search_discloses_unsupported_conditions(catalog):
    catalog["create"](country="中国")
    result = catalog["client"].post(
        "/api/v1/companies/search", json={"query": "中国营收超过一亿元的企业"}
    )
    assert result.status_code == 200
    assert "营收" in result.json()["unparsed_criteria"]
    result = catalog["client"].post(
        "/api/v1/companies/search", json={"query": "中国企业但排除江苏"}
    )
    assert result.status_code == 422


def test_merge_discloses_conflicting_original_statuses(catalog):
    first = catalog["create"]("同名示例", listing_status="listed")
    second = catalog["create"]("同名示例旧名", listing_status="unlisted")
    response = catalog["client"].post(
        f"/api/v1/companies/{first['id']}/merge",
        json={
            "duplicate_id": second["id"],
            "source_id": catalog["source_id"],
            "reason": "人工确认测试历史档案归属",
            "expected_target_version": 1,
            "expected_duplicate_version": 1,
            "confirm": True,
        },
    )
    assert response.status_code == 200
    conflict = response.json()["company"]["conflicts"][0]
    assert conflict["field_name"] == "listing_status" and set(conflict["values"]) == {
        "listed",
        "unlisted",
    }
    assert set(conflict["record_ids"]) == {first["id"], second["id"]}


def test_historical_alias_is_a_review_candidate_not_a_new_automatic_identity(catalog):
    original = catalog["create"]("设备企业正式现用名", aliases=["更名前的旧名称"])
    job, _ = queue(catalog, "canonical_name\n更名前的旧名称\n".encode())
    execute_import(catalog["engine"])
    result = catalog["client"].get(f"/api/v1/catalog/imports/{job['id']}").json()
    assert result["result"]["counts"]["review_required"] == 1
    assert original["id"] in result["result"]["rows"][0]["candidate_ids"]
    manual = catalog["create"]("更名前的旧名称")
    candidates = catalog["client"].get(f"/api/v1/companies/{original['id']}/duplicates").json()
    match = next(row for row in candidates["items"] if row["id"] == manual["id"])
    assert any("别名" in reason for reason in match["reasons"])
    assert catalog["client"].get("/api/v1/companies").json()["total"] == 2


def test_archived_identity_is_not_silently_recreated_on_import(catalog):
    record = catalog["create"]("归档企业的已知身份")
    catalog["client"].post(
        f"/api/v1/companies/{record['id']}/archive",
        json={
            "source_id": catalog["source_id"],
            "reason": "人工归档后保留历史身份",
            "expected_version": 1,
        },
    )
    job, _ = queue(catalog, "canonical_name\n归档企业的已知身份\n".encode())
    execute_import(catalog["engine"])
    result = catalog["client"].get(f"/api/v1/catalog/imports/{job['id']}").json()
    assert result["result"]["counts"]["review_required"] == 1
    assert catalog["client"].get("/api/v1/companies").json()["total"] == 0
