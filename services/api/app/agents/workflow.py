"""Authorize, retrieve, reserve, call, validate and reauthorize each bounded workflow."""

import json
import time
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import gateway
from app.agents.evidence import collect, resolve
from app.agents.gateway import ModelError
from app.agents.prompts import prompt
from app.agents.validation import validate_result
from app.core.config import get_settings
from app.models.agents import ModelCall, TaskRun
from app.models.identity import Organization, User, now
from app.schemas.agents import TaskInput
from app.security.dependencies import project_access
from app.services.audit import audit

ACTIVE = {"retrieving", "calling", "validating"}


def actor(db, task):
    user = db.get(User, task.requested_by) if task.requested_by else None
    if not user or not user.is_active:
        raise ModelError("ACCESS_REVOKED")
    project_access(db, user, task.organization_id, task.project_id, "write")
    return user


def owned_claim(db, task_id, token):
    task = db.scalar(
        select(TaskRun)
        .where(TaskRun.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not task or task.claim_token != token or task.status not in ACTIVE:
        raise ModelError("TASK_CANCELLED")
    return task


def execute_task(engine) -> bool:
    with Session(engine) as db:
        # Final crash at the execution cap cannot leave a task permanently running.
        for stale in db.scalars(
            select(TaskRun)
            .where(TaskRun.status.in_(ACTIVE), TaskRun.lease_until < now(), TaskRun.attempts >= 3)
            .with_for_update(skip_locked=True)
            .limit(20)
        ):
            stale.status, stale.error_code, stale.finished_at = (
                "failed",
                "ATTEMPTS_EXHAUSTED",
                now(),
            )
        db.commit()
        task = db.scalar(
            select(TaskRun)
            .where(
                (TaskRun.status == "queued")
                | (TaskRun.status.in_(ACTIVE) & (TaskRun.lease_until < now())),
                TaskRun.attempts < 3,
            )
            .order_by(TaskRun.created_at, TaskRun.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not task:
            return False
        if task.status in ACTIVE:
            old_call = db.scalar(
                select(ModelCall).where(
                    ModelCall.task_id == task.id, ModelCall.attempt == task.attempts
                )
            )
            if old_call and old_call.status == "reserved":
                old_call.status, old_call.error_code = "interrupted", "WORKER_INTERRUPTED"
        token, task_id = uuid4(), task.id
        task.claim_token, task.status, task.attempts = token, "retrieving", task.attempts + 1
        task.error_code, task.result = None, None
        task.lease_until, task.updated_at = now() + timedelta(seconds=120), now()
        db.commit()
    call_id, completion = None, None
    started = time.monotonic()
    try:
        if not gateway.configuration()["configured"]:
            raise ModelError("MODEL_NOT_CONFIGURED")
        with Session(engine) as db:
            task = db.get(TaskRun, task_id)
            user = actor(db, task)
            version, checksum, system = prompt(task.kind)
            if version != task.prompt_version or checksum != task.prompt_hash:
                raise ModelError("PROMPT_VERSION_UNAVAILABLE")
            payload = TaskInput.model_validate(task.inputs)
            context, refs = collect(db, user, task.organization_id, task.project_id, payload)
            if refs != task.evidence_refs:
                raise ModelError("EVIDENCE_CHANGED")
            db.commit()
        settings = get_settings()
        # Conservatively charge one token per UTF-8 byte plus all requested output tokens.
        reservation = (
            len(json.dumps(gateway.messages(system, context), ensure_ascii=False).encode())
            + settings.model_max_output_tokens
        )
        if reservation > 100000:
            raise ModelError("CONTEXT_LIMIT")
        with Session(engine) as db:
            # Serialize each organization's budget+concurrency reservation.
            org_id = db.get(TaskRun, task_id).organization_id
            db.scalar(select(Organization).where(Organization.id == org_id).with_for_update())
            task = owned_claim(db, task_id, token)
            user = actor(db, task)
            resolve(db, user, task.organization_id, task.project_id, task.evidence_refs)
            day = now().replace(hour=0, minute=0, second=0, microsecond=0)
            used = db.scalar(
                select(func.coalesce(func.sum(ModelCall.reserved_tokens), 0)).where(
                    ModelCall.organization_id == org_id, ModelCall.created_at >= day
                )
            )
            if used + reservation > settings.model_org_daily_token_limit:
                raise ModelError("ORG_TOKEN_BUDGET")
            running = db.scalar(
                select(func.count())
                .select_from(ModelCall)
                .where(
                    ModelCall.organization_id == org_id,
                    ModelCall.status == "reserved",
                    ModelCall.created_at > now() - timedelta(seconds=300),
                    ModelCall.task_id != task_id,
                )
            )
            if running >= settings.model_org_concurrency:
                # No model invocation/attempt charged for waiting behind another call.
                task.status, task.claim_token, task.lease_until = "queued", None, None
                task.attempts -= 1
                db.commit()
                return False
            call = ModelCall(
                task_id=task.id,
                organization_id=org_id,
                attempt=task.attempts,
                provider=settings.model_provider,
                model=settings.model_name,
                reserved_tokens=reservation,
            )
            db.add(call)
            task.status, task.updated_at = "calling", now()
            task.lease_until = now() + timedelta(seconds=300)
            db.commit()
            call_id = call.id
        completion = gateway.complete(system, context)
        result = validate_result(completion.content, context)
        with Session(engine) as db:
            task = owned_claim(db, task_id, token)
            task.status = "validating"
            user = actor(db, task)
            resolve(db, user, task.organization_id, task.project_id, task.evidence_refs)
            task.result, task.status = result, "review_required"
            task.finished_at, task.updated_at, task.lease_until = now(), now(), None
            audit(
                db,
                user.id,
                task.organization_id,
                "agent.review_required",
                task.id,
                details={
                    "kind": task.kind,
                    "attempt": task.attempts,
                    "prompt_version": task.prompt_version,
                },
            )
            db.commit()
    except Exception as error:
        code = (
            error.code
            if isinstance(error, ModelError)
            else ("ACCESS_REVOKED" if isinstance(error, HTTPException) else "WORKFLOW_FAILED")
        )
        with Session(engine) as db:
            task = db.scalar(select(TaskRun).where(TaskRun.id == task_id).with_for_update())
            if task and task.claim_token == token and task.status in ACTIVE:
                task.status, task.error_code, task.result = "failed", code, None
                task.finished_at, task.updated_at, task.lease_until = now(), now(), None
                audit(
                    db,
                    task.requested_by,
                    task.organization_id,
                    "agent.failed",
                    task.id,
                    result="failed",
                    details={"code": code, "attempt": task.attempts},
                )
                db.commit()
    finally:
        if call_id:
            with Session(engine) as db:
                call = db.get(ModelCall, call_id)
                task = db.get(TaskRun, task_id)
                call.status = (
                    "succeeded"
                    if task and task.claim_token == token and task.status == "review_required"
                    else "failed"
                )
                call.error_code = (
                    task.error_code if task and task.claim_token == token else "TASK_CANCELLED"
                )
                call.latency_ms = int((time.monotonic() - started) * 1000)
                if completion:
                    call.input_tokens, call.output_tokens = (
                        completion.input_tokens,
                        completion.output_tokens,
                    )
                    if completion.input_tokens is not None and completion.output_tokens is not None:
                        call.reserved_tokens = max(
                            call.reserved_tokens, completion.input_tokens + completion.output_tokens
                        )
                    cfg = get_settings()
                    if (
                        completion.input_tokens is not None
                        and completion.output_tokens is not None
                        and cfg.model_input_price_per_million is not None
                        and cfg.model_output_price_per_million is not None
                    ):
                        call.estimated_cost_micros = round(
                            completion.input_tokens * cfg.model_input_price_per_million
                            + completion.output_tokens * cfg.model_output_price_per_million
                        )
                db.commit()
    return True
