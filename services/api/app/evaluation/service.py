import hashlib
import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.agents.evidence import company_excerpt, public_company
from app.agents.gateway import ModelError
from app.knowledge.access import document_access, project_writer
from app.models.agents import TaskRun
from app.models.evaluation import EvaluationDataset, EvaluationRun
from app.models.identity import User
from app.models.knowledge import DocumentChunk, DocumentVersion
from app.reports.quality import fingerprint
from app.reports.service import access as report_access
from app.reports.sources import resolve
from app.schemas.evaluation import DatasetInput, ReportCase, RetrievalCase, SearchCase, TaskCase
from app.security.dependencies import deny, project_access
from app.services.audit import audit


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def task_hash(task):
    return digest(
        {
            "result": task.result,
            "prompt_version": task.prompt_version,
            "prompt_hash": task.prompt_hash,
            "kind": task.kind,
        }
    )


def merge_refs(*groups):
    result = {}
    for refs in groups:
        for ref in refs:
            if ref["id"] in result and result[ref["id"]] != ref:
                raise ModelError("EVALUATION_SOURCE_CHANGED")
            result[ref["id"]] = ref
    return list(result.values())


def artifact_guard(db, user, dataset):
    resolve(db, user, dataset.organization_id, dataset.project_id, dataset.evidence_refs)
    for binding in dataset.bindings.values():
        if binding["kind"] == "task":
            task = db.scalar(
                select(TaskRun).where(
                    TaskRun.id == UUID(binding["id"]),
                    TaskRun.organization_id == dataset.organization_id,
                    TaskRun.project_id == dataset.project_id,
                )
            )
            if (
                not task
                or str(task.requested_by) != binding["author"]
                or task.status != "review_required"
                or task_hash(task) != binding["hash"]
            ):
                raise ModelError("EVALUATION_SOURCE_CHANGED")
        else:
            report = report_access(
                db, user, dataset.organization_id, dataset.project_id, UUID(binding["id"])
            )
            if report.revision != binding["revision"] or fingerprint(db, report) != binding["hash"]:
                raise ModelError("EVALUATION_SOURCE_CHANGED")


def dataset_access(db, user, org, project, dataset_id, write=False, lock=False):
    project_access(db, user, org, project, "write" if write else "read")
    query = select(EvaluationDataset).where(
        EvaluationDataset.id == dataset_id,
        EvaluationDataset.organization_id == org,
        EvaluationDataset.project_id == project,
    )
    if lock:
        query = query.with_for_update()
    dataset = db.scalar(query)
    if not dataset or user.id not in {dataset.created_by, dataset.reviewer_id}:
        deny(db, user, "evaluation.access", dataset_id, org)
    artifact_guard(db, user, dataset)
    return dataset


