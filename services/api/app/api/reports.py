import hashlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select

from app.agents.gateway import ModelError
from app.core.config import get_settings
from app.models.identity import User, now
from app.models.reports import KeyMetric, Report, ReportExport, ReportReview
from app.reports.quality import fingerprint, metric_output, metric_problem, metrics, quality
from app.reports.render import render
from app.reports.service import (
    access,
    assert_reviewer,
    change,
    check_revision,
    create,
    get_metric,
    record_review,
    unavailable,
)
from app.reports.sources import resolve
from app.reports.templates import LABELS, TEMPLATES
from app.schemas.reports import (
    AssignReviewer,
    CreateReport,
    ExportInput,
    MetricInput,
    MetricReview,
    ReviewInput,
    RevisionInput,
    UpdateReport,
)
from app.security.dependencies import CurrentUser, Db, deny, project_access
from app.services.audit import audit

router = APIRouter(prefix="/api/v1", tags=["reports"])
BASE = "/organizations/{organization_id}/projects/{project_id}/reports"


def meta(report, user):
    return {
        **{
            key: getattr(report, key)
            for key in [
                "id",
                "organization_id",
                "project_id",
                "template_version",
                "revision",
                "status",
                "created_by",
                "reviewer_id",
                "created_at",
                "updated_at",
            ]
        },
        "can_edit": report.created_by == user.id,
        "can_review": report.reviewer_id == user.id and report.created_by != user.id,
    }


def detail(db, user, report):
    try:
        q = quality(db, user, report)
    except ModelError as error:
        raise unavailable(error) from None
    return {
        **meta(report, user),
        "title": report.title,
        "content": report.content,
        "provenance": report.provenance,
        "quality": q,
        "metrics": [metric_output(m) for m in metrics(db, report)],
        "reviews": [
            {
                key: getattr(row, key)
                for key in [
                    "id",
                    "revision",
                    "reviewer_id",
                    "decision",
                    "content_hash",
                    "notes",
                    "confirmations",
                    "created_at",
                ]
            }
            for row in db.scalars(
                select(ReportReview)
                .where(ReportReview.report_id == report.id)
                .order_by(ReportReview.created_at, ReportReview.id)
            )
        ],
        "exports": [
            {
                key: getattr(row, key)
                for key in [
                    "id",
                    "revision",
                    "mode",
                    "format",
                    "content_hash",
                    "file_hash",
                    "requested_by",
                    "created_at",
                ]
            }
            for row in db.scalars(
                select(ReportExport)
                .where(ReportExport.report_id == report.id)
                .order_by(ReportExport.created_at.desc())
                .limit(100)
            )
        ],
    }


def require_gate(result):
    if not result["passed"]:
        raise HTTPException(
            409,
            detail={
                "code": "REPORT_QUALITY_BLOCKED",
                "message": "质量闸未通过：请核对未核验数字、引用与来源冲突。",
            },
        )


@router.get("/reports/templates")
def templates(user: CurrentUser):
    return {
        "templates": [
            {
                "id": key,
                "version": key + "@1.0.0",
                "sections": [{"key": s, "title": LABELS.get(s, s)} for s in values],
            }
            for key, values in TEMPLATES.items()
        ],
        "allow_draft_export": get_settings().report_allow_draft_export,
        "policy_version": "strict@1.0.0",
    }


@router.post(BASE, status_code=201)
def create_report(
    organization_id: UUID, project_id: UUID, payload: CreateReport, user: CurrentUser, db: Db
):
    return detail(db, user, create(db, user, organization_id, project_id, payload))


