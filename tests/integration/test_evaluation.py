from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fixtures.agent_provider import synthetic_result
from sqlalchemy.orm import Session

from app.agents.evidence import public_evidence_hash
from app.evaluation.engine import execute_evaluation
from app.knowledge.workflow import execute_ingestion
from app.models.agents import TaskRun
from app.models.catalog import Evidence
from app.models.evaluation import EvaluationRun
from app.models.identity import Membership, now

pytestmark = pytest.mark.integration


@pytest.fixture
def evaluation(knowledge, catalog):
    k = knowledge
    companies = [catalog["create"]("Eval cohort " + name) for name in ["Alpha", "Beta", "Gamma"]]
    doc_a, _ = k["upload"]("客户验证独有甲资料，需要核实原文。")
    doc_b, _ = k["upload"]("天气降雨独有乙资料，尚无产业内容。")
    while execute_ingestion(k["engine"]):
        pass
    with Session(k["engine"]) as db:
        e = Evidence(
            company_id=UUID(companies[0]["id"]),
            source_id=UUID(catalog["source_id"]),
            claim_text="合成公司已提交客户验证材料。",
            excerpt="合成公司已提交客户验证材料。",
            classification="fact",
            verification_status="verified",
        )
        db.add(e)
        db.flush()
        ref = {
            "id": "evidence:" + str(e.id),
            "kind": "public_evidence",
            "resource_id": str(e.id),
            "hash": public_evidence_hash(e),
        }
        result = synthetic_result(
            {
                "workflow": "company_profile",
                "candidate_company_ids": [companies[0]["id"]],
                "evidence": [{"id": ref["id"]}],
            }
        )
        for claim in [result["summary"], *[c for s in result["sections"] for c in s["claims"]]]:
            claim.update(text=e.claim_text, classification="fact", evidence_ids=[ref["id"]])
        task = TaskRun(
            organization_id=k["org"],
            project_id=UUID(k["project"]),
            requested_by=k["users"][0],
            kind="company_profile",
            inputs={},
            input_digest="e" * 64,
            idempotency_key=uuid4(),
            prompt_version="company_profile@1.0.0",
            prompt_hash="a" * 64,
            status="review_required",
            result=result,
            evidence_refs=[ref],
        )
        db.add(task)
        db.commit()
        task_id = str(task.id)
    base = f"/api/v1/organizations/{k['org']}/projects/{k['project']}/evaluations"
    cases = [
        {
            "id": "search",
            "kind": "company_search",
            "filters": {"q": "Eval cohort"},
            "k": 3,
            "relevance": [
                {"company_id": c["id"], "grade": g} for c, g in zip(companies, [3, 1, 0])
            ],
        },
        {
            "id": "retrieval",
            "kind": "knowledge_retrieval",
            "query": "客户验证独有甲",
            "mode": "keyword",
            "k": 1,
            "relevance": [
                {"document_id": doc_a["id"], "grade": 3},
                {"document_id": doc_b["id"], "grade": 0},
            ],
        },
        {
            "id": "facts",
            "kind": "fact_extraction",
            "task_id": task_id,
            "expected_claims": [{"text": "合成公司已提交客户验证材料。", "classification": "fact"}],
        },
        {
            "id": "bp_waiting",
            "kind": "bp_screening",
            "expected_claims": [{"text": "尚缺模型结果", "classification": "unknown"}],
        },
    ]

    def create(reviewer=False, **extra):
        payload = {
            "name": "合成评测集",
            "version": 1,
            "data_kind": "synthetic",
            "source_description": "明确合成的数据库与文档测试，不是客户试点。",
            "authorized_for_evaluation": True,
            "idempotency_key": str(uuid4()),
            "cases": cases,
            **extra,
        }
        if reviewer:
            payload["reviewer_id"] = str(k["users"][1])
        response = k["owner"].post(base, json=payload)
        assert response.status_code == 201, response.text
        return response.json(), payload

    def start(dataset, client=None):
        payload = {"idempotency_key": str(uuid4())}
        response = (client or k["owner"]).post(base + "/" + dataset["id"] + "/runs", json=payload)
        assert response.status_code == 202, response.text
        return response.json(), payload

    def get(run, client=None):
        response = (client or k["owner"]).get(base + "/runs/" + run["id"])
        assert response.status_code == 200, response.text
        return response.json()

    return {
        **k,
        "eval_base": base,
        "companies": companies,
        "doc_a": doc_a,
        "doc_b": doc_b,
        "cases": cases,
        "task_id": task_id,
        "create_dataset": create,
        "start_run": start,
        "get_run": get,
    }


