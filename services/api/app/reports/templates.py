from copy import deepcopy

from app.agents.prompts import SECTION_KEYS

TEMPLATES = deepcopy(SECTION_KEYS)
TEMPLATES["bp_screening"] = [
    "project_basics",
    "company_team",
    "products_technology",
    "market_competition",
    "commercialization",
    "financial_financing",
    "strategy_fit",
    "advantages",
    "risks",
    "diligence_questions",
    "gaps",
    "sources",
    "conclusion_limitations",
]
LABELS = {
    "selection_reasons": "候选入选理由",
    "verification_gaps": "待核验事项",
    "company": "企业概况",
    "products_technology": "产品与技术",
    "industry_position": "产业位置",
    "risks": "主要风险",
    "fit": "匹配理由",
    "mismatch": "不匹配因素",
    "comparability": "历史可比性",
    "gaps": "数据缺口",
    "company_team": "企业与团队",
    "market_competition": "市场与竞争格局",
    "commercialization": "商业化进展",
    "financial_financing": "财务与融资",
    "strategy_fit": "投资策略匹配",
    "technical": "技术真实性",
    "commercial": "客户与商业化",
    "financial": "财务",
    "legal": "合规与法律",
    "project_basics": "项目基本情况",
    "advantages": "潜在优势",
    "diligence_questions": "尽调问题",
    "sources": "证据与来源",
    "conclusion_limitations": "初步结论及局限性",
}


def body(template, source=None):
    unknown = {
        "text": "待核实：暂无足以支持结论的材料。",
        "classification": "unknown",
        "evidence_ids": [],
    }
    result = (
        deepcopy(source)
        if source
        else {
            "workflow": template,
            "summary": unknown,
            "candidate_ids": [],
            "sections": [],
            "questions": [],
            "unknowns": ["需要研究员补充授权证据，未知信息不自动补全。"],
            "limitations": ["这是报告模板，不是模型生成的分析或经核验的投资判断。"],
        }
    )
    existing = {section["key"]: section for section in result["sections"]}
    result["sections"] = [
        existing.get(key, {"key": key, "claims": [deepcopy(unknown)]})
        for key in TEMPLATES[template]
    ]
    result["workflow"] = template
    return result
