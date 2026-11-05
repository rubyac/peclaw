"""Named, denominator-aware metrics. No hidden model judge or synthetic business scores."""

import math
import unicodedata


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def ranked_metrics(predicted, judgments, k):
    predicted = list(dict.fromkeys(str(value) for value in predicted))[:k]
    labels = {str(key): grade for key, grade in judgments.items()}
    known = [key for key in predicted if key in labels]
    hits = sum(labels[key] > 0 for key in known)
    relevant = sum(grade > 0 for grade in labels.values())
    ideal = sorted(labels.values(), reverse=True)[:k]
    idcg = sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(ideal))
    dcg = sum(
        (2 ** labels.get(key, 0) - 1) / math.log2(rank + 2) for rank, key in enumerate(predicted)
    )
    complete = len(known) == len(predicted)
    return {
        "returned_count": len(predicted),
        "judged_returned_count": len(known),
        "positive_label_count": relevant,
        "judgment_coverage": ratio(len(known), len(predicted)),
        "precision_on_judged": ratio(hits, len(known)),
        "precision_at_k": ratio(hits, k) if complete else None,
        "recall_on_labeled_positives": ratio(hits, relevant),
        "ndcg_at_k": ratio(dcg, idcg) if complete else None,
    }


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


def claim_metrics(observed, expected):
    predicted = {(normalized(c["text"]), c["classification"]) for c in observed}
    gold = {(normalized(c["text"]), c["classification"]) for c in expected}
    correct = len(predicted & gold)
    return {
        "observed_unique_count": len(predicted),
        "expected_unique_count": len(gold),
        "exact_claim_precision": ratio(correct, len(predicted)),
        "exact_claim_recall": ratio(correct, len(gold)),
        "unknown_exact_recall": ratio(
            len({item for item in predicted & gold if item[1] == "unknown"}),
            sum(item[1] == "unknown" for item in gold),
        ),
    }


def summary(records, feedback, data_kind):
    measured = [r for r in records if r["status"] == "measured"]
    latest = {}
    for item in feedback:
        latest[(str(item.created_by), item.case_id)] = item
    independent = [f for f in latest.values() if f.independent]
    model_cases = {
        r["case_id"]: r for r in measured if r["kind"] in {"fact_extraction", "bp_screening"}
    }

    def source_key(record):
        return record.get("provenance", {}).get("task_id", record["case_id"])

    fact_keys = {
        (source_key(r), normalized(c["text"]))
        for r in model_cases.values()
        for c in r.get("observed_claims", [])
        if c["classification"] == "fact"
    }
    fact_total = len(fact_keys)
    fact_votes = {}
    usable_votes = {}
    numeric_votes = {}
    for f in independent:
        record = model_cases.get(f.case_id)
        if not record:
            continue
        key = source_key(record)
        for item in f.claim_judgments:
            claim = record["observed_claims"][item["index"]]
            if claim["classification"] == "fact":
                fact_votes.setdefault((key, normalized(claim["text"])), set()).add(item["correct"])
        if f.usable is not None:
            usable_votes.setdefault(key, set()).add(f.usable)
        if f.numeric_correct is not None:
            numeric_votes.setdefault(key, set()).add(f.numeric_correct)
    fact_ratings = {key: next(iter(votes)) for key, votes in fact_votes.items() if len(votes) == 1}
    usable = [next(iter(votes)) for votes in usable_votes.values() if len(votes) == 1]
    numeric = [next(iter(votes)) for votes in numeric_votes.values() if len(votes) == 1]
    conflicting = sum(
        len(votes) > 1
        for group in [fact_votes, usable_votes, numeric_votes]
        for votes in group.values()
    )
    by_kind = {}
    for record in records:
        kind = record["kind"]
        by_kind.setdefault(kind, {"measured": 0, "blocked": 0, "failed": 0})[record["status"]] += 1
    failures = {}
    for record in records:
        if record.get("error_code"):
            failures[record["error_code"]] = failures.get(record["error_code"], 0) + 1
    latencies = sorted(r["latency_ms"] for r in measured)

    def percentile(p):
        if not latencies:
            return None
        index = (len(latencies) - 1) * p
        low = math.floor(index)
        high = math.ceil(index)
        return latencies[low] + (latencies[high] - latencies[low]) * (index - low)

    upstream = {
        r["provenance"]["task_id"]: r.get("upstream_calls", [])
        for r in measured
        if r.get("provenance")
    }
    calls = [call for rows in upstream.values() for call in rows]
    costs = [
        call["estimated_cost_micros"] for call in calls if call["estimated_cost_micros"] is not None
    ]
    return {
        "p50_case_latency_ms": percentile(0.5),
        "p95_case_latency_ms": percentile(0.95),
        "new_model_calls": 0,
        "unique_upstream_tasks": len(upstream),
        "upstream_call_count": len(calls),
        "upstream_cost_micros": sum(costs) if calls and len(costs) == len(calls) else None,
        "upstream_priced_call_count": len(costs),
        "case_count": len(records),
        "measured_count": len(measured),
        "by_kind": by_kind,
        "failure_types": failures,
        "mean_case_latency_ms": ratio(sum(r["latency_ms"] for r in measured), len(measured)),
        "independent_fact_accuracy": ratio(sum(fact_ratings.values()), len(fact_ratings)),
        "independent_fact_judged_count": len(fact_ratings),
        "fact_claim_count": fact_total,
        "independent_fact_review_coverage": ratio(len(fact_ratings), fact_total),
        "independent_model_usability_rate": ratio(sum(usable), len(usable)),
        "independent_usability_case_count": len(usable),
        "independent_numeric_case_accuracy": ratio(sum(numeric), len(numeric)),
        "independent_numeric_case_count": len(numeric),
        "conflicting_human_judgment_count": conflicting,
        "feedback_count": len(feedback),
        "self_feedback_count": sum(not f.independent for f in latest.values()),
        "business_assessment": "not_assessed"
        if data_kind == "synthetic" or not independent
        else "human_labels_only",
        "limitations": [
            "合成工程回归不代表真实业务效果；空分母显示未知，不以零或百分百替代。",
            "文本精确匹配不是语义事实准确率，排名分数仅对应提交的标注集合。",
            "人工指标只采用非作者的指定评审反馈；自评单列，未评分样本不算通过。",
            "评测耗时不等于模型推理耗时，已完成任务用量单独保留，不重复计为新调用。",
        ],
    }
