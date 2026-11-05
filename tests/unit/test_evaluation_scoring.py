from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.evaluation.scoring import claim_metrics, ranked_metrics, summary
from app.schemas.evaluation import DatasetInput


def test_ranked_metrics_are_denominator_aware_and_do_not_guess_unjudged():
    result = ranked_metrics(["a", "b", "c"], {"a": 3, "b": 1, "c": 0}, 3)
    assert result["precision_at_k"] == pytest.approx(2 / 3)
    assert result["recall_on_labeled_positives"] == 1 and result["ndcg_at_k"] == 1
    assert ranked_metrics(["a"], {"a": 1}, 10)["precision_at_k"] == 0.1
    partial = ranked_metrics(["a", "unknown"], {"a": 1}, 2)
    assert partial["precision_at_k"] is None and partial["ndcg_at_k"] is None
    assert partial["judgment_coverage"] == 0.5 and partial["precision_on_judged"] == 1
    empty = ranked_metrics([], {"a": 1}, 3)
    assert empty["judgment_coverage"] is None and empty["recall_on_labeled_positives"] == 0
    assert ranked_metrics(["a"], {"a": 0}, 1)["recall_on_labeled_positives"] is None


def test_exact_match_is_not_semantic_grading_and_ignores_duplicate_claims():
    expected = [{"text": "收入为1.2亿元", "classification": "unverified"}]
    observed = [*expected, *expected, {"text": "收入为1.2元", "classification": "unverified"}]
    scores = claim_metrics(observed, expected)
    assert scores["exact_claim_precision"] == 0.5 and scores["exact_claim_recall"] == 1
    assert scores["unknown_exact_recall"] is None


def test_no_human_feedback_means_unknown_not_zero_or_perfect():
    records = [
        {
            "case_id": "fact",
            "kind": "fact_extraction",
            "status": "measured",
            "latency_ms": 10,
            "observed_claims": [{"classification": "fact", "text": "x"}],
            "metrics": {},
        },
        {
            "case_id": "bp",
            "kind": "bp_screening",
            "status": "blocked",
            "error_code": "MODEL_NOT_CONFIGURED",
            "latency_ms": 1,
        },
    ]
    empty = summary(records, [], "synthetic")
    assert (
        empty["independent_fact_accuracy"] is None
        and empty["business_assessment"] == "not_assessed"
    )
    self_rating = SimpleNamespace(
        created_by="owner",
        case_id="fact",
        independent=False,
        usable=True,
        numeric_correct=True,
        claim_judgments=[{"index": 0, "correct": True}],
    )
    assert summary(records, [self_rating], "authorized")["independent_fact_accuracy"] is None
    peer = SimpleNamespace(
        created_by="peer",
        case_id="fact",
        independent=True,
        usable=False,
        numeric_correct=False,
        claim_judgments=[{"index": 0, "correct": False}],
    )
    measured = summary(records, [self_rating, peer], "authorized")
    assert (
        measured["independent_fact_accuracy"] == 0
        and measured["independent_fact_review_coverage"] == 1
    )
    assert measured["failure_types"] == {"MODEL_NOT_CONFIGURED": 1}


def test_dataset_requires_attestation_and_unique_case_ids():
    from uuid import uuid4

    case = {
        "id": "bp",
        "kind": "bp_screening",
        "expected_claims": [{"text": "资料缺失", "classification": "unknown"}],
    }
    payload = {
        "name": "合成集",
        "version": 1,
        "data_kind": "synthetic",
        "source_description": "只用于自动化测试的合成资料",
        "idempotency_key": str(uuid4()),
        "cases": [case],
    }
    with pytest.raises(ValidationError):
        DatasetInput.model_validate(payload)
    with pytest.raises(ValidationError):
        DatasetInput.model_validate(
            {**payload, "authorized_for_evaluation": True, "cases": [case, case]}
        )


def test_duplicate_task_cases_do_not_inflate_independent_fact_sample_size():
    records = [
        {
            "case_id": case,
            "kind": "fact_extraction",
            "status": "measured",
            "latency_ms": 1,
            "provenance": {"task_id": "same-task"},
            "observed_claims": [{"text": "same fact", "classification": "fact"}],
        }
        for case in ["one", "two"]
    ]
    ratings = [
        SimpleNamespace(
            created_by="peer",
            case_id=case,
            independent=True,
            usable=correct,
            numeric_correct=None,
            claim_judgments=[{"index": 0, "correct": correct}],
        )
        for case, correct in [("one", True), ("two", False)]
    ]
    result = summary(records, ratings, "authorized")
    assert result["fact_claim_count"] == 1 and result["unique_upstream_tasks"] == 1
    assert result["independent_fact_accuracy"] is None
    assert result["conflicting_human_judgment_count"] == 2
    assert result["independent_model_usability_rate"] is None


def test_demo_command_does_not_reuse_stale_test_evidence(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from app.evaluation import demo
    from app.evaluation.demos import DEMOS

    stale = {
        "exit_code": 0,
        "tests": {node: {"outcome": "passed"} for d in DEMOS for node in d["nodes"]},
    }
    (tmp_path / "test-outcomes.json").write_text(json.dumps(stale))
    monkeypatch.setattr("sys.argv", ["demo", "--output", str(tmp_path)])
    monkeypatch.setattr(
        demo.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0)
    )
    assert demo.main() == 1
    result = json.loads((tmp_path / "eight-demos.json").read_text())
    assert result["exit_code"] == 1 and all(
        d["regression_status"] == "incomplete_or_failed" for d in result["demos"]
    )
