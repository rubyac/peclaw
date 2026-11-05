import time
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.gateway import ModelError, configuration
from app.catalog.service import search
from app.evaluation.scoring import claim_metrics, normalized, ranked_metrics
from app.evaluation.service import dataset_access, digest, merge_refs
from app.knowledge.retrieval import search_private
from app.models.agents import ModelCall, TaskRun
from app.models.evaluation import EvaluationDataset, EvaluationRun
from app.models.identity import User, now
from app.reports.quality import claims, quality
from app.reports.service import access as report_access
from app.reports.sources import resolve
from app.schemas.catalog import SearchFilters
from app.schemas.knowledge import KnowledgeQuery
from app.services.audit import audit


def execute_case(db, user, dataset, case):
    org, project = dataset.organization_id, dataset.project_id
    record = {
        "case_id": case["id"],
        "kind": case["kind"],
        "status": "measured",
        "metrics": {},
        "error_code": None,
    }
    refs = []
    if case["kind"] == "company_search":
        filters = SearchFilters.model_validate(case["filters"]).model_copy(
            update={"limit": case["k"], "offset": 0, "include_archived": False}
        )
        response = search(db, filters)
        ranked = [str(item["id"]) for item in response["items"]]
        record["metrics"] = ranked_metrics(
            ranked, {label["company_id"]: label["grade"] for label in case["relevance"]}, case["k"]
        )
        record["ranked_ids"] = ranked
        record["applied_filters"] = filters.model_dump(mode="json")
    elif case["kind"] == "knowledge_retrieval":
        response = search_private(
            db,
            user,
            org,
            KnowledgeQuery(query=case["query"], project_id=project, mode=case["mode"], limit=50),
        )
        ranked = list(dict.fromkeys(str(item["document_id"]) for item in response["items"]))[
            : case["k"]
        ]
        record["ranked_ids"] = ranked
        record["metrics"] = ranked_metrics(
            ranked, {label["document_id"]: label["grade"] for label in case["relevance"]}, case["k"]
        )
        record["semantic_available"] = response["semantic_available"]
        from app.knowledge.embedding import MODEL_ID

        record["retrieval_model_id"] = MODEL_ID
        for item in response["items"]:
            refs.append(
                {
                    "id": "chunk:" + str(item["chunk_id"]),
                    "kind": "private_chunk",
                    "resource_id": str(item["chunk_id"]),
                    "document_id": str(item["document_id"]),
                    "version_id": str(item["version_id"]),
                    "hash": item["content_hash"],
                }
            )
    elif case["kind"] in {"fact_extraction", "bp_screening"}:
        if not case["task_id"]:
            record.update(
                status="blocked",
                error_code="MODEL_NOT_CONFIGURED"
                if not configuration()["configured"]
                else "COMPLETED_TASK_REQUIRED",
            )
            return record, refs
        binding = dataset.bindings[case["id"]]
        task = db.get(TaskRun, UUID(binding["id"]))
        unique = {}
        for claim in claims(task.result):
            key = (normalized(claim["text"]), claim["classification"])
            if key not in unique:
                unique[key] = {**claim, "evidence_ids": list(claim["evidence_ids"])}
            else:
                unique[key]["evidence_ids"] = sorted(
                    set(unique[key]["evidence_ids"]) | set(claim["evidence_ids"])
                )
        observed = list(unique.values())
        record["observed_claims"] = observed
        record["observed_output"] = task.result
        record["source_author_id"] = binding["author"]
        record["metrics"] = claim_metrics(observed, case["expected_claims"])
        record["provenance"] = {
            "task_id": str(task.id),
            "prompt_version": task.prompt_version,
            "prompt_hash": task.prompt_hash,
            "workflow": task.kind,
        }
        record["upstream_calls"] = [
            {
                key: getattr(call, key)
                for key in [
                    "attempt",
                    "provider",
                    "model",
                    "input_tokens",
                    "output_tokens",
                    "latency_ms",
                    "estimated_cost_micros",
                    "status",
                ]
            }
            for call in db.scalars(
                select(ModelCall).where(ModelCall.task_id == task.id).order_by(ModelCall.attempt)
            )
        ]
        refs.extend(task.evidence_refs)
    else:
        report = report_access(db, user, org, project, UUID(case["report_id"]))
        result = quality(db, user, report)
        record["metrics"] = {
            "gate_expectation_match": float(result["passed"] == case["expected_gate_passed"]),
            "actual_gate_passed": result["passed"],
            "expected_gate_passed": case["expected_gate_passed"],
        }
        record["issue_codes"] = sorted({issue["code"] for issue in result["issues"]})
        record["source_author_id"] = str(report.created_by)
        refs.extend(report.evidence_refs)
    return record, refs


