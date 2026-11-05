"""Conservative mechanical gates, complemented by explicit human confirmations."""

import hashlib
import json
import re
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.models.catalog import Evidence
from app.models.reports import KeyMetric
from app.reports.sources import resolve
from app.reports.templates import TEMPLATES

# A number immediately following Chinese text has no ASCII word boundary.
NUMBER = re.compile(r"(?<![a-zA-Z0-9_.])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
CLASS_NAMES = {
    "fact": "事实",
    "inference": "推断",
    "unverified": "待核验",
    "unknown": "未知",
    "conflicting": "来源冲突",
}
CURRENCIES = {
    "CNY": ["人民币", "CNY", "¥", "￥"],
    "USD": ["美元", "USD", "$"],
    "EUR": ["欧元", "EUR", "€"],
    "HKD": ["港元", "HKD"],
    "JPY": ["日元", "JPY"],
}


def metrics(db, report):
    return db.scalars(
        select(KeyMetric).where(KeyMetric.report_id == report.id).order_by(KeyMetric.id)
    ).all()


def metric_output(item):
    return {
        key: getattr(item, key)
        for key in [
            "id",
            "metric_name",
            "metric_type",
            "metric_value",
            "unit",
            "currency",
            "period",
            "evidence_id",
            "source_quote",
            "verification_status",
            "reviewer_id",
            "reviewed_at",
            "notes",
            "review_notes",
        ]
    }


def fingerprint(db, report):
    values = {
        "title": report.title,
        "template": report.template_version,
        "content": report.content,
        "evidence_refs": report.evidence_refs,
        "reviewer_id": str(report.reviewer_id),
        "metrics": [metric_output(m) for m in metrics(db, report)],
    }
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def numbers(text):
    text = text.replace("％", "%").replace("−", "-")
    for match in NUMBER.finditer(text):
        before = text[max(0, match.start() - 2) : match.start()]
        after = text[match.end() : match.end() + 64]
        if re.fullmatch(r"(?:19|20)\d{2}", match.group()) and (
            after.startswith("年") or after.startswith("-")
        ):
            continue
        if before.rstrip().endswith("第") and after.startswith(("页", "章", "项", "节")):
            continue
        yield Decimal(match.group().replace(",", "")), match.group(), after


def unit_matches(after, unit):
    after = after.strip().replace("％", "%")
    if not after.startswith(unit):
        return False
    rest = after[len(unit) :].lstrip()
    if rest.startswith(("人民币", "美元", "港元", "日元", "欧元")):
        return True
    # Preserve compound units (e.g. 万片/月), and forbid a shorter unit prefix.
    return re.match(r"^[元台家片吨个份人倍%/千百千万亿兆]", rest) is None


def metric_problem(item, evidence):
    if item.metric_value is None:
        return (
            None
            if item.verification_status == "not_applicable" and len(item.review_notes.strip()) >= 5
            else "MISSING_VALUE"
        )
    source = evidence.get(item.evidence_id)
    if not source or not item.source_quote or item.source_quote not in source["excerpt"]:
        return "QUOTE_MISMATCH"
    # Registry values must actually occur in the quote. No silent unit or FX conversion.
    value = Decimal(item.metric_value)
    quote_numbers = [
        n for n, _, tail in numbers(item.source_quote) if unit_matches(tail, item.unit)
    ]
    if value not in quote_numbers:
        return "VALUE_NOT_IN_QUOTE"
    normalized = item.source_quote.replace("％", "%")
    if item.unit not in normalized or item.period not in item.source_quote:
        return "UNIT_OR_PERIOD_MISSING"
    if item.currency and not any(
        alias in item.source_quote for alias in CURRENCIES.get(item.currency, [item.currency])
    ):
        return "CURRENCY_MISSING"
    return None


def claims(content):
    yield content["summary"]
    for section in content["sections"]:
        yield from section["claims"]


def quality(db, user, report):
    evidence = resolve(db, user, report.organization_id, report.project_id, report.evidence_refs)
    index = {e["id"]: e for e in evidence}
    items = metrics(db, report)
    issues = []

    def issue(code, message, resource=None):
        if len(issues) < 100:
            issues.append(
                {
                    "code": code,
                    "message": message,
                    "resource_id": str(resource) if resource else None,
                }
            )

    required = TEMPLATES[report.content["workflow"]]
    if sorted(s["key"] for s in report.content["sections"]) != sorted(required):
        issue("TEMPLATE_INCOMPLETE", "报告章节与模板不一致。")
    used = set()
    for item in items:
        if item.evidence_id:
            used.add(item.evidence_id)
        if item.verification_status not in {"verified", "not_applicable"}:
            issue("METRIC_UNVERIFIED", "关键数字未经审核、存在冲突或已被拒绝。", item.id)
        problem = metric_problem(item, index)
        if problem:
            issue(problem, "关键数字的精确原文、数值、单位、币种或期间未匹配。", item.id)
        if item.verification_status == "verified" and (
            item.reviewer_id != report.reviewer_id
            or not item.reviewed_at
            or item.metric_value is None
        ):
            issue("METRIC_REVIEW_INVALID", "数字核验必须由当前指定审核人完成。", item.id)
    for item in items:
        for value, raw, tail in numbers(item.source_quote):
            if not any(
                m.metric_value is not None
                and Decimal(m.metric_value) == value
                and m.evidence_id == item.evidence_id
                and unit_matches(tail, m.unit)
                and m.verification_status == "verified"
                and not metric_problem(m, index)
                for m in items
            ):
                issue(
                    "UNREGISTERED_QUOTE_NUMBER", f"数字原文中的 {raw} 尚未逐项登记核验。", item.id
                )
    registry_values = {}
    for item in items:
        if item.metric_value is not None:
            key = (item.metric_name, item.metric_type, item.period, item.unit, item.currency)
            registry_values.setdefault(key, set()).add(Decimal(item.metric_value))
    if any(len(values) > 1 for values in registry_values.values()):
        issue("METRIC_VALUE_CONFLICT", "同名指标在相同期间、单位和币种下存在不同值，需先解决冲突。")
    all_claims = list(claims(report.content))
    for claim in all_claims:
        ids = set(claim["evidence_ids"])
        used.update(ids)
        if not ids.issubset(index):
            issue("REFERENCE_MISSING", "正文引用不在报告授权证据集合内。")
        if claim["classification"] != "unknown" and not ids:
            issue("CLAIM_WITHOUT_SOURCE", "非未知陈述缺少来源。")
        if claim["classification"] == "conflicting":
            issue("UNRESOLVED_CONFLICT", "正文仍含未解决的来源冲突。")
        for value, raw, after in numbers(claim["text"]):
            matched = any(
                m.metric_value is not None
                and Decimal(m.metric_value) == value
                and m.evidence_id in ids
                and unit_matches(after, m.unit)
                and m.verification_status == "verified"
                and not metric_problem(m, index)
                for m in items
            )
            if not matched:
                issue(
                    "UNREGISTERED_NUMBER",
                    f"正文数字 {raw} 未关联同一引用下已核验且单位匹配的数字登记。",
                )
        if re.search(
            r"[一二三四五六七八九十百两][零〇一二三四五六七八九十百千万亿两]*(?:元|台|家|%)",
            claim["text"],
        ):
            issue(
                "CHINESE_NUMBER_REQUIRES_CHECK",
                "中文数词金额或数量需改为可核验的明确数字，或仅保留不含数值的待核实描述。",
            )
    extra_text = [report.title, *report.content["unknowns"], *report.content["limitations"]]
    extra_text.extend(text for item in items for text in [item.notes, item.review_notes])
    for question in report.content["questions"]:
        ids = set(question["evidence_ids"])
        used.update(ids)
        if not ids.issubset(index):
            issue("REFERENCE_MISSING", "尽调问题引用缺失。")
        extra_text.extend(
            question[key]
            for key in [
                "question",
                "reason",
                "risk",
                "known_information",
                "missing_evidence",
                "verification_method",
            ]
        )
    # Keep numeric assertions out of unregistered free-text channels.
    if any(list(numbers(text)) for text in extra_text):
        issue(
            "NUMBER_IN_FREE_TEXT",
            "标题、问题或自由文本出现未纳入逐条引用核验的数字，请移入带引用的正文和数字登记。",
        )
    if not used.issubset(index):
        issue("REFERENCE_MISSING", "数字或正文引用已缺失。")
    fields = {}
    for ref in report.evidence_refs:
        if ref["id"] not in used or ref["kind"] != "public_evidence":
            continue
        source = db.get(Evidence, UUID(ref["resource_id"]))
        if source.classification == "conflicting" or source.verification_status in {
            "conflicting",
            "rejected",
        }:
            issue("SOURCE_CONFLICT", "引用来源被标为冲突或拒绝，不能正式导出。", source.id)
        if source.field_name and source.field_value is not None:
            fields.setdefault((source.company_id, source.field_name), set()).add(source.field_value)
    if any(len(values) > 1 for values in fields.values()):
        issue("SOURCE_VALUE_CONFLICT", "相同企业字段存在不同来源值。")
    return {
        "passed": not issues,
        "issues": issues,
        "policy_version": "strict@1.0.0",
        "evidence": evidence,
        "limitations": [
            "规则只校验登记、引用与字面数值，不证明业务口径、财务真实性或模型结论。",
            "日期和页码有有限豁免，中文财务数词保守阻止；审核人仍须确认登记完整、无虚构数据。",
        ],
    }
