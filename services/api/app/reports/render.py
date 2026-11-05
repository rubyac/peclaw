"""Deterministic, in-memory Markdown and DOCX; no scripts, macros or external resources."""

import html
import io
import re
from datetime import datetime, timezone
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from docx import Document

from app.reports.quality import CLASS_NAMES
from app.reports.templates import LABELS


def paragraphs(report, items, evidence, reviewer_name, mode):
    yield (
        0,
        "内部草稿 · 未审核 · 不得作为正式报告"
        if mode == "draft"
        else "正式导出 · 已通过应用审核流程，仍需独立投资判断",
    )
    yield 1, report.title
    yield 0, f"报告编号：{report.id}；修订：{report.revision}；模板：{report.template_version}"
    yield 0, "审核人：" + (reviewer_name or "尚未审核")
    yield 0, "事实、推断、未知与待核验信息分开呈现；本报告不构成投资建议或收益保证。"

    def statement(value):
        refs = "；".join(value["evidence_ids"]) or "无引用"
        return f"【{CLASS_NAMES[value['classification']]}】{value['text']}\n引用：{refs}"

    yield 2, "摘要"
    yield 0, statement(report.content["summary"])
    for section in report.content["sections"]:
        yield 2, LABELS.get(section["key"], section["key"])
        for claim in section["claims"]:
            yield 0, statement(claim)
    yield 2, "关键数字登记"
    if not items:
        yield 0, "未登记关键数字。审核人需确认正文不存在未登记的关键数值。"
    for item in items:
        displayed_value = item.metric_value if item.metric_value is not None else "不适用／未提供"
        yield 3, item.metric_name
        yield (
            0,
            (
                f"数值：{displayed_value}；"
                f"单位：{item.unit}；币种：{item.currency or '不适用'}；期间：{item.period}"
            ),
        )
        yield 0, f"核验状态：{item.verification_status}；引用：{item.evidence_id or '无'}"
        yield 0, "原文：" + (item.source_quote or "不适用")
        yield 0, "登记备注：" + item.notes + "\n核验备注：" + item.review_notes
    yield 2, "尽调问题"
    for item in report.content["questions"]:
        yield 3, item["question"]
        for key, label in [
            ("priority", "优先级"),
            ("reason", "原因"),
            ("risk", "风险"),
            ("known_information", "已知信息"),
            ("missing_evidence", "缺失证据"),
            ("verification_method", "验证方式"),
        ]:
            yield 0, f"{label}：{item[key]}"
        yield 0, "引用：" + "；".join(item["evidence_ids"])
    for key, label in [("unknowns", "未知与缺口"), ("limitations", "局限性")]:
        yield 2, label
        for text in report.content[key]:
            yield 0, text
    yield 2, "授权来源与原文定位"
    for source in evidence:
        yield 3, source["id"]
        if source["kind"] == "private_chunk":
            yield (
                0,
                (
                    f"文档：{source['document_title']}；版本：{source['version_number']}；"
                    f"文件 SHA-256：{source['file_hash']}"
                ),
            )
            yield (
                0,
                (
                    f"页码：{source.get('page_number') or '不适用'}；"
                    f"章节：{source.get('section_name') or '未提供'}；定位：{source.get('locator')}"
                ),
            )
        else:
            yield 0, "公共企业档案：" + source["company_id"]
        yield (
            0,
            (
                source["excerpt"]
                if mode == "draft"
                else "仅保留授权来源定位；正式文件不自动附带未逐项核验的全文片段。"
            ),
        )


def safe_markdown(text):
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~\-])", r"\\\1", html.escape(text, quote=False))


def render(report, items, evidence, reviewer_name, mode, format):
    rows = list(paragraphs(report, items, evidence, reviewer_name, mode))
    if format == "md":
        return (
            "\n\n".join(
                ("#" * level + " " if level else "") + safe_markdown(text) for level, text in rows
            )
            + "\n"
        ).encode()
    document = Document()
    document.core_properties.title = report.title
    document.core_properties.author = "PEClaw"
    document.core_properties.created = datetime(2020, 1, 1, tzinfo=timezone.utc)
    document.core_properties.modified = datetime(2020, 1, 1, tzinfo=timezone.utc)
    document.sections[0].header.paragraphs[0].text = rows[0][1]
    for level, text in rows:
        if level:
            document.add_heading(text, level=min(level, 3))
        else:
            document.add_paragraph(text)
    stream = io.BytesIO()
    document.save(stream)
    # Freeze ZIP timestamps for byte-identical idempotent replay.
    output = io.BytesIO()
    with (
        ZipFile(io.BytesIO(stream.getvalue())) as source,
        ZipFile(output, "w", compression=ZIP_DEFLATED) as target,
    ):
        for name in sorted(source.namelist()):
            info = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            target.writestr(info, source.read(name))
    return output.getvalue()