@router.get(BASE)
def list_reports(
    organization_id: UUID,
    project_id: UUID,
    user: CurrentUser,
    db: Db,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    project_access(db, user, organization_id, project_id)
    return [
        meta(row, user)
        for row in db.scalars(
            select(Report)
            .where(
                Report.organization_id == organization_id,
                Report.project_id == project_id,
                (Report.created_by == user.id) | (Report.reviewer_id == user.id),
            )
            .order_by(Report.updated_at.desc(), Report.id)
            .offset(offset)
            .limit(limit)
        )
    ]


@router.get(BASE + "/{report_id}")
def get_report(organization_id: UUID, project_id: UUID, report_id: UUID, user: CurrentUser, db: Db):
    report = access(db, user, organization_id, project_id, report_id)
    output = detail(db, user, report)
    audit(db, user.id, organization_id, "report.read", report.id)
    db.commit()
    return output


@router.get(BASE + "/{report_id}/reviews/{review_id}")
def get_review_snapshot(
    organization_id: UUID,
    project_id: UUID,
    report_id: UUID,
    review_id: UUID,
    user: CurrentUser,
    db: Db,
):
    report = access(db, user, organization_id, project_id, report_id)
    row = db.scalar(
        select(ReportReview).where(
            ReportReview.id == review_id, ReportReview.report_id == report.id
        )
    )
    if not row:
        raise HTTPException(404)
    if not row.snapshot:
        raise HTTPException(409)
    resolve(db, user, organization_id, project_id, row.snapshot.get("evidence_refs", []))
    audit(
        db,
        user.id,
        organization_id,
        "report.review_snapshot_read",
        report.id,
        details={"review_id": str(row.id)},
    )
    db.commit()
    return {
        "id": row.id,
        "content_hash": row.content_hash,
        "decision": row.decision,
        "notes": row.notes,
        "snapshot": row.snapshot,
    }


@router.put(BASE + "/{report_id}")
def update_report(
    organization_id: UUID,
    project_id: UUID,
    report_id: UUID,
    payload: UpdateReport,
    user: CurrentUser,
    db: Db,
):
    report = access(
        db, user, organization_id, project_id, report_id, owner=True, write=True, lock=True
    )
    check_revision(report, payload.expected_revision)
    kind = report.template_version.split("@")[0]
    if payload.content.workflow != kind or sorted(
        s.key for s in payload.content.sections
    ) != sorted(TEMPLATES[kind]):
        raise HTTPException(422)
    report.title, report.content = payload.title, payload.content.model_dump(mode="json")
    change(report)
    audit(
        db,
        user.id,
        organization_id,
        "report.updated",
        report.id,
        details={"revision": report.revision},
    )
    db.commit()
    return detail(db, user, report)


@router.put(BASE + "/{report_id}/reviewer")
def assign_reviewer(
    organization_id: UUID,
    project_id: UUID,
    report_id: UUID,
    payload: AssignReviewer,
    user: CurrentUser,
    db: Db,
):
    report = access(
        db, user, organization_id, project_id, report_id, owner=True, write=True, lock=True
    )
    check_revision(report, payload.expected_revision)
    old = report.reviewer_id
    candidate = SimpleNamespace(
        created_by=report.created_by,
        reviewer_id=payload.reviewer_id,
        organization_id=organization_id,
        project_id=project_id,
        evidence_refs=report.evidence_refs,
    )
    assert_reviewer(db, candidate)
    report.reviewer_id = payload.reviewer_id
    for item in metrics(db, report):
        item.verification_status, item.reviewer_id, item.reviewed_at, item.review_notes = (
            "unverified",
            None,
            None,
            "",
        )
    change(report)
    audit(
        db,
        user.id,
        organization_id,
        "report.reviewer",
        report.id,
        details={
            "before": str(old) if old else None,
            "after": str(report.reviewer_id),
            "revision": report.revision,
        },
    )
    db.commit()
    return detail(db, user, report)


@router.post(BASE + "/{report_id}/metrics", status_code=201)
def add_metric(
    organization_id: UUID,
    project_id: UUID,
    report_id: UUID,
    payload: MetricInput,
    user: CurrentUser,
    db: Db,
):
    report = access(
        db, user, organization_id, project_id, report_id, owner=True, write=True, lock=True
    )
    check_revision(report, payload.expected_revision)
    if len(metrics(db, report)) >= 100:
        raise HTTPException(409)
    values = payload.model_dump(exclude={"expected_revision"})
    if payload.evidence_id and payload.evidence_id not in {
        ref["id"] for ref in report.evidence_refs
    }:
        raise HTTPException(422)
    db.add(
        KeyMetric(
            report_id=report.id, organization_id=organization_id, project_id=project_id, **values
        )
    )
    change(report)
    audit(
        db,
        user.id,
        organization_id,
        "report.metric_added",
        report.id,
        details={"revision": report.revision},
    )
    db.commit()
    return detail(db, user, report)


@router.put(BASE + "/{report_id}/metrics/{metric_id}")
def update_metric(
    organization_id: UUID,
    project_id: UUID,
    report_id: UUID,
    metric_id: UUID,
    payload: MetricInput,
    user: CurrentUser,
    db: Db,
):
    report = access(
        db, user, organization_id, project_id, report_id, owner=True, write=True, lock=True
    )
    check_revision(report, payload.expected_revision)
    item = get_metric(db, report, metric_id)
    if payload.evidence_id and payload.evidence_id not in {
        ref["id"] for ref in report.evidence_refs
    }:
        raise HTTPException(422)
    for key, value in payload.model_dump(exclude={"expected_revision"}).items():
        setattr(item, key, value)
    item.verification_status, item.reviewer_id, item.reviewed_at, item.review_notes = (
        "unverified",
        None,
        None,
        "",
    )
    item.updated_at = now()
    change(report)
    audit(
        db,
        user.id,
        organization_id,
        "report.metric_updated",
        report.id,
        details={"metric_id": str(item.id), "revision": report.revision},
    )
    db.commit()
    return detail(db, user, report)


@router.delete(BASE + "/{report_id}/metrics/{metric_id}")
def delete_metric(
    organization_id: UUID,
    project_id: UUID,
    report_id: UUID,
    metric_id: UUID,
    payload: RevisionInput,
    user: CurrentUser,
    db: Db,
):
    report = access(
        db, user, organization_id, project_id, report_id, owner=True, write=True, lock=True
    )
    check_revision(report, payload.expected_revision)
    db.delete(get_metric(db, report, metric_id))
    change(report)
    audit(
        db,
        user.id,
        organization_id,
        "report.metric_deleted",
        report.id,
        details={"metric_id": str(metric_id), "revision": report.revision},
    )
    db.commit()
    return detail(db, user, report)


@router.post(BASE + "/{report_id}/submit")
def submit_report(
    organization_id: UUID,
    project_id: UUID,
    report_id: UUID,
    payload: RevisionInput,
    user: CurrentUser,
    db: Db,
):
    report = access(
        db, user, organization_id, project_id, report_id, owner=True, write=True, lock=True
    )
    check_revision(report, payload.expected_revision)
    if report.status != "draft":
        raise HTTPException(409)
    assert_reviewer(db, report)
    change(report, status="review_required")
    record_review(db, report, user, "submit", "作者提交当前修订进行独立审核。")
    audit(
        db,
        user.id,
        organization_id,
        "report.submitted",
        report.id,
        details={"revision": report.revision},
    )
    db.commit()
    return detail(db, user, report)


@router.post(BASE + "/{report_id}/metrics/{metric_id}/review")
def review_metric(
    organization_id: UUID,
    project_id: UUID,
    report_id: UUID,
    metric_id: UUID,
    payload: MetricReview,
    user: CurrentUser,
    db: Db,
):
    report = access(
        db, user, organization_id, project_id, report_id, reviewer=True, write=True, lock=True
    )
    check_revision(report, payload.expected_revision)
    assert_reviewer(db, report)
    if report.status != "review_required":
        raise HTTPException(409)
    item = get_metric(db, report, metric_id)
    if payload.status == "not_applicable" and item.metric_value is not None:
        raise HTTPException(422)
    if payload.status == "verified":
        source = resolve(db, user, organization_id, project_id, report.evidence_refs)
        if item.metric_value is None or metric_problem(item, {e["id"]: e for e in source}):
            raise HTTPException(
                409,
                detail={
                    "code": "METRIC_SOURCE_MISMATCH",
                    "message": "数值、单位、币种、期间或精确原文未匹配，不能标为已核验。",
                },
            )
    item.verification_status, item.reviewer_id, item.reviewed_at, item.review_notes = (
        payload.status,
        user.id,
        now(),
        payload.notes,
    )
    change(report, status="review_required")
    record_review(
        db, report, user, "metric_" + payload.status, payload.notes, {"metric_id": str(item.id)}
    )
    audit(
        db,
        user.id,
        organization_id,
        "report.metric_reviewed",
        report.id,
        details={"metric_id": str(item.id), "status": payload.status, "revision": report.revision},
    )
    db.commit()
    return detail(db, user, report)


@router.post(BASE + "/{report_id}/review")
def review_report(
    organization_id: UUID,
    project_id: UUID,
    report_id: UUID,
    payload: ReviewInput,
    user: CurrentUser,
    db: Db,
):
    report = access(
        db, user, organization_id, project_id, report_id, reviewer=True, write=True, lock=True
    )
    check_revision(report, payload.expected_revision)
    assert_reviewer(db, report)
    if report.status != "review_required":
        raise HTTPException(409)
    if payload.decision == "approve":
        require_gate(quality(db, user, report))
        report.approved_revision, report.approved_hash = report.revision, fingerprint(db, report)
        report.status = "approved_for_export"
        report.updated_at = now()
    else:
        change(report)
    record_review(
        db,
        report,
        user,
        payload.decision,
        payload.notes,
        payload.model_dump(exclude={"expected_revision", "notes", "decision"}),
    )
    audit(
        db,
        user.id,
        organization_id,
        "report.reviewed",
        report.id,
        details={"decision": payload.decision, "revision": report.revision},
    )
    db.commit()
    return detail(db, user, report)


@router.post(BASE + "/{report_id}/export")
def export_report(
    organization_id: UUID,
    project_id: UUID,
    report_id: UUID,
    payload: ExportInput,
    user: CurrentUser,
    db: Db,
):
    report = access(db, user, organization_id, project_id, report_id, write=True, lock=True)
    check_revision(report, payload.expected_revision)
    result = quality(db, user, report)
    if payload.mode == "draft" and not get_settings().report_allow_draft_export:
        raise HTTPException(403)
    content_hash = fingerprint(db, report)
    if payload.mode == "formal":
        assert_reviewer(db, report)
        require_gate(result)
        if (
            report.status not in {"approved_for_export", "exported"}
            or report.approved_revision != report.revision
            or report.approved_hash != content_hash
        ):
            raise HTTPException(
                409,
                detail={
                    "code": "REPORT_NOT_APPROVED",
                    "message": "当前修订尚未获得有效独立审核批准，不能正式导出。",
                },
            )
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    digest = hashlib.sha256(
        json.dumps(
            {
                "report": str(report.id),
                "request": payload.model_dump(mode="json"),
                "hash": content_hash,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    existing = db.scalar(
        select(ReportExport).where(
            ReportExport.requested_by == user.id,
            ReportExport.idempotency_key == payload.idempotency_key,
        )
    )
    if existing and existing.input_digest != digest:
        raise HTTPException(409)
    raw = render(
        report,
        metrics(db, report),
        result["evidence"],
        str(report.reviewer_id) if report.reviewer_id else None,
        payload.mode,
        payload.format,
    )
    file_hash = hashlib.sha256(raw).hexdigest()
    if existing and existing.file_hash != file_hash:
        raise HTTPException(409)
    # Expire cached authority/source rows: revocation during rendering must be visible.
    db.expire_all()
    if not user.is_active:
        deny(db, user, "report.export", report.id, organization_id, status=401)
    project_access(db, user, organization_id, project_id, "write")
    try:
        resolve(db, user, organization_id, project_id, report.evidence_refs)
    except ModelError as error:
        raise unavailable(error) from None
    if payload.mode == "formal":
        assert_reviewer(db, report)
    if not existing:
        existing = ReportExport(
            id=uuid4(),
            report_id=report.id,
            organization_id=organization_id,
            project_id=project_id,
            requested_by=user.id,
            idempotency_key=payload.idempotency_key,
            input_digest=digest,
            revision=report.revision,
            mode=payload.mode,
            format=payload.format,
            content_hash=content_hash,
            file_hash=file_hash,
        )
        db.add(existing)
    if payload.mode == "formal":
        report.status = "exported"
    audit(
        db,
        user.id,
        organization_id,
        "report.exported",
        report.id,
        details={
            "mode": payload.mode,
            "format": payload.format,
            "revision": report.revision,
            "file_hash": file_hash,
        },
    )
    db.commit()
    filename = f"peclaw-{payload.mode}-{report.id}-r{report.revision}.{payload.format}"
    return Response(
        raw,
        media_type="text/markdown; charset=utf-8"
        if payload.format == "md"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Export-ID": str(existing.id),
            "X-Content-SHA256": file_hash,
        },
    )
