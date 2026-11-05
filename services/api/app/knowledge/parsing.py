"""Local deterministic parsers: files and their embedded instructions are data, never code."""

import io
import re
from dataclasses import dataclass
from hashlib import sha256
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.table import Table
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

MAX_TEXT = 2_000_000
MAX_UNITS = 5000


class ParseFailure(ValueError):
    pass


@dataclass(frozen=True)
class TextUnit:
    text: str
    page: int | None
    section: str | None
    locator: dict


def validate_file(content: bytes, kind: str) -> None:
    if kind == "pdf":
        if not content.startswith(b"%PDF-"):
            raise ParseFailure("INVALID_PDF")
    elif kind in {"docx", "xlsx", "pptx"}:
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                expected = {
                    "docx": "word/document.xml",
                    "xlsx": "xl/workbook.xml",
                    "pptx": "ppt/presentation.xml",
                }[kind]
                if expected not in archive.namelist():
                    raise ParseFailure("FILE_TYPE_MISMATCH")
                if (
                    len(entries) > 3000
                    or sum(e.file_size for e in entries) > 50 * 1024 * 1024
                    or any(e.file_size > max(1, e.compress_size) * 200 for e in entries)
                    or any("vbaproject" in e.filename.lower() for e in entries)
                ):
                    raise ParseFailure("UNSAFE_OFFICE_FILE")
                for entry in entries:
                    if entry.filename.lower().endswith((".xml", ".rels")):
                        xml = archive.read(entry).upper()
                        if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                            raise ParseFailure("UNSAFE_XML")
        except BadZipFile:
            raise ParseFailure("INVALID_OFFICE_FILE") from None
    elif kind in {"txt", "md"}:
        if content.startswith((b"PK\x03\x04", b"%PDF-", b"MZ", b"\x7fELF")):
            raise ParseFailure("FILE_TYPE_MISMATCH")
        text = decode_text(content)
        if "\x00" in text:
            raise ParseFailure("INVALID_TEXT")
    else:
        raise ParseFailure("UNSUPPORTED_FORMAT")


