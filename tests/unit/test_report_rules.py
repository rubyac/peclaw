import io
from types import SimpleNamespace
from uuid import uuid4

import pytest
from docx import Document
from pydantic import ValidationError

from app.reports.quality import metric_problem, numbers, unit_matches
from app.reports.render import render
from app.reports.templates import body
from app.schemas.reports import MetricInput


def test_numeric_gate_distinguishes_units_and_keeps_decimals_exact():
    assert unit_matches("亿元人民币", "亿元")
    assert not unit_matches("亿元人民币", "元")
    assert not unit_matches("万元", "元")
    assert not unit_matches("亿元", "亿")
    assert not unit_matches("万元/年", "万元")
    assert unit_matches("万片/月，原文", "万片/月")
    assert [str(n) for n, _, _ in numbers("2025年收入为1.20亿元，第3页。")] == ["1.20"]
    item = SimpleNamespace(
        metric_value="1.2",
        unit="亿元",
        period="2025年",
        currency="CNY",
        evidence_id="x",
        source_quote="2025年收入为1.2亿元人民币。",
        verification_status="unverified",
    )
    assert metric_problem(item, {"x": {"excerpt": item.source_quote}}) is None
    item.metric_value = "12"
    assert metric_problem(item, {"x": {"excerpt": item.source_quote}}) == "VALUE_NOT_IN_QUOTE"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e100000", "0e100000", "0.0000000001"])
def test_metric_rejects_non_finite_or_excessive_precision(value):
    with pytest.raises(ValidationError):
        MetricInput(
            expected_revision=1,
            metric_name="收入",
            metric_type="revenue",
            metric_value=value,
            unit="亿元",
            currency="CNY",
            period="2025年",
            evidence_id="x",
            source_quote="原文",
        )


def test_exports_are_deterministic_watermarked_and_do_not_create_active_markup():
    content = body("company_profile")
    content["summary"]["text"] = (
        '<img src="https://private.example" onerror="alert(1)"> [资料](https://example.com)'
    )
    report = SimpleNamespace(
        id=uuid4(),
        revision=1,
        title="合成模板报告",
        template_version="company_profile@1.0.0",
        content=content,
    )
    first = render(report, [], [], None, "draft", "docx")
    assert first == render(report, [], [], None, "draft", "docx")
    document = Document(io.BytesIO(first))
    assert "未审核" in document.sections[0].header.paragraphs[0].text
    assert any("<img" in p.text for p in document.paragraphs)
    markdown = render(report, [], [], None, "draft", "md").decode()
    assert "未审核" in markdown and "<img" not in markdown and "&lt;img" in markdown
    assert "[资料](" not in markdown
    assert "正式导出" in render(report, [], [], "审核人", "formal", "md").decode()
