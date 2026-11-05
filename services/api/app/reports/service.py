import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select

from app.agents.evidence import collect
from app.agents.gateway import ModelError
from app.knowledge.access import project_writer
from app.models.agents import TaskRun
from app.models.identity import User, now
from app.models.reports import KeyMetric, Report, ReportReview
from app.reports.quality import fingerprint, metric_output, metrics
from app.reports.sources import resolve
from app.reports.templates import body
from app.schemas.agents import TaskInput
from app.security.dependencies import deny, project_access
from app.services.audit import audit


def unavailable(error):
    return HTTPException(
        409,
        detail={
            "code": "REPORT_EVIDENCE_UNAVAILABLE",
            "message": "引用材料已变化或不可用，请核对来源后新建报告。",
        },
    )


def access(
    db, user, org_id, project_id, report_id, *, owner=False, reviewer=False, write=False, lock=False
):
    project_access(db, user, org_id, project_id, "write" if write else "read")
    query = select(Report).where(
        Report.id == report_id, Report.organization_id == org_id, Report.project_id == project_id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    report = db.scalar(query)
    allowed = report and user.id in {report.created_by, report.reviewer_id}
    if (
        not allowed
        or (owner and report.created_by != user.id)
        or (reviewer and (report.reviewer_id != user.id or report.created_by == user.id))
    ):
        deny(db, user, "report.access", report_id, org_id)
    try:
        resolve(db, user, org_id, project_id, report.evidence_refs)
    except ModelError as error:
        raise unavailable(error) from None
    return report


def assert_reviewer(db, report):
    user = db.get(User, report.reviewer_id) if report.reviewer_id else None
    if (
        not user
        or not user.is_active
        or user.id == report.created_by
        or not project_writer(db, user, report.organization_id, report.project_id)
    ):
        raise HTTPException(
            409,
            detail={
                "code": "REVIEWER_REQUIRED",
                "message": "需指定另一名当前具备项目编辑与原文读取资格的审核人。",
            },
        )
    try:
        resolve(db, user, report.organization_id, report.project_id, report.evidence_refs)
    except ModelError as error:
        raise unavailable(error) from None
    return user


def check_revision(report, expected):
    if report.revision != expected:
        raise HTTPException(409)


def change(report, *, status="draft"):
    report.revision += 1
    report.status, report.approved_hash, report.approved_revision, report.updated_at = (
        status,
        None,
        None,
        now(),
    )


def record_review(db, report, user, decision, notes, confirmations=None):
    db.flush()
    db.add(
        ReportReview(
            report_id=report.id,
            revision=report.revision,
            reviewer_id=user.id,
            decision=decision,
            content_hash=fingerprint(db, report),
            notes=notes,
            confirmations=confirmations or {},
            snapshot=json.loads(
                json.dumps(
                    {
                        "title": report.title,
                        "template_version": report.template_version,
                        "revision": report.revision,
                        "content": report.content,
                        "evidence_refs": report.evidence_refs,
                        "metrics": [metric_output(m) for m in metrics(db, report)],
                    },
                    default=str,
                )
            ),
        )
    )


def create(db, user, org_id, project_id, payload):
    project_access(db, user, org_id, project_id, "write")
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    digest = hashlib.sha256(
        json.dumps(
            {
                "org": str(org_id),
                "project": str(project_id),
                "input": payload.model_dump(mode="json"),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    existing = db.scalar(
        select(Report).where(
            Report.created_by == user.id, Report.idempotency_key == payload.idempotency_key
        )
    )
    if existing:
        if existing.input_digest != digest:
            raise HTTPException(409)
        return access(db, user, org_id, project_id, existing.id)
    source = None
    provenance = {"source": "manual_template"}
    if payload.source_task_id:
        task = db.scalar(
            select(TaskRun).where(
                TaskRun.id == payload.source_task_id,
                TaskRun.organization_id == org_id,
                TaskRun.project_id == project_id,
                TaskRun.requested_by == user.id,
            )
        )
        if not task or task.status != "review_required" or not task.result:
            raise HTTPException(
                409,
                detail={
                    "code": "TASK_NOT_READY",
                    "message": "只能从本人在当前项目中已完成的研究草案创建报告。",
                },
            )
        if task.kind != payload.template:
            raise HTTPException(422)
        refs = task.evidence_refs
        source = task.result
        provenance = {
            "source": "agent_draft",
            "task_id": str(task.id),
            "prompt_version": task.prompt_version,
            "prompt_hash": task.prompt_hash,
        }
        try:
            resolve(db, user, org_id, project_id, refs)
        except ModelError as error:
            raise unavailable(error) from None
    else:
        request = TaskInput(
            kind="due_diligence",
            idempotency_key=payload.idempotency_key,
            question="报告来源收集，不调用生成模型。",
            company_id=payload.company_id,
            document_ids=payload.document_ids,
            allow_private_to_model=bool(payload.document_ids),
        )
        try:
            _, refs = collect(db, user, org_id, project_id, request)
        except ModelError as error:
            raise unavailable(error) from None
    report = Report(
        organization_id=org_id,
        project_id=project_id,
        created_by=user.id,
        source_task_id=payload.source_task_id,
        idempotency_key=payload.idempotency_key,
        input_digest=digest,
        title=payload.title,
        template_version=payload.template + "@1.0.0",
        content=body(payload.template, source),
        evidence_refs=refs,
        provenance=provenance,
    )
    db.add(report)
    db.flush()
    audit(
        db,
        user.id,
        org_id,
        "report.created",
        report.id,
        details={"template": report.template_version, "source": provenance["source"]},
    )
    db.commit()
    return report


def get_metric(db, report, metric_id):
    item = db.scalar(
        select(KeyMetric).where(
            KeyMetric.id == metric_id,
            KeyMetric.report_id == report.id,
            KeyMetric.organization_id == report.organization_id,
            KeyMetric.project_id == report.project_id,
        )
    )
    if not item:
        raise HTTPException(404)
    return item