def create_dataset(db, user, org, project, payload: DatasetInput):
    project_access(db, user, org, project, "write")
    definition = payload.model_dump(mode="json", exclude={"idempotency_key"})
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    existing = db.scalar(
        select(EvaluationDataset).where(
            EvaluationDataset.created_by == user.id,
            EvaluationDataset.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        if (
            existing.organization_id != org
            or existing.project_id != project
            or existing.definition != definition
        ):
            raise HTTPException(409)
        artifact_guard(db, user, existing)
        return existing
    if db.scalar(
        select(EvaluationDataset.id).where(
            EvaluationDataset.created_by == user.id,
            EvaluationDataset.organization_id == org,
            EvaluationDataset.project_id == project,
            EvaluationDataset.name == payload.name,
            EvaluationDataset.version == payload.version,
        )
    ):
        raise HTTPException(
            409,
            detail={
                "code": "DATASET_VERSION_EXISTS",
                "message": "同名评测集版本已存在，请递增版本而非覆盖。",
            },
        )
    refs = []
    bindings = {}
    for case in payload.cases:
        if isinstance(case, SearchCase):
            for label in case.relevance:
                company = public_company(db, label.company_id)
                refs.append(
                    {
                        "id": "company:" + str(company.id),
                        "kind": "company",
                        "resource_id": str(company.id),
                        "hash": hashlib.sha256(company_excerpt(company).encode()).hexdigest(),
                    }
                )
        elif isinstance(case, RetrievalCase):
            for label in case.relevance:
                doc = document_access(db, user, org, project, label.document_id)
                version = db.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == doc.id,
                        DocumentVersion.number == doc.current_version,
                    )
                )
                if not version or version.status != "indexed":
                    raise ModelError("DOCUMENT_NOT_INDEXED")
                chunk = db.scalar(
                    select(DocumentChunk)
                    .where(DocumentChunk.version_id == version.id)
                    .order_by(DocumentChunk.chunk_index)
                    .limit(1)
                )
                if not chunk:
                    raise ModelError("DOCUMENT_NOT_INDEXED")
                refs.append(
                    {
                        "id": "chunk:" + str(chunk.id),
                        "kind": "private_chunk",
                        "resource_id": str(chunk.id),
                        "document_id": str(doc.id),
                        "version_id": str(version.id),
                        "hash": chunk.content_hash,
                    }
                )
        elif isinstance(case, TaskCase) and case.task_id:
            task = db.scalar(
                select(TaskRun).where(
                    TaskRun.id == case.task_id,
                    TaskRun.organization_id == org,
                    TaskRun.project_id == project,
                    TaskRun.requested_by == user.id,
                )
            )
            if not task or task.status != "review_required" or not task.result:
                raise ModelError("TASK_NOT_READY")
            if case.kind == "bp_screening" and task.kind != "bp_screening":
                raise ModelError("TASK_KIND_MISMATCH")
            resolve(db, user, org, project, task.evidence_refs)
            refs.extend(task.evidence_refs)
            bindings[case.id] = {
                "kind": "task",
                "id": str(task.id),
                "hash": task_hash(task),
                "author": str(task.requested_by),
            }
        elif isinstance(case, ReportCase):
            report = report_access(db, user, org, project, case.report_id)
            refs.extend(report.evidence_refs)
            bindings[case.id] = {
                "kind": "report",
                "id": str(report.id),
                "revision": report.revision,
                "hash": fingerprint(db, report),
                "author": str(report.created_by),
            }
    refs = merge_refs(refs)
    if len(refs) > 500:
        raise ModelError("EVALUATION_SOURCE_LIMIT")
    dataset = EvaluationDataset(
        organization_id=org,
        project_id=project,
        created_by=user.id,
        reviewer_id=payload.reviewer_id,
        name=payload.name,
        version=payload.version,
        data_kind=payload.data_kind,
        source_description=payload.source_description,
        idempotency_key=payload.idempotency_key,
        content_hash=digest(
            {"definition": definition, "bindings": bindings, "refs": merge_refs(refs)}
        ),
        definition=definition,
        evidence_refs=merge_refs(refs),
        bindings=bindings,
    )
    if payload.reviewer_id:
        reviewer = db.get(User, payload.reviewer_id)
        if (
            not reviewer
            or not reviewer.is_active
            or reviewer.id == user.id
            or not project_writer(db, reviewer, org, project)
        ):
            raise ModelError("EVALUATION_REVIEWER_INVALID")
        artifact_guard(db, reviewer, dataset)
    db.add(dataset)
    db.flush()
    audit(
        db,
        user.id,
        org,
        "evaluation.dataset_created",
        dataset.id,
        details={
            "version": dataset.version,
            "data_kind": dataset.data_kind,
            "case_count": len(payload.cases),
        },
    )
    db.commit()
    return dataset


def run_access(db, user, org, project, run_id, write=False):
    project_access(db, user, org, project, "write" if write else "read")
    run = db.scalar(
        select(EvaluationRun)
        .join(EvaluationDataset, EvaluationRun.dataset_id == EvaluationDataset.id)
        .where(
            EvaluationRun.id == run_id,
            EvaluationDataset.organization_id == org,
            EvaluationDataset.project_id == project,
            (EvaluationDataset.created_by == user.id) | (EvaluationDataset.reviewer_id == user.id),
        )
    )
    if not run:
        deny(db, user, "evaluation.run_access", run_id, org)
    dataset = dataset_access(db, user, org, project, run.dataset_id, write=write)
    resolve(db, user, org, project, run.evidence_refs)
    return run, dataset
