from hashlib import sha256
from uuid import uuid4

import numpy as np
import pytest
from fixtures.private_documents import office_bytes
from pydantic import ValidationError

from app.knowledge.embedding import MODEL_ID, encode
from app.knowledge.parsing import ParseFailure, chunk_units, parse
from app.schemas.knowledge import DocumentInput


@pytest.mark.parametrize("kind", ["pdf", "docx", "xlsx", "pptx"])
def test_real_office_and_pdf_parsers_preserve_locations(kind):
    units = parse(office_bytes(kind), kind)
    assert units and all(unit.locator["type"] == kind for unit in units)
    chunks = chunk_units(units)
    assert chunks and all(
        chunk["text"] and sha256(chunk["text"].encode()).hexdigest() == chunk["content_hash"]
        for chunk in chunks
    )
    if kind in {"pdf", "pptx"}:
        assert any(unit.page == 1 for unit in units)
    if kind == "xlsx":
        assert any("公式未计算" in unit.text for unit in units)
        assert any(unit.locator.get("sheet") == "财务草稿" for unit in units)
    if kind == "docx":
        assert any("table" in unit.locator for unit in units)


def test_markdown_sections_and_exact_offsets():
    text = "# 盈利分析\n\n" + "企业利润与客户证据需要核验。" * 160
    units = parse(text.encode(), "md")
    chunks = chunk_units(units)
    assert len(chunks) > 1 and chunks[-1]["section_name"] == "盈利分析"
    for chunk in chunks:
        assert (
            units[chunk["locator"]["unit"]].text[chunk["start_offset"] : chunk["end_offset"]]
            == chunk["text"]
        )


def test_scan_only_pdf_reports_ocr_requirement():
    import io

    from pypdf import PdfWriter

    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(stream)
    with pytest.raises(ParseFailure, match="NO_TEXT_LAYER"):
        parse(stream.getvalue(), "pdf")


def test_real_pretrained_vectors_are_semantic_not_hashes():
    first, _ = encode("盈利")
    related, _ = encode("利润")
    unrelated, _ = encode("降雨天气")
    assert "300" in MODEL_ID and len(first) == 300
    assert np.isfinite(first).all() and abs(np.linalg.norm(first) - 1) < 0.001
    assert np.dot(first, related) > np.dot(first, unrelated)


@pytest.mark.parametrize(
    "filename",
    ["../secret.txt", "evil\\file.pdf", ".hidden.txt", "file.exe", "nul\x00.txt"],
)
def test_unsafe_upload_names_rejected(filename):
    with pytest.raises(ValidationError):
        DocumentInput(
            filename=filename,
            title="私有文件",
            content_base64="dGVzdA==",
            idempotency_key=uuid4(),
        )


def test_mislabelled_binary_and_xml_entities_rejected():
    import io
    from zipfile import ZipFile

    with pytest.raises(ParseFailure):
        parse(b"MZnottext", "txt")
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>',
        )
    with pytest.raises(ParseFailure, match="UNSAFE_XML"):
        parse(buffer.getvalue(), "docx")
