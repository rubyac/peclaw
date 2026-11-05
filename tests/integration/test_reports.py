import hashlib
import io
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from docx import Document
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge.workflow import execute_ingestion
from app.models.identity import Membership, User
from app.models.reports import ReportExport

pytestmark = pytest.mark.integration
QUOTE = "2025年营业收入为1.2亿元人民币。以上为合成材料，不代表真实企业。"
CONFIRM = {
    "citations_checked": True,
    "facts_checked": True,
    "numeric_registry_complete": True,
    "conflicts_checked": True,
    "no_invented_data": True,
}


@pytest.fixture
def reports(knowledge):
    k = knowledge
    doc, _ = k["upload"](QUOTE)
    while execute_ingestion(k["engine"]):
        pass
    base = f"/api/v1/organizations/{k['org']}/projects/{k['project']}/reports"
    payload = {
        "title": "合成研究报告",
        "template": "company_profile",
        "document_ids": [doc["id"]],
        "idempotency_key": str(uuid4()),
    }
    response = k["owner"].post(base, json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    path = base + "/" + data["id"]
    reviewer = k["login"](1)

    def current(client=None):
        r = (client or k["owner"]).get(path)
        assert r.status_code == 200, r.text
        return r.json()

    def mutate(suffix, values, client=None, method="POST", expected=200):
        actor = client or k["owner"]
        r = actor.request(
            method, path + suffix, json={"expected_revision": current(actor)["revision"], **values}
        )
        assert r.status_code == expected, r.text
        return r

    def assign():
        return mutate("/reviewer", {"reviewer_id": str(k["users"][1])}, method="PUT").json()

    def save_number():
        data = current()
        content = deepcopy(data["content"])
        content["summary"] = {
            "text": "营业收入为1.2亿元。",
            "classification": "unverified",
            "evidence_ids": [data["quality"]["evidence"][0]["id"]],
        }
        return mutate("", {"title": data["title"], "content": content}, method="PUT").json()

    def add_number(value="1.2", quote=QUOTE):
        evidence = current()["quality"]["evidence"][0]["id"]
        return mutate(
            "/metrics",
            {
                "metric_name": "营业收入",
                "metric_type": "revenue",
                "metric_value": value,
                "unit": "亿元",
                "currency": "CNY",
                "period": "2025年",
                "evidence_id": evidence,
                "source_quote": quote,
                "notes": "合成测试数字，仅验证登记与核验流程",
            },
            expected=201,
        ).json()

    def approve():
        return mutate(
            "/review",
            {
                "decision": "approve",
                "notes": "已逐项人工核对来源、数字与数据缺口，仅为合成流程验证。",
                **CONFIRM,
            },
            client=reviewer,
        )

    def export(mode="draft", format="md", key=None, client=None, expected=200):
        return mutate(
            "/export",
            {"mode": mode, "format": format, "idempotency_key": key or str(uuid4())},
            client=client,
            expected=expected,
        )

    return {
        **k,
        "report": data,
        "path": path,
        "reports_base": base,
        "report_payload": payload,
        "doc": doc,
        "reviewer": reviewer,
        "current": current,
        "mutate": mutate,
        "assign": assign,
        "save_number": save_number,
        "add_number": add_number,
        "approve": approve,
        "export": export,
    }


def test_template_and_draft_exports_are_real_and_idempotent(reports):
    r = reports
    assert (
        r["owner"].post(r["reports_base"], json=r["report_payload"]).json()["id"]
        == r["report"]["id"]
    )
    assert (
        r["owner"]
        .post(r["reports_base"], json={**r["report_payload"], "title": "不同标题"})
        .status_code
        == 409
    )
    for format in ["md", "docx"]:
        key = str(uuid4())
        first = r["export"](format=format, key=key)
        second = r["export"](format=format, key=key)
        assert (
            first.content == second.content and "attachment" in first.headers["content-disposition"]
        )
        assert first.headers["cache-control"] == "no-store"
        assert first.headers["x-content-sha256"] == hashlib.sha256(first.content).hexdigest()
        if format == "md":
            assert "未审核" in first.text and QUOTE.replace(".", "\\.") in first.text
        else:
            assert (
                "未审核"
                in Document(io.BytesIO(first.content)).sections[0].header.paragraphs[0].text
            )
    assert len(r["current"]()["exports"]) == 2


def test_unregistered_number_blocks_formal_even_without_metric_rows(reports):
    r = reports
    r["assign"]()
    r["save_number"]()
    r["mutate"]("/submit", {})
    data = r["current"]()
    assert "UNREGISTERED_NUMBER" in {i["code"] for i in data["quality"]["issues"]}
    r["mutate"](
        "/review",
        {"decision": "approve", "notes": "尝试批准缺少登记的数字。", **CONFIRM},
        client=r["reviewer"],
        expected=409,
    )
    r["export"]("formal", expected=409)
    assert "未审核" in r["export"]().text


def test_metric_review_approval_export_and_edit_invalidates_approval(reports):
    r = reports
    r["assign"]()
    r["save_number"]()
    r["add_number"]()
    r["mutate"]("/submit", {})
    r["export"]("formal", expected=409)
    metric = r["current"]()["metrics"][0]
    r["mutate"](
        f"/metrics/{metric['id']}/review",
        {"status": "verified", "notes": "已对照原文核实数值单位币种与期间。"},
        client=r["reviewer"],
    )
    assert r["current"]()["quality"]["passed"]
    assert r["approve"]().json()["status"] == "approved_for_export"
    for format in ["md", "docx"]:
        data = r["export"]("formal", format)
        assert data.status_code == 200
        if format == "md":
            assert "正式导出" in data.text
    state = r["current"]()
    assert state["status"] == "exported"
    assert any(review["decision"] == "approve" for review in state["reviews"])
    r["mutate"]("", {"title": "重新修改的报告", "content": state["content"]}, method="PUT")
    assert r["current"]()["status"] == "draft"
    approval = next(
        review for review in r["current"]()["reviews"] if review["decision"] == "approve"
    )
    snapshot = r["owner"].get(r["path"] + "/reviews/" + approval["id"])
    assert snapshot.status_code == 200
    assert snapshot.json()["snapshot"]["title"] != "重新修改的报告"
    assert snapshot.json()["content_hash"] == approval["content_hash"]
    r["export"]("formal", expected=409)


def test_self_approval_and_unassigned_project_editor_denied(reports):
    r = reports
    r["mutate"]("/reviewer", {"reviewer_id": str(r["users"][0])}, method="PUT", expected=409)
    assert r["reviewer"].get(r["path"]).status_code == 404
    r["assign"]()
    r["mutate"]("/submit", {})
    r["mutate"](
        "/review",
        {"decision": "approve", "notes": "作者不能审核自己的报告。", **CONFIRM},
        expected=404,
    )
    r["mutate"](
        "/review",
        {"decision": "approve", "notes": "没有确认所有检查项。"},
        client=r["reviewer"],
        expected=422,
    )


def test_wrong_quote_or_amount_cannot_be_verified(reports):
    r = reports
    r["assign"]()
    r["add_number"](value="12")
    r["mutate"]("/submit", {})
    metric = r["current"]()["metrics"][0]
    r["mutate"](
        f"/metrics/{metric['id']}/review",
        {"status": "verified", "notes": "错误数字不能通过字面核验。"},
        client=r["reviewer"],
        expected=409,
    )
    r["mutate"](
        f"/metrics/{metric['id']}/review",
        {"status": "not_applicable", "notes": "有数值不能标记为不适用。"},
        client=r["reviewer"],
        expected=422,
    )


def test_metric_edit_resets_verification_and_revision_conflicts(reports):
    r = reports
    r["assign"]()
    r["add_number"]()
    r["mutate"]("/submit", {})
    metric = r["current"]()["metrics"][0]
    r["mutate"](
        f"/metrics/{metric['id']}/review",
        {"status": "verified", "notes": "对照原文完成合成数字核验。"},
        client=r["reviewer"],
    )
    data = r["current"]()
    item = data["metrics"][0]
    fields = {
        key: item[key]
        for key in [
            "metric_name",
            "metric_type",
            "metric_value",
            "unit",
            "currency",
            "period",
            "evidence_id",
            "source_quote",
            "notes",
        ]
    }
    r["mutate"](f"/metrics/{item['id']}", fields, method="PUT")
    assert r["current"]()["metrics"][0]["verification_status"] == "unverified"
    assert (
        r["owner"]
        .put(
            r["path"],
            json={
                "expected_revision": data["revision"],
                "title": data["title"],
                "content": data["content"],
            },
        )
        .status_code
        == 409
    )


def test_cross_org_unassigned_viewer_and_curator_export_denied(reports):
    r = reports
    with Session(r["engine"]) as db:
        db.get(User, r["users"][4]).is_data_curator = True
        db.commit()
    for index in [1, 2, 3, 4]:
        user = r["login"](index)
        assert user.get(r["path"]).status_code == 404
        assert user.post(
            r["path"] + "/export",
            json={
                "expected_revision": 1,
                "mode": "draft",
                "format": "md",
                "idempotency_key": str(uuid4()),
            },
        ).status_code in {403, 404}
    data = r["owner"].get(r["reports_base"]).json()
    assert "content" not in data[0] and "title" not in data[0]


def test_original_deletion_blocks_replayed_export_and_no_artifact_remains(reports):
    r = reports
    key = str(uuid4())
    r["export"](key=key)
    assert (
        r["owner"]
        .request("DELETE", f"{r['base']}/{r['doc']['id']}", json={"expected_revision": 1})
        .status_code
        == 202
    )
    assert r["owner"].get(r["path"]).status_code == 404
    assert (
        r["owner"]
        .post(
            r["path"] + "/export",
            json={"expected_revision": 1, "mode": "draft", "format": "md", "idempotency_key": key},
        )
        .status_code
        == 404
    )
    with Session(r["engine"]) as db:
        assert len(db.scalars(select(ReportExport)).all()) == 1


def test_reviewer_role_revocation_invalidates_formal_export(reports):
    r = reports
    r["assign"]()
    r["mutate"]("/submit", {})
    r["approve"]()
    r["export"]("formal")
    with Session(r["engine"]) as db:
        db.get(Membership, (r["org"], r["users"][1])).role = "viewer"
        db.commit()
    r["export"]("formal", expected=409)


def test_report_from_agent_draft_preserves_provenance_and_bp_template(knowledge):
    from app.models.agents import TaskRun
    from app.reports.templates import body

    k = knowledge
    owner = k["owner"]
    with Session(k["engine"]) as db:
        task = TaskRun(
            organization_id=k["org"],
            project_id=UUID(k["project"]),
            requested_by=k["users"][0],
            kind="bp_screening",
            inputs={},
            input_digest="x" * 64,
            idempotency_key=uuid4(),
            prompt_version="bp_screening@1.0.0",
            prompt_hash="a" * 64,
            status="review_required",
            result=body("bp_screening"),
            evidence_refs=[],
        )
        db.add(task)
        db.commit()
        identity = str(task.id)
    response = owner.post(
        f"/api/v1/organizations/{k['org']}/projects/{k['project']}/reports",
        json={
            "title": "任务转入草案",
            "template": "bp_screening",
            "source_task_id": identity,
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["provenance"]["task_id"] == identity
    assert len(data["content"]["sections"]) == 13 and data["status"] == "draft"


def test_formal_export_does_not_append_unregistered_original_numbers(reports):
    r = reports
    r["assign"]()
    r["mutate"]("/submit", {})
    r["approve"]()
    formal = r["export"]("formal").text
    assert "1.2" not in formal and "1\\.2" not in formal
    assert "正式文件不自动附带" in formal
    assert "1\\.2" in r["export"]("draft").text


def test_unit_mismatch_in_body_cannot_reuse_a_verified_different_unit(reports):
    r = reports
    r["assign"]()
    r["save_number"]()
    r["add_number"]()
    r["mutate"]("/submit", {})
    metric = r["current"]()["metrics"][0]
    r["mutate"](
        f"/metrics/{metric['id']}/review",
        {"status": "verified", "notes": "已按原文完成数字核验。"},
        client=r["reviewer"],
    )
    state = r["current"]()
    content = deepcopy(state["content"])
    content["summary"]["text"] = "营业收入为1.2元。"
    r["mutate"]("", {"title": state["title"], "content": content}, method="PUT")
    assert "UNREGISTERED_NUMBER" in {i["code"] for i in r["current"]()["quality"]["issues"]}


def test_new_document_version_blocks_previously_authorized_report_export(reports):
    import base64

    r = reports
    key = str(uuid4())
    r["export"](key=key)
    response = r["owner"].post(
        f"{r['base']}/{r['doc']['id']}/versions",
        json={
            "expected_revision": 1,
            "filename": "updated.txt",
            "content_base64": base64.b64encode("新版资料，不再使用旧版数字。".encode()).decode(),
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 202
    assert r["owner"].get(r["path"]).status_code == 409
    assert (
        r["owner"]
        .post(
            r["path"] + "/export",
            json={"expected_revision": 1, "mode": "draft", "format": "md", "idempotency_key": key},
        )
        .status_code
        == 409
    )


def test_revoked_reviewer_original_acl_blocks_owner_formal_export(reports):
    r = reports
    r["assign"]()
    r["mutate"]("/submit", {})
    r["approve"]()
    r["export"]("formal")
    response = r["owner"].put(
        f"{r['base']}/{r['doc']['id']}/permissions",
        json={
            "expected_revision": 1,
            "access_scope": "restricted",
            "grants": [{"user_id": str(r["users"][0]), "role": "editor"}],
        },
    )
    assert response.status_code == 200
    assert r["reviewer"].get(r["path"]).status_code == 404
    r["export"]("formal", expected=404)


def test_draft_export_can_be_disabled_without_relaxing_formal_gate(reports, monkeypatch):
    from app.api import reports as routes
    from app.core.config import get_settings

    r = reports
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: get_settings().model_copy(update={"report_allow_draft_export": False}),
    )
    r["export"]("draft", expected=403)
    r["export"]("formal", expected=409)


def test_simultaneous_approval_and_author_edit_never_leave_edit_approved(reports):
    from concurrent.futures import ThreadPoolExecutor

    r = reports
    r["assign"]()
    r["mutate"]("/submit", {})
    state = r["current"]()
    rev = state["revision"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        approval = pool.submit(
            r["reviewer"].post,
            r["path"] + "/review",
            json={
                "expected_revision": rev,
                "decision": "approve",
                "notes": "并发审核测试，核对未知信息与来源。",
                **CONFIRM,
            },
        )
        edit = pool.submit(
            r["owner"].put,
            r["path"],
            json={
                "expected_revision": rev,
                "title": "并发修改后的报告",
                "content": state["content"],
            },
        )
        assert edit.result().status_code == 200
        assert approval.result().status_code in {200, 409}
    assert r["current"]()["status"] == "draft"
    r["export"]("formal", expected=409)


def test_role_revoked_during_render_does_not_release_file(reports, monkeypatch):
    from app.api import reports as routes
    from app.models.identity import ProjectMember

    r = reports
    original = routes.render

    def revoke(*args, **kwargs):
        raw = original(*args, **kwargs)
        with Session(r["engine"]) as db:
            db.get(ProjectMember, (UUID(r["project"]), r["users"][1])).role = "manager"
            db.get(ProjectMember, (UUID(r["project"]), r["users"][0])).role = "viewer"
            db.commit()
        return raw

    monkeypatch.setattr(routes, "render", revoke)
    r["export"]("draft", expected=403)
    with Session(r["engine"]) as db:
        assert not db.scalars(select(ReportExport)).all()


def test_source_updated_during_render_does_not_release_stale_file(reports, monkeypatch):
    import base64

    from app.api import reports as routes

    r = reports
    original = routes.render

    def change_source(*args, **kwargs):
        raw = original(*args, **kwargs)
        response = r["reviewer"].post(
            f"{r['base']}/{r['doc']['id']}/versions",
            json={
                "expected_revision": 1,
                "filename": "new.txt",
                "content_base64": base64.b64encode(
                    "新版授权资料，不使用旧版金额。".encode()
                ).decode(),
                "idempotency_key": str(uuid4()),
            },
        )
        assert response.status_code == 202, response.text
        return raw

    monkeypatch.setattr(routes, "render", change_source)
    r["export"]("draft", expected=409)
    with Session(r["engine"]) as db:
        assert not db.scalars(select(ReportExport)).all()