def execute_evaluation(engine):
    with Session(engine) as db:
        for stale in db.scalars(
            select(EvaluationRun)
            .where(
                EvaluationRun.status == "running",
                EvaluationRun.lease_until < now(),
                EvaluationRun.attempts >= 3,
            )
            .with_for_update(skip_locked=True)
            .limit(20)
        ):
            stale.status, stale.error_code, stale.finished_at = (
                "failed",
                "EVALUATION_ATTEMPTS_EXHAUSTED",
                now(),
            )
        db.commit()
        run = db.scalar(
            select(EvaluationRun)
            .where(
                (EvaluationRun.status == "queued")
                | ((EvaluationRun.status == "running") & (EvaluationRun.lease_until < now())),
                EvaluationRun.attempts < 3,
            )
            .order_by(EvaluationRun.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not run:
            return False
        token, run_id = uuid4(), run.id
        run.claim_token, run.status, run.attempts = token, "running", run.attempts + 1
        run.records, run.error_code, run.result_hash = [], None, None
        run.lease_until = now() + timedelta(seconds=300)
        db.commit()
    try:
        with Session(engine) as db:
            current = db.get(EvaluationRun, run_id)
            actor = db.get(User, current.requested_by)
            if not actor or not actor.is_active:
                raise ModelError("ACCESS_REVOKED")
            dataset = db.get(EvaluationDataset, current.dataset_id)
            dataset_access(
                db, actor, dataset.organization_id, dataset.project_id, dataset.id, write=True
            )
            cases = dataset.definition["cases"]
        records = []
        all_refs = []
        for case in cases:
            started = time.monotonic()
            with Session(engine, expire_on_commit=False) as db:
                current = db.get(EvaluationRun, run_id)
                actor = db.get(User, current.requested_by)
                if not actor or not actor.is_active:
                    raise ModelError("ACCESS_REVOKED")
                dataset = dataset_access(
                    db, actor, dataset.organization_id, dataset.project_id, dataset.id, write=True
                )
                if current.claim_token != token or current.status != "running":
                    return True
                try:
                    record, refs = execute_case(db, actor, dataset, case)
                except ModelError as error:
                    record, refs = (
                        {
                            "case_id": case["id"],
                            "kind": case["kind"],
                            "status": "blocked",
                            "metrics": {},
                            "error_code": error.code,
                        },
                        [],
                    )
                record["latency_ms"] = int((time.monotonic() - started) * 1000)
                records.append(record)
                all_refs = merge_refs(all_refs, refs)
            with Session(engine) as db:
                current = db.scalar(
                    select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
                )
                if current.claim_token != token or current.status != "running":
                    return True
                current.lease_until = now() + timedelta(seconds=300)
                db.commit()
        with Session(engine) as db:
            current = db.scalar(
                select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
            )
            if current.claim_token != token or current.status != "running":
                return True
            actor = db.get(User, current.requested_by)
            if not actor or not actor.is_active:
                raise ModelError("ACCESS_REVOKED")
            dataset = dataset_access(
                db, actor, dataset.organization_id, dataset.project_id, dataset.id, write=True
            )
            resolve(db, actor, dataset.organization_id, dataset.project_id, all_refs)
            current.records, current.evidence_refs, current.result_hash = (
                records,
                all_refs,
                digest(records),
            )
            current.status, current.finished_at, current.lease_until = "completed", now(), None
            audit(
                db,
                actor.id,
                dataset.organization_id,
                "evaluation.completed",
                current.id,
                details={"case_count": len(records), "data_kind": dataset.data_kind},
            )
            db.commit()
    except Exception as error:
        code = (
            error.code
            if isinstance(error, ModelError)
            else ("ACCESS_REVOKED" if isinstance(error, HTTPException) else "EVALUATION_FAILED")
        )
        with Session(engine) as db:
            current = db.scalar(
                select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
            )
            if current and current.claim_token == token and current.status == "running":
                current.status, current.error_code, current.finished_at, current.lease_until = (
                    "failed",
                    code,
                    now(),
                    None,
                )
                current.records, current.result_hash = [], None
                dataset = db.get(EvaluationDataset, current.dataset_id)
                audit(
                    db,
                    current.requested_by,
                    dataset.organization_id,
                    "evaluation.failed",
                    current.id,
                    result="failed",
                    details={"code": code},
                )
                db.commit()
    return True