def test_ranked_search_and_retrieval_are_measured_on_real_data(evaluation):
    e = evaluation
    dataset, _ = e["create_dataset"]()
    run, _ = e["start_run"](dataset)
    assert execute_evaluation(e["engine"])
    data = e["get_run"](run)
    assert data["status"] == "completed" and len(data["records"]) == 4
    rows = {r["case_id"]: r for r in data["records"]}
    assert rows["search"]["metrics"]["precision_at_k"] == pytest.approx(2 / 3)
    assert rows["retrieval"]["metrics"]["precision_at_k"] == 1
    assert rows["facts"]["metrics"]["exact_claim_precision"] == 1
    assert len(rows["facts"]["observed_claims"]) == 1
    assert rows["bp_waiting"]["status"] == "blocked" and rows["bp_waiting"]["metrics"] == {}
    assert data["summary"]["independent_fact_accuracy"] is None
    assert (
        data["summary"]["business_assessment"] == "not_assessed"
        and data["summary"]["new_model_calls"] == 0
    )


def test_dataset_version_and_run_idempotency(evaluation):
    e = evaluation
    dataset, payload = e["create_dataset"]()
    assert e["owner"].post(e["eval_base"], json=payload).json()["id"] == dataset["id"]
    assert (
        e["owner"]
        .post(
            e["eval_base"],
            json={**payload, "source_description": "输入被修改，不能悄悄覆盖已有样本。"},
        )
        .status_code
        == 409
    )
    assert (
        e["owner"]
        .post(e["eval_base"], json={**payload, "idempotency_key": str(uuid4())})
        .status_code
        == 409
    )
    run, rpayload = e["start_run"](dataset)
    assert (
        e["owner"].post(e["eval_base"] + "/" + dataset["id"] + "/runs", json=rpayload).json()["id"]
        == run["id"]
    )


def test_independent_feedback_and_self_feedback_are_separate(evaluation):
    e = evaluation
    dataset, _ = e["create_dataset"](reviewer=True)
    run, _ = e["start_run"](dataset)
    execute_evaluation(e["engine"])
    data = e["get_run"](run)
    path = e["eval_base"] + "/runs/" + run["id"] + "/feedback"
    payload = {
        "case_id": "facts",
        "result_hash": data["result_hash"],
        "usable": True,
        "numeric_correct": None,
        "claim_judgments": [{"index": 0, "correct": True}],
        "category": "fact",
        "severity": "low",
        "notes": "逐条核对合成原文，仅测试人工标注流程。",
    }
    assert e["owner"].post(path, json=payload).json()["independent"] is False
    assert e["get_run"](run)["summary"]["independent_fact_accuracy"] is None
    peer = e["login"](1)
    assert peer.post(path, json=payload).json()["independent"] is True
    summary = e["get_run"](run)["summary"]
    assert (
        summary["independent_fact_accuracy"] == 1 and summary["independent_fact_judged_count"] == 1
    )
    assert summary["business_assessment"] == "not_assessed"
    assert (
        peer.post(
            path, json={**payload, "claim_judgments": [{"index": 2, "correct": True}]}
        ).status_code
        == 422
    )
    assert peer.post(path, json={**payload, "result_hash": "0" * 64}).status_code == 409


