import base64
import csv
import hashlib
import io
import json
from datetime import timedelta
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException
from openpyxl import load_workbook
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog.service import create_company, normalize, source
from app.models.catalog import (
    CatalogImport,
    Company,
    CompanyAlias,
    CompanyChange,
    CompanyTechnology,
    Evidence,
    IndustryNode,
    Technology,
)
from app.models.identity import User, now
from app.schemas.catalog import CompanyCreate, EvidenceInput, ImportInput
from app.services.audit import audit

MAX_ROWS = 200
HEADERS = set(CompanyCreate.model_fields) - {
    "source_id",
    "reason",
    "industry_ids",
    "expected_version",
}
HEADERS |= {"industries", "technologies", "technology_excerpt"}


def parse_file(payload: ImportInput) -> list[dict]:
    content = base64.b64decode(payload.content_base64, validate=True)
    if payload.format == "csv":
        try:
            text = content.decode("utf-8-sig")
            table = list(csv.reader(io.StringIO(text)))
        except (UnicodeError, csv.Error):
            raise ValueError("INVALID_UTF8_CSV") from None
    else:
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > 2000
                    or sum(e.file_size for e in entries) > 20 * 1024 * 1024
                    or any(e.file_size > max(1, e.compress_size) * 200 for e in entries)
                    or any(
                        "vbaproject" in e.filename.lower() or "externallinks" in e.filename.lower()
                        for e in entries
                    )
                ):
                    raise ValueError("UNSAFE_XLSX")
            workbook = load_workbook(
                io.BytesIO(content), read_only=True, data_only=False, keep_links=False
            )
            try:
                if len(workbook.worksheets) != 1:
                    raise ValueError("ONE_SHEET_REQUIRED")
                sheet = workbook.worksheets[0]
                if (sheet.max_row and sheet.max_row > MAX_ROWS + 1) or (
                    sheet.max_column and sheet.max_column > 40
                ):
                    raise ValueError("TOO_MANY_ROWS")
                table = []
                for cells in sheet.iter_rows(max_row=MAX_ROWS + 2):
                    if any(c.data_type == "f" for c in cells):
                        raise ValueError("FORMULAS_NOT_ALLOWED")
                    table.append(["" if c.value is None else str(c.value) for c in cells])
            finally:
                workbook.close()
        except (BadZipFile, KeyError, OSError):
            raise ValueError("INVALID_XLSX") from None
    while table and not any(table[-1]):
        table.pop()
    if not table or len(table) > MAX_ROWS + 1:
        raise ValueError("EMPTY_OR_TOO_MANY_ROWS")
    columns = [str(column).strip() for column in table[0]]
    if (
        "canonical_name" not in columns
        or len(columns) != len(set(columns))
        or not set(columns) <= HEADERS
    ):
        raise ValueError("INVALID_HEADERS")
    rows = []
    for number, row in enumerate(table[1:], 2):
        if len(row) != len(columns):
            rows.append({"__invalid__": True, "__row_number__": number})
        elif any(row):
            rows.append(
                {
                    "__row_number__": number,
                    **{key: value.strip() for key, value in zip(columns, row)},
                }
            )
    if not rows:
        raise ValueError("NO_DATA_ROWS")
    return rows


def input_digest(payload: ImportInput) -> str:
    values = payload.model_dump(mode="json", exclude={"idempotency_key"})
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def import_output(job: CatalogImport) -> dict:
    return {
        key: getattr(job, key)
        for key in [
            "id",
            "source_id",
            "state",
            "attempts",
            "result",
            "error_code",
            "created_at",
            "started_at",
            "finished_at",
        ]
    }


def strong_candidates(db: Session, values: dict) -> list[Company]:
    names = {
        normalize(values["canonical_name"]),
        *[normalize(a) for a in values.get("aliases", [])],
    }
    matches = [
        Company.normalized_name.in_(names),
        Company.id.in_(
            select(CompanyAlias.company_id).where(CompanyAlias.normalized_name.in_(names))
        ),
    ]
    if values.get("registration_name"):
        matches.append(Company.registration_name == values["registration_name"])
    if values.get("unified_social_credit_code"):
        matches.append(Company.unified_social_credit_code == values["unified_social_credit_code"])
    from app.catalog.service import domain

    if values.get("website"):
        matches.append(Company.website_domain == domain(values["website"]))
    return db.scalars(select(Company).where(or_(*matches))).all()


