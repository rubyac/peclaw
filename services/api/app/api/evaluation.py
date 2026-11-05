import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select

from app.agents.gateway import ModelError
from app.evaluation.scoring import summary
from app.evaluation.service import create_dataset, dataset_access, merge_refs, run_access
from app.models.evaluation import EvaluationDataset, EvaluationFeedback, EvaluationRun
from app.models.identity import now
from app.reports.sources import resolve
from app.schemas.evaluation import DatasetInput, FeedbackInput, RunInput
from app.security.dependencies import CurrentUser, Db, deny, project_access
from app.services.audit import audit

router = APIRouter(prefix="/api/v1", tags=["evaluation"])
BASE = "/organizations/{organization_id}/projects/{project_id}/evaluations"


def failure(error):
    return HTTPException(
        409,
        detail={
            "code": error.code,
            "message": "评测来源未就绪、已改变或不可用，请核对来源并创建新版本。",
        },
    )


def guarded(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ModelError as error:
        raise failure(error) from None


def dataset_meta(dataset):
    return {
        key: getattr(dataset, key)
        for key in [
            "id",
            "version",
            "data_kind",
            "created_by",
            "reviewer_id",
            "content_hash",
            "created_at",
        ]
    }


def run_meta(run):
    return {
        key: getattr(run, key)
        for key in [
            "id",
            "dataset_id",
            "requested_by",
            "status",
            "attempts",
            "error_code",
            "result_hash",
            "engine_version",
            "created_at",
            "finished_at",
        ]
    }


@router.get("/evaluations/definitions")
def definitions(user: CurrentUser):
    return {
        "schema_version": "evaluation@1.0.0",
        "dataset_schema": DatasetInput.model_json_schema(),
        "max_cases": 20,
        "new_model_calls": False,
        "metrics": [
            "precision_at_k",
            "precision_on_judged",
            "judgment_coverage",
            "recall_on_labeled_positives",
            "ndcg_at_k",
            "exact_claim_precision",
            "exact_claim_recall",
            "independent_fact_accuracy",
            "independent_model_usability_rate",
        ],
        "limitations": [
            "未标注检索结果不会擅自判为不相关；完整precision/ndcg在覆盖不足时为未知。",
            "缺少模型结果的案例显示未评测，不能算通过；评测不自动发起模型调用。",
            "真实业务质量需要授权标注和独立反馈，合成集只用于工程回归。",
        ],
    }


@router.post(BASE, status_code=201)
def create(
    organization_id: UUID, project_id: UUID, payload: DatasetInput, user: CurrentUser, db: Db
):
    dataset = guarded(create_dataset, db, user, organization_id, project_id, payload)
    return {**dataset_meta(dataset), "name": dataset.name, "definition": dataset.definition}


@router.get(BASE)
def datasets(
    organization_id: UUID,
    project_id: UUID,
    user: CurrentUser,
    db: Db,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    from app.security.dependencies import project_access

    project_access(db, user, organization_id, project_id)
    return [
        dataset_meta(d)
        for d in db.scalars(
            select(EvaluationDataset)
            .where(
                EvaluationDataset.organization_id == organization_id,
                EvaluationDataset.project_id == project_id,
                (EvaluationDataset.created_by == user.id)
                | (EvaluationDataset.reviewer_id == user.id),
            )
            .order_by(EvaluationDataset.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ]


@router.get(BASE + "/{dataset_id}")
def get_dataset(
    organization_id: UUID, project_id: UUID, dataset_id: UUID, user: CurrentUser, db: Db
):
    dataset = guarded(dataset_access, db, user, organization_id, project_id, dataset_id)
    runs = [
        run_meta(r)
        for r in db.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.dataset_id == dataset.id)
            .order_by(EvaluationRun.created_at.desc())
            .limit(100)
        )
    ]
    return {
        **dataset_meta(dataset),
        "name": dataset.name,
        "definition": dataset.definition,
        "runs": runs,
    }


@router.delete(BASE + "/{dataset_id}/reviewer")
def revoke_reviewer(
    organization_id: UUID, project_id: UUID, dataset_id: UUID, user: CurrentUser, db: Db
):
    project_access(db, user, organization_id, project_id, "write")
    dataset = db.scalar(
        select(EvaluationDataset)
        .where(
            EvaluationDataset.id == dataset_id,
            EvaluationDataset.organization_id == organization_id,
            EvaluationDataset.project_id == project_id,
            EvaluationDataset.created_by == user.id,
        )
        .with_for_update()
    )
    if not dataset:
        deny(db, user, "evaluation.reviewer_revoke", dataset_id, organization_id)
    old = dataset.reviewer_id
    dataset.reviewer_id = None
    audit(
        db,
        user.id,
        organization_id,
        "evaluation.reviewer_revoked",
        dataset.id,
        details={"previous_reviewer": str(old) if old else None},
    )
    db.commit()
    return dataset_meta(dataset)


@router.post(BASE + "/{dataset_id}/runs", status_code=202)
def start_run(
    organization_id: UUID,
    project_id: UUID,
    dataset_id: UUID,
    payload: RunInput,
    user: CurrentUser,
    db: Db,
):
    dataset = guarded(
        dataset_access, db, user, organization_id, project_id, dataset_id, write=True, lock=True
    )
    existing = db.scalar(
        select(EvaluationRun).where(
            EvaluationRun.requested_by == user.id,
            EvaluationRun.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        if existing.dataset_id != dataset.id:
            raise HTTPException(409)
        return run_meta(existing)
    pending = db.scalar(
        select(func.count())
        .select_from(EvaluationRun)
        .where(
            EvaluationRun.dataset_id == dataset.id, EvaluationRun.status.in_(["queued", "running"])
        )
    )
    if pending >= 3:
        raise HTTPException(
            409,
            detail={
                "code": "EVALUATION_QUEUE_LIMIT",
                "message": "该评测集已有待处理运行，请等待完成。",
            },
        )
    run = EvaluationRun(
        dataset_id=dataset.id, requested_by=user.id, idempotency_key=payload.idempotency_key
    )
    db.add(run)
    db.flush()
    audit(
        db,
        user.id,
        organization_id,
        "evaluation.started",
        run.id,
        details={"dataset_id": str(dataset.id), "version": dataset.version},
    )
    db.commit()
    return run_meta(run)


@router.get(BASE + "/runs/{run_id}")
def get_run(organization_id: UUID, project_id: UUID, run_id: UUID, user: CurrentUser, db: Db):
    run, dataset = guarded(run_access, db, user, organization_id, project_id, run_id)
    feedback = db.scalars(
        select(EvaluationFeedback)
        .where(EvaluationFeedback.run_id == run.id)
        .order_by(EvaluationFeedback.created_at, EvaluationFeedback.id)
    ).all()
    audit(db, user.id, organization_id, "evaluation.run_read", run.id)
    db.commit()
    return {
        **run_meta(run),
        "data_kind": dataset.data_kind,
        "dataset_hash": dataset.content_hash,
        "records": run.records,
        "evidence": resolve(
            db,
            user,
            organization_id,
            project_id,
            merge_refs(dataset.evidence_refs, run.evidence_refs),
        ),
        "summary": summary(run.records, feedback, dataset.data_kind),
        "feedback": [
            {
                key: getattr(f, key)
                for key in [
                    "id",
                    "case_id",
                    "created_by",
                    "independent",
                    "usable",
                    "numeric_correct",
                    "claim_judgments",
                    "category",
                    "severity",
                    "notes",
                    "created_at",
                ]
            }
            for f in feedback
        ],
    }


@router.get(BASE + "/runs/{run_id}/export")
def export_run(organization_id: UUID, project_id: UUID, run_id: UUID, user: CurrentUser, db: Db):
    payload = get_run(organization_id, project_id, run_id, user, db)
    run, dataset = guarded(run_access, db, user, organization_id, project_id, run_id)
    payload["dataset"] = {
        "name": dataset.name,
        "version": dataset.version,
        "definition": dataset.definition,
        "content_hash": dataset.content_hash,
    }
    audit(db, user.id, organization_id, "evaluation.exported", run.id)
    db.commit()
    return Response(
        json.dumps(jsonable_encoder(payload), ensure_ascii=False, sort_keys=True).encode(),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="evaluation-{run.id}.json"',
            "Cache-Control": "no-store",
        },
    )


@router.post(BASE + "/runs/{run_id}/retry", status_code=202)
def retry_run(organization_id: UUID, project_id: UUID, run_id: UUID, user: CurrentUser, db: Db):
    run, dataset = guarded(run_access, db, user, organization_id, project_id, run_id, write=True)
    run = db.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.id == run.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run.status != "failed" or run.attempts >= 3:
        raise HTTPException(409)
    run.status, run.error_code, run.claim_token, run.lease_until, run.finished_at = (
        "queued",
        None,
        None,
        None,
        None,
    )
    audit(db, user.id, organization_id, "evaluation.retried", run.id)
    db.commit()
    return run_meta(run)


@router.post(BASE + "/runs/{run_id}/cancel", status_code=202)
def cancel_run(organization_id: UUID, project_id: UUID, run_id: UUID, user: CurrentUser, db: Db):
    run, dataset = guarded(run_access, db, user, organization_id, project_id, run_id, write=True)
    run = db.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.id == run.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run.status not in {"queued", "running"}:
        raise HTTPException(409)
    run.status, run.claim_token, run.lease_until, run.finished_at = "cancelled", None, None, now()
    audit(db, user.id, organization_id, "evaluation.cancelled", run.id)
    db.commit()
    return run_meta(run)


@router.post(BASE + "/runs/{run_id}/feedback", status_code=201)
def add_feedback(
    organization_id: UUID,
    project_id: UUID,
    run_id: UUID,
    payload: FeedbackInput,
    user: CurrentUser,
    db: Db,
):
    run, dataset = guarded(run_access, db, user, organization_id, project_id, run_id, write=True)
    if run.status != "completed" or run.result_hash != payload.result_hash:
        raise HTTPException(409)
    record = next((r for r in run.records if r["case_id"] == payload.case_id), None)
    if not record or record["status"] != "measured":
        raise HTTPException(422)
    observed = record.get("observed_claims", [])
    if any(r.index >= len(observed) for r in payload.claim_judgments):
        raise HTTPException(422)
    independent = (
        user.id == dataset.reviewer_id
        and user.id != dataset.created_by
        and str(user.id) != record.get("source_author_id")
    )
    row = EvaluationFeedback(
        run_id=run.id,
        case_id=payload.case_id,
        created_by=user.id,
        result_hash=payload.result_hash,
        independent=independent,
        usable=payload.usable,
        numeric_correct=payload.numeric_correct,
        claim_judgments=[j.model_dump() for j in payload.claim_judgments],
        category=payload.category,
        severity=payload.severity,
        notes=payload.notes,
    )
    db.add(row)
    db.flush()
    audit(
        db,
        user.id,
        organization_id,
        "evaluation.feedback",
        run.id,
        details={
            "case_id": payload.case_id,
            "category": payload.category,
            "independent": independent,
        },
    )
    db.commit()
    return {"id": row.id, "independent": independent}