def test_other_member_and_tenant_cannot_read_evaluation(evaluation):
    e = evaluation
    dataset, _ = e["create_dataset"]()
    run, _ = e["start_run"](dataset)
    execute_evaluation(e["engine"])
    for user in [1, 2, 3, 4]:
        client = e["login"](user)
        assert client.get(e["eval_base"] + "/" + dataset["id"]).status_code == 404
        assert client.get(e["eval_base"] + "/runs/" + run["id"]).status_code == 404
    assert "definition" not in e["owner"].get(e["eval_base"]).json()[0]


def test_document_revoke_blocks_stored_metrics_and_feedback(evaluation):
    e = evaluation
    dataset, _ = e["create_dataset"](reviewer=True)
    run, _ = e["start_run"](dataset)
    execute_evaluation(e["engine"])
    peer = e["login"](1)
    assert peer.get(e["eval_base"] + "/runs/" + run["id"]).status_code == 200
    assert (
        e["owner"]
        .put(
            f"{e['base']}/{e['doc_a']['id']}/permissions",
            json={
                "expected_revision": 1,
                "access_scope": "restricted",
                "grants": [{"user_id": str(e["users"][0]), "role": "editor"}],
            },
        )
        .status_code
        == 200
    )
    assert peer.get(e["eval_base"] + "/runs/" + run["id"]).status_code == 404


def test_cancelled_evaluation_is_not_executed(evaluation):
    e = evaluation
    dataset, _ = e["create_dataset"]()
    run, _ = e["start_run"](dataset)
    assert e["owner"].post(e["eval_base"] + "/runs/" + run["id"] + "/cancel").status_code == 202
    assert not execute_evaluation(e["engine"])
    assert e["get_run"](run)["status"] == "cancelled"


def test_actor_revocation_and_stale_worker_recovery(evaluation):
    e = evaluation
    dataset, _ = e["create_dataset"]()
    run, _ = e["start_run"](dataset)
    with Session(e["engine"]) as db:
        item = db.get(EvaluationRun, UUID(run["id"]))
        item.status = "running"
        item.attempts = 1
        item.lease_until = now() - timedelta(minutes=10)
        db.commit()
    execute_evaluation(e["engine"])
    assert e["get_run"](run)["status"] == "completed"
    assert e["get_run"](run)["attempts"] == 2
    fresh, _ = e["start_run"](dataset)
    with Session(e["engine"]) as db:
        db.get(Membership, (e["org"], e["users"][0])).is_active = False
        db.commit()
    execute_evaluation(e["engine"])
    with Session(e["engine"]) as db:
        row = db.get(EvaluationRun, UUID(fresh["id"]))
        assert row.status == "failed" and row.error_code == "ACCESS_REVOKED" and not row.records


def test_unjudged_retrieved_document_also_guards_stored_run(evaluation):
    e = evaluation
    peer = e["login"](1)
    extra, _ = e["upload"]("客户验证独有甲，新增的未标注授权材料。", client=peer)
    while execute_ingestion(e["engine"]):
        pass
    retrieval = {
        **e["cases"][1],
        "k": 2,
        "relevance": [{"document_id": e["doc_a"]["id"], "grade": 3}],
    }
    dataset, _ = e["create_dataset"](cases=[retrieval])
    run, _ = e["start_run"](dataset)
    execute_evaluation(e["engine"])
    record = e["get_run"](run)["records"][0]
    assert record["metrics"]["precision_at_k"] is None
    assert record["metrics"]["judgment_coverage"] == 0.5
    assert (
        peer.put(
            f"{e['base']}/{extra['id']}/permissions",
            json={
                "expected_revision": 1,
                "access_scope": "restricted",
                "grants": [{"user_id": str(e["users"][1]), "role": "editor"}],
            },
        ).status_code
        == 200
    )
    assert e["owner"].get(e["eval_base"] + "/runs/" + run["id"]).status_code == 404


