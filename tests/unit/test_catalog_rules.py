import base64
import io
from uuid import uuid4

import pytest
from openpyxl import Workbook
from pydantic import ValidationError

from app.catalog.imports import parse_file
from app.catalog.service import domain, literal_like, normalize
from app.schemas.catalog import CompanyCreate, EvidenceInput, ImportInput, SourceInput


def file_input(content, format="csv"):
    return ImportInput(
        source_id=uuid4(),
        reason="测试文件解析边界",
        format=format,
        content_base64=base64.b64encode(content).decode(),
        idempotency_key=uuid4(),
        public_confirmed=True,
    )


def test_unknown_not_inferred_and_alias_normalization():
    company = CompanyCreate(canonical_name="Example", source_id=uuid4(), reason="测试默认未知字段")
    assert company.country == company.listing_status == company.company_stage == "unknown"
    assert company.financing_stage == "unknown"
    assert normalize(" ＡＢＣ  公司 ") == "abc 公司"
    assert domain("https://www.example.com/company") == "example.com"
    assert literal_like("a%b_c") == "%a\\%b\\_c%"


def test_source_requires_explicit_public_permission_and_locator():
    body = dict(
        source_name="Source",
        source_type="official",
        license_type="authorized",
        permitted_use="authorized public platform redistribution",
    )
    with pytest.raises(ValidationError):
        SourceInput(**body, public_confirmed=False)
    with pytest.raises(ValidationError):
        SourceInput(**body, public_confirmed=True)
    with pytest.raises(ValidationError):
        SourceInput(
            **body,
            public_confirmed=True,
            source_url="https://secret:password@example.com",
        )


def test_blank_evidence_is_not_a_supported_fact():
    with pytest.raises(ValidationError):
        EvidenceInput(source_id=uuid4(), claim_text="   ", excerpt="   ")


@pytest.mark.parametrize(
    "content",
    [
        b"wrong_header\nhello\n",
        b"canonical_name,canonical_name\na,b\n",
        b"canonical_name\n\xff\n",
        b"canonical_name\n",
    ],
)
def test_malformed_csv_rejected(content):
    with pytest.raises(ValueError):
        parse_file(file_input(content))


def test_excel_formula_rejected_without_evaluation():
    book = Workbook()
    book.active.append(["canonical_name"])
    book.active.append(['=HYPERLINK("https://example.com")'])
    data = io.BytesIO()
    book.save(data)
    with pytest.raises(ValueError, match="FORMULAS_NOT_ALLOWED"):
        parse_file(file_input(data.getvalue(), "xlsx"))


def test_multiple_excel_sheets_not_silently_ignored():
    book = Workbook()
    book.active.append(["canonical_name"])
    book.active.append(["Example"])
    book.create_sheet("Second")
    data = io.BytesIO()
    book.save(data)
    with pytest.raises(ValueError, match="ONE_SHEET_REQUIRED"):
        parse_file(file_input(data.getvalue(), "xlsx"))


def test_row_limit_enforced():
    with pytest.raises(ValueError):
        parse_file(file_input(b"canonical_name\n" + b"example\n" * 201))