def decode_text(content: bytes) -> str:
    try:
        return content.decode(
            "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        )
    except UnicodeError:
        raise ParseFailure("TEXT_ENCODING_UNSUPPORTED") from None


def parse(content: bytes, kind: str) -> list[TextUnit]:
    validate_file(content, kind)
    units: list[TextUnit] = []
    length = 0

    def add(text: str, page: int | None, section: str | None, locator: dict):
        nonlocal length
        text = text.strip()
        if not text:
            return
        if "\x00" in text:
            raise ParseFailure("INVALID_TEXT")
        length += len(text)
        if length > MAX_TEXT or len(units) >= MAX_UNITS:
            raise ParseFailure("EXTRACTED_TEXT_LIMIT")
        units.append(TextUnit(text, page, section[:200] if section else None, locator))

    try:
        if kind == "pdf":
            reader = PdfReader(io.BytesIO(content), strict=False)
            if reader.is_encrypted:
                raise ParseFailure("ENCRYPTED_PDF")
            if len(reader.pages) > 300:
                raise ParseFailure("PAGE_LIMIT")
            for number, page in enumerate(reader.pages, 1):
                add(
                    page.extract_text() or "",
                    number,
                    f"第 {number} 页",
                    {"type": "pdf", "page": number},
                )
        elif kind in {"txt", "md"}:
            section = None
            lines = decode_text(content).splitlines()
            paragraph: list[str] = []
            start = 1
            for number, line in enumerate([*lines, ""], 1):
                heading = re.match(r"^#{1,6}\s+(.+)", line) if kind == "md" else None
                if not line.strip() or heading:
                    if paragraph:
                        add(
                            "\n".join(paragraph),
                            None,
                            section,
                            {"type": kind, "line_start": start, "line_end": number - 1},
                        )
                        paragraph = []
                    if heading:
                        section = heading.group(1).strip()
                if line.strip():
                    if not paragraph:
                        start = number
                    paragraph.append(line)
        elif kind == "docx":
            document = Document(io.BytesIO(content))
            paragraph_number, table_number, section = 0, 0, None
            for block in document.iter_inner_content():
                if isinstance(block, Table):
                    table_number += 1
                    if len(block.rows) * len(block.columns) > 20000:
                        raise ParseFailure("TABLE_LIMIT")
                    for row_number, row in enumerate(block.rows, 1):
                        add(
                            " | ".join(cell.text for cell in row.cells),
                            None,
                            section,
                            {"type": "docx", "table": table_number, "row": row_number},
                        )
                else:
                    paragraph_number += 1
                    if block.style and (
                        block.style.name.startswith("Heading")
                        or block.style.name.startswith("标题")
                    ):
                        section = block.text
                    add(block.text, None, section, {"type": "docx", "paragraph": paragraph_number})
        elif kind == "pptx":
            slides = Presentation(io.BytesIO(content)).slides
            if len(slides) > 300:
                raise ParseFailure("PAGE_LIMIT")
            for number, slide in enumerate(slides, 1):
                section = slide.shapes.title.text if slide.shapes.title else f"第 {number} 张幻灯片"
                for shape_number, shape in enumerate(slide.shapes, 1):
                    if shape.has_text_frame:
                        add(
                            shape.text,
                            number,
                            section,
                            {"type": "pptx", "slide": number, "shape": shape_number},
                        )
                    if shape.has_table:
                        for row_number, row in enumerate(shape.table.rows, 1):
                            add(
                                " | ".join(cell.text for cell in row.cells),
                                number,
                                section,
                                {
                                    "type": "pptx",
                                    "slide": number,
                                    "shape": shape_number,
                                    "row": row_number,
                                },
                            )
        elif kind == "xlsx":
            book = load_workbook(
                io.BytesIO(content), read_only=True, data_only=False, keep_links=False
            )
            try:
                total_cells = 0
                for sheet in book.worksheets:
                    if (sheet.max_row or 0) > 5000 or (sheet.max_column or 0) > 200:
                        raise ParseFailure("TABLE_LIMIT")
                    for row in sheet.iter_rows():
                        total_cells += len(row)
                        if total_cells > 250000:
                            raise ParseFailure("TABLE_LIMIT")
                        cells = [
                            f"{cell.coordinate}: "
                            + (
                                f"[公式未计算] {cell.value}"
                                if cell.data_type == "f"
                                else str(cell.value)
                            )
                            for cell in row
                            if cell.value is not None
                        ]
                        if cells:
                            add(
                                " | ".join(cells),
                                None,
                                sheet.title,
                                {"type": "xlsx", "sheet": sheet.title, "row": row[0].row},
                            )
            finally:
                book.close()
    except ParseFailure:
        raise
    except Exception:
        raise ParseFailure("PARSER_FAILED") from None
    if not units:
        raise ParseFailure("NO_TEXT_LAYER" if kind == "pdf" else "EMPTY_DOCUMENT")
    return units


def chunk_units(units: list[TextUnit]) -> list[dict]:
    chunks = []
    for unit_index, unit in enumerate(units):
        for start in range(0, len(unit.text), 900):
            end = min(start + 1000, len(unit.text))
            excerpt = unit.text[start:end]
            chunks.append(
                {
                    "text": excerpt,
                    "page_number": unit.page,
                    "section_name": unit.section,
                    "locator": {**unit.locator, "unit": unit_index},
                    "start_offset": start,
                    "end_offset": end,
                    "content_hash": sha256(excerpt.encode()).hexdigest(),
                    "chunk_index": len(chunks),
                }
            )
            if len(chunks) > 2500:
                raise ParseFailure("CHUNK_LIMIT")
            if end == len(unit.text):
                break
    return chunks