def test_dataset_source_change_blocks_old_runs(evaluation):
    from app.models.catalog import Company

    e = evaluation
    dataset, _ = e["create_dataset"]()
    run, _ = e["start_run"](dataset)
    execute_evaluation(e["engine"])
    with Session(e["engine"]) as db:
        db.get(
            Company, UUID(e["companies"][0]["id"])
        ).description = "来源已更新，不能悄悄用新数据覆盖旧评测"
        db.commit()
    assert e["owner"].get(e["eval_base"] + "/runs/" + run["id"]).status_code == 409


def test_json_export_rechecks_live_permissions(evaluation):
    e = evaluation
    dataset, _ = e["create_dataset"](reviewer=True)
    run, _ = e["start_run"](dataset)
    execute_evaluation(e["engine"])
    peer = e["login"](1)
    url = e["eval_base"] + "/runs/" + run["id"] + "/export"
    exported = peer.get(url)
    assert exported.status_code == 200 and "attachment" in exported.headers["content-disposition"]
    assert exported.headers["cache-control"] == "no-store"
    assert exported.json()["dataset"]["content_hash"] == dataset["content_hash"]
    assert exported.json()["evidence"]
    assert (
        e["owner"]
        .put(
            f"{e['base']}/{e['doc_a']['id']}/permissions",
            json={
                "expected_revision": 1,
                "access_scope": "restricted",
                "grants": [{"user_id": str(e["users"][0]), "role": "editor"}],
            },
        )
        .status_code
        == 200
    )
    assert peer.get(url).status_code == 404


def test_blocked_model_case_cannot_receive_a_fake_usable_rating(evaluation):
    e = evaluation
    dataset, _ = e["create_dataset"]()
    run, _ = e["start_run"](dataset)
    execute_evaluation(e["engine"])
    data = e["get_run"](run)
    response = e["owner"].post(
        e["eval_base"] + "/runs/" + run["id"] + "/feedback",
        json={
            "case_id": "bp_waiting",
            "result_hash": data["result_hash"],
            "usable": True,
            "category": "usability",
            "severity": "low",
            "notes": "不能给尚无模型结果的案例打可用分数。",
        },
    )
    assert response.status_code == 422


def test_configured_provider_still_does_not_implicitly_call_a_model(evaluation, monkeypatch):
    from app.agents import gateway
    from app.evaluation import engine

    e = evaluation
    monkeypatch.setattr(engine, "configuration", lambda: {"configured": True})
    monkeypatch.setattr(
        gateway,
        "complete",
        lambda *args, **kwargs: pytest.fail("Evaluation must not invoke a provider"),
    )
    dataset, _ = e["create_dataset"](cases=[e["cases"][-1]])
    run, _ = e["start_run"](dataset)
    execute_evaluation(e["engine"])
    data = e["get_run"](run)
    assert data["records"][0]["error_code"] == "COMPLETED_TASK_REQUIRED"
    assert data["summary"]["measured_count"] == 0 and data["summary"]["new_model_calls"] == 0


def test_evaluation_share_can_be_revoked_without_changing_labeled_version(evaluation):
    e = evaluation
    dataset, _ = e["create_dataset"](reviewer=True)
    run, _ = e["start_run"](dataset)
    execute_evaluation(e["engine"])
    peer = e["login"](1)
    assert peer.get(e["eval_base"] + "/runs/" + run["id"]).status_code == 200
    response = e["owner"].delete(e["eval_base"] + "/" + dataset["id"] + "/reviewer")
    assert response.status_code == 200 and response.json()["reviewer_id"] is None
    assert response.json()["content_hash"] == dataset["content_hash"]
    assert peer.get(e["eval_base"] + "/runs/" + run["id"]).status_code == 404
    assert peer.get(e["eval_base"] + "/runs/" + run["id"] + "/export").status_code == 404