def apply_row(
    db: Session, actor: User, job: CatalogImport, payload: ImportInput, row: dict, number: int
) -> dict:
    if "__invalid__" in row:
        raise ValueError("INVALID_COLUMNS")
    values = {key: value for key, value in row.items() if value != ""}
    values["aliases"] = [v.strip() for v in values.get("aliases", "").split("|") if v.strip()]
    industries = values.pop("industries", "").split("|")
    technologies = [v.strip() for v in values.pop("technologies", "").split("|") if v.strip()]
    excerpt = values.pop("technology_excerpt", "")
    if technologies and len(excerpt.strip()) < 3:
        raise ValueError("TECHNOLOGY_EXCERPT_REQUIRED")
    # Validate every company field before touching shared taxonomy or deduplication state.
    initial = CompanyCreate.model_validate(
        {**values, "source_id": job.source_id, "reason": payload.reason}
    )
    fingerprint = hashlib.sha256(
        (str(job.source_id) + json.dumps(row, sort_keys=True, ensure_ascii=False)).encode()
    ).hexdigest()
    previous = db.scalar(
        select(CompanyChange).where(CompanyChange.import_fingerprint == fingerprint)
    )
    if previous:
        return {"row": number, "status": "skipped", "company_id": str(previous.company_id)}
    matches = strong_candidates(db, initial.model_dump())
    if matches:
        return {
            "row": number,
            "status": "review_required",
            "candidate_ids": [str(c.merged_into_id or c.id) for c in matches],
        }
    node_ids = []
    for name in dict.fromkeys(v.strip() for v in industries if v.strip()):
        if len(name) > 100:
            raise ValueError("INVALID_INDUSTRY_NAME")
        node = db.scalar(select(IndustryNode).where(IndustryNode.name == name))
        if not node:
            node = IndustryNode(name=name)
            db.add(node)
            db.flush()
        node_ids.append(node.id)
    initial.industry_ids = node_ids
    record = create_company(db, actor, initial, fingerprint)
    for name in dict.fromkeys(technologies):
        if len(name) > 100:
            raise ValueError("INVALID_TECHNOLOGY_NAME")
        tech = db.scalar(select(Technology).where(Technology.name == name))
        if not tech:
            tech = Technology(name=name)
            db.add(tech)
            db.flush()
        quote = EvidenceInput(
            source_id=job.source_id,
            claim_text=f"导入档案标注技术关联：{name}",
            excerpt=excerpt,
            classification="unverified",
            verification_status="unverified",
            section_name=f"导入任务 {job.id} · 第 {number} 行",
        )
        evidence = Evidence(company_id=record.id, **quote.model_dump())
        db.add(evidence)
        db.flush()
        db.add(
            CompanyTechnology(
                company_id=record.id,
                technology_id=tech.id,
                evidence_id=evidence.id,
                relation_type="announced",
            )
        )
    return {"row": number, "status": "created", "company_id": str(record.id)}


def execute_import(engine) -> bool:
    # Durable DB queue: claim committed separately, then hold a job row lock for atomic output.
    # A crashed process rolls back all output; expired running jobs may be reclaimed.
    with Session(engine) as db:
        exhausted = db.scalars(
            select(CatalogImport)
            .where(
                CatalogImport.state == "running",
                CatalogImport.attempts >= 3,
                CatalogImport.started_at < now() - timedelta(seconds=120),
            )
            .with_for_update(skip_locked=True)
        ).all()
        for stale in exhausted:
            stale.state, stale.finished_at, stale.error_code = (
                "failed",
                now(),
                "MAX_ATTEMPTS_EXHAUSTED",
            )
            audit(
                db,
                stale.requested_by,
                None,
                "catalog.import.failed",
                stale.id,
                result="failed",
                details={"code": stale.error_code},
            )
        if exhausted:
            db.commit()
        job = db.scalar(
            select(CatalogImport)
            .where(
                or_(
                    CatalogImport.state == "queued",
                    (CatalogImport.state == "running")
                    & (CatalogImport.started_at < now() - timedelta(seconds=120)),
                ),
                CatalogImport.attempts < 3,
            )
            .order_by(CatalogImport.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return False
        job.state, job.started_at = "running", now()
        job.attempts += 1
        job_id = job.id
        db.commit()
    try:
        with Session(engine) as db:
            job = db.scalar(
                select(CatalogImport).where(CatalogImport.id == job_id).with_for_update()
            )
            actor = db.get(User, job.requested_by)
            if not actor or not actor.is_active or not actor.is_data_curator:
                raise ValueError("CURATOR_ACCESS_REVOKED")
            source(db, job.source_id)
            payload = ImportInput.model_validate(job.input_payload)
            rows = parse_file(payload)
            results = []
            for fallback_number, row in enumerate(rows, 2):
                number = row.pop("__row_number__", fallback_number)
                try:
                    with db.begin_nested():
                        result = apply_row(db, actor, job, payload, row, number)
                    results.append(result)
                except (ValidationError, ValueError, IntegrityError, HTTPException):
                    results.append({"row": number, "status": "error", "code": "INVALID_ROW"})
            # Successful import results and their provenance commit together.
            job.result = {
                "rows": results,
                "counts": {
                    state: sum(r["status"] == state for r in results)
                    for state in ["created", "skipped", "review_required", "error"]
                },
            }
            job.state, job.finished_at = "completed", now()
            audit(
                db, actor.id, None, "catalog.import.complete", job.id, details=job.result["counts"]
            )
            db.commit()
    except Exception as error:
        with Session(engine) as db:
            job = db.get(CatalogImport, job_id)
            job.state, job.finished_at = "failed", now()
            # Persist controlled codes, never raw files or parser/credential details.
            job.error_code = (
                "CURATOR_ACCESS_REVOKED"
                if str(error) == "CURATOR_ACCESS_REVOKED"
                else (
                    "INVALID_FILE"
                    if isinstance(error, (ValueError, ValidationError))
                    else "IMPORT_FAILED"
                )
            )
            audit(
                db,
                job.requested_by,
                None,
                "catalog.import.failed",
                job.id,
                result="failed",
                details={"code": job.error_code},
            )
            db.commit()
    return True
