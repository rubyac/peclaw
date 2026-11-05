"""Synthetic HTTP provider fixtures used only by tests, never by the application runtime."""

import json

from app.agents.prompts import SECTION_KEYS


def synthetic_result(context):
    refs = [e["id"] for e in context["evidence"][:1]]
    claim = {
        "text": "仅用于测试结构化协议的合成结论，须人工核验。",
        "classification": "unverified" if refs else "unknown",
        "evidence_ids": refs,
    }
    return {
        "workflow": context["workflow"],
        "summary": claim,
        "candidate_ids": context["candidate_company_ids"],
        "sections": [{"key": key, "claims": [claim]} for key in SECTION_KEYS[context["workflow"]]],
        "questions": [
            {
                "question": "如何核实客户验证标准？",
                "reason": "合成协议测试",
                "risk": "资料不足",
                "known_information": "仅有合成原文",
                "missing_evidence": "客户授权访谈",
                "verification_method": "人工核对授权访谈与测试记录",
                "priority": "high",
                "evidence_ids": refs,
            }
        ],
        "unknowns": ["该合成响应不用于评估真实模型质量"],
        "limitations": ["仅用于测试"],
    }


def wire_response(context):
    return {
        "choices": [
            {
                "message": {"content": json.dumps(synthetic_result(context), ensure_ascii=False)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 80},
    }
