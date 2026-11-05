import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.agents.evidence import collect, resolve
from app.agents.gateway import ModelError, configuration
from app.agents.prompts import SECTION_KEYS, prompt
from app.agents.workflow import ACTIVE
from app.models.agents import ModelCall, TaskRun
from app.models.identity import Organization, User, now
from app.schemas.agents import AgentResult, TaskInput, TaskRevision
from app.security.dependencies import CurrentUser, Db, deny, project_access
from app.services.audit import audit

router = APIRouter(prefix="/api/v1", tags=["agents"])


def model_failure(error):
    return HTTPException(
        409, detail={"code": error.code, "message": "任务证据已改变或不可用，请核对材料后新建任务"}
    )


@router.get("/agents/config")
def model_config(user: CurrentUser):
    return {
        **configuration(),
        "definitions": [
            {
                "kind": kind,
                "prompt_version": prompt(kind)[0],
                "prompt_hash": prompt(kind)[1],
                "section_keys": sections,
            }
            for kind, sections in SECTION_KEYS.items()
        ],
        "input_schema": TaskInput.model_json_schema(),
        "output_schema": AgentResult.model_json_schema(),
    }


def task_output(task):
    return {
        key: getattr(task, key)
        for key in [
            "id",
            "organization_id",
            "project_id",
            "kind",
            "prompt_version",
            "prompt_hash",
            "status",
            "attempts",
            "error_code",
            "created_at",
            "updated_at",
            "finished_at",
        ]
    }


def own_task(db, user, org_id, project_id, task_id, write=False, lock=False):
    project_access(db, user, org_id, project_id, "write" if write else "read")
    query = select(TaskRun).where(
        TaskRun.id == task_id,
        TaskRun.organization_id == org_id,
        TaskRun.project_id == project_id,
        TaskRun.requested_by == user.id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    task = db.scalar(query)
    if not task:
        deny(db, user, "agent.access", task_id, org_id)
    return task


BASE = "/organizations/{organization_id}/projects/{project_id}/agent-tasks"


@router.post(BASE, status_code=202)
def create_task(
    organization_id: UUID, project_id: UUID, payload: TaskInput, user: CurrentUser, db: Db
):
    project_access(db, user, organization_id, project_id, "write")
    db.scalar(select(Organization).where(Organization.id == organization_id).with_for_update())
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    inputs = payload.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(
            {"org": str(organization_id), "project": str(project_id), "inputs": inputs},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    existing = db.scalar(
        select(TaskRun).where(
            TaskRun.requested_by == user.id, TaskRun.idempotency_key == payload.idempotency_key
        )
    )
    if existing:
        if existing.input_digest != digest:
            raise HTTPException(409)
        return task_output(existing)
    pending = db.scalar(
        select(func.count())
        .select_from(TaskRun)
        .where(TaskRun.organization_id == organization_id, TaskRun.status.in_(["queued", *ACTIVE]))
    )
    if pending >= 100:
        raise HTTPException(
            429, detail={"code": "ORG_QUEUE_LIMIT", "message": "机构待处理任务已达到上限"}
        )
    try:
        _, refs = collect(db, user, organization_id, project_id, payload)
    except ModelError as error:
        raise model_failure(error) from None
    version, checksum, _ = prompt(payload.kind)
    task = TaskRun(
        organization_id=organization_id,
        project_id=project_id,
        requested_by=user.id,
        kind=payload.kind,
        inputs=inputs,
        input_digest=digest,
        idempotency_key=payload.idempotency_key,
        prompt_version=version,
        prompt_hash=checksum,
        evidence_refs=refs,
    )
    db.add(task)
    db.flush()
    audit(
        db,
        user.id,
        organization_id,
        "agent.created",
        task.id,
        details={"kind": task.kind, "prompt_version": version, "evidence_count": len(refs)},
    )
    db.commit()
    return task_output(task)


@router.get(BASE)
def list_tasks(
    organization_id: UUID,
    project_id: UUID,
    user: CurrentUser,
    db: Db,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    project_access(db, user, organization_id, project_id)
    return [
        task_output(task)
        for task in db.scalars(
            select(TaskRun)
            .where(
                TaskRun.organization_id == organization_id,
                TaskRun.project_id == project_id,
                TaskRun.requested_by == user.id,
            )
            .order_by(TaskRun.created_at.desc(), TaskRun.id)
            .offset(offset)
            .limit(limit)
        )
    ]


@router.get(BASE + "/{task_id}")
def get_task(organization_id: UUID, project_id: UUID, task_id: UUID, user: CurrentUser, db: Db):
    task = own_task(db, user, organization_id, project_id, task_id)
    try:
        evidence = resolve(db, user, organization_id, project_id, task.evidence_refs)
    except ModelError as error:
        raise model_failure(error) from None
    calls = [
        {
            key: getattr(call, key)
            for key in [
                "attempt",
                "provider",
                "model",
                "status",
                "reserved_tokens",
                "input_tokens",
                "output_tokens",
                "latency_ms",
                "estimated_cost_micros",
                "error_code",
                "created_at",
            ]
        }
        for call in db.scalars(
            select(ModelCall)
            .where(ModelCall.task_id == task.id, ModelCall.organization_id == organization_id)
            .order_by(ModelCall.attempt)
        )
    ]
    audit(db, user.id, organization_id, "agent.read", task.id)
    db.commit()
    return {
        **task_output(task),
        "inputs": task.inputs,
        "result": task.result,
        "evidence": evidence,
        "calls": calls,
        "review_notice": (
            "仅为待人工审核草案。引用校验不代表事实、数字或投资判断正确；"
            "尚未提供正式报告审核与导出。"
        ),
    }


@router.post(BASE + "/{task_id}/retry", status_code=202)
def retry_task(
    organization_id: UUID,
    project_id: UUID,
    task_id: UUID,
    payload: TaskRevision,
    user: CurrentUser,
    db: Db,
):
    task = own_task(db, user, organization_id, project_id, task_id, write=True, lock=True)
    if task.status != "failed" or task.attempts != payload.expected_attempts or task.attempts >= 3:
        raise HTTPException(409)
    try:
        resolve(db, user, organization_id, project_id, task.evidence_refs)
    except ModelError as error:
        raise model_failure(error) from None
    task.status, task.error_code, task.result = "queued", None, None
    task.claim_token, task.lease_until, task.finished_at, task.updated_at = None, None, None, now()
    audit(db, user.id, organization_id, "agent.retry", task.id, details={"attempt": task.attempts})
    db.commit()
    return task_output(task)


@router.post(BASE + "/{task_id}/cancel", status_code=202)
def cancel_task(
    organization_id: UUID,
    project_id: UUID,
    task_id: UUID,
    payload: TaskRevision,
    user: CurrentUser,
    db: Db,
):
    task = own_task(db, user, organization_id, project_id, task_id, write=True, lock=True)
    if task.status not in {"queued", *ACTIVE} or task.attempts != payload.expected_attempts:
        raise HTTPException(409)
    task.status, task.error_code, task.result = "cancelled", "TASK_CANCELLED", None
    task.claim_token, task.lease_until, task.finished_at, task.updated_at = None, None, now(), now()
    audit(db, user.id, organization_id, "agent.cancelled", task.id)
    db.commit()
    return task_output(task)