def test_report_quality_expectations_are_measured_and_pin_report_revision(evaluation):
    e = evaluation
    report_base = f"/api/v1/organizations/{e['org']}/projects/{e['project']}/reports"
    created = e["owner"].post(
        report_base,
        json={
            "title": "合成质量闸评测报告",
            "template": "company_profile",
            "idempotency_key": str(uuid4()),
        },
    )
    assert created.status_code == 201, created.text
    report = created.json()
    cases = [
        {
            "id": "gate_match",
            "kind": "report_quality",
            "report_id": report["id"],
            "expected_gate_passed": True,
        },
        {
            "id": "gate_mismatch",
            "kind": "report_quality",
            "report_id": report["id"],
            "expected_gate_passed": False,
        },
    ]
    dataset, _ = e["create_dataset"](cases=cases)
    run, _ = e["start_run"](dataset)
    execute_evaluation(e["engine"])
    data = e["get_run"](run)
    assert data["records"][0]["metrics"]["gate_expectation_match"] == 1
    assert data["records"][1]["metrics"]["gate_expectation_match"] == 0
    assert data["status"] == "completed"  # Completed measurement is not a passing assertion.
    response = e["owner"].put(
        report_base + "/" + report["id"],
        json={
            "expected_revision": report["revision"],
            "title": "已修改来源报告",
            "content": report["content"],
        },
    )
    assert response.status_code == 200
    assert e["owner"].get(e["eval_base"] + "/runs/" + run["id"]).status_code == 409


def test_dataset_sharing_does_not_bypass_private_report_participants(evaluation):
    e = evaluation
    report_base = f"/api/v1/organizations/{e['org']}/projects/{e['project']}/reports"
    report = (
        e["owner"]
        .post(
            report_base,
            json={
                "title": "没有共享给评审的报告",
                "template": "company_profile",
                "idempotency_key": str(uuid4()),
            },
        )
        .json()
    )
    response = e["owner"].post(
        e["eval_base"],
        json={
            "name": "不得旁路私有报告",
            "version": 1,
            "data_kind": "synthetic",
            "source_description": "合成权限测试，不授予底层报告读取资格。",
            "authorized_for_evaluation": True,
            "reviewer_id": str(e["users"][1]),
            "idempotency_key": str(uuid4()),
            "cases": [
                {
                    "id": "report",
                    "kind": "report_quality",
                    "report_id": report["id"],
                    "expected_gate_passed": True,
                }
            ],
        },
    )
    assert response.status_code == 404


@pytest.mark.parametrize("scope", ["project", "organization"])
def test_idempotency_and_dataset_versions_are_bound_to_request_scope(evaluation, scope):
    e = evaluation
    dataset, payload = e["create_dataset"](cases=[e["cases"][-1]])
    if scope == "project":
        org = e["org"]
        manager = e["owner"]
    else:
        org = e["orgs"][1]
        manager = e["login"](3)
        response = manager.post(
            f"/api/v1/organizations/{org}/members",
            json={"email": "user0@example.com", "role": "member"},
        )
        assert response.status_code == 201, response.text
    project = manager.post(
        f"/api/v1/organizations/{org}/projects", json={"name": "另一请求范围"}
    ).json()
    if scope == "organization":
        assert (
            manager.put(
                f"/api/v1/organizations/{org}/projects/{project['id']}/members",
                json={"user_id": str(e["users"][0]), "role": "editor"},
            ).status_code
            == 200
        )
    other = f"/api/v1/organizations/{org}/projects/{project['id']}/evaluations"
    assert e["owner"].post(other, json=payload).status_code == 409
    fresh = e["owner"].post(other, json={**payload, "idempotency_key": str(uuid4())})
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["id"] != dataset["id"]
    assert e["owner"].get(other + "/" + dataset["id"]).status_code == 404
