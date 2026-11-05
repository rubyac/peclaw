import type { AgentEvidence, TaskDetail } from "./agents";
export const caseKinds: Record<string, string> = {
  company_search: "企业搜索",
  knowledge_retrieval: "知识检索",
  fact_extraction: "事实陈述对照",
  bp_screening: "BP 初筛对照",
  report_quality: "报告质量闸",
};
export const evaluationStates: Record<string, string> = {
  queued: "等待执行",
  running: "评测中",
  completed: "已完成测量（不代表业务通过）",
  failed: "执行失败",
  cancelled: "已取消",
};
export const metricLabels: Record<string, string> = {
  returned_count: "实际返回数",
  judged_returned_count: "已标注返回数",
  positive_label_count: "相关标注数",
  judgment_coverage: "标注覆盖率",
  precision_on_judged: "已标注返回的精确率",
  precision_at_k: "P@k",
  recall_on_labeled_positives: "已标注正例召回率",
  ndcg_at_k: "NDCG@k",
  observed_unique_count: "去重后的陈述数",
  expected_unique_count: "预期陈述数",
  exact_claim_precision: "文本精确匹配精确率",
  exact_claim_recall: "文本精确匹配召回率",
  unknown_exact_recall: "未知陈述精确匹配召回率",
  gate_expectation_match: "质量闸断言一致性",
  actual_gate_passed: "实际机械质量闸",
  expected_gate_passed: "预期机械质量闸",
};
export type DatasetMeta = {
  id: string;
  version: number;
  data_kind: string;
  created_by: string;
  reviewer_id: string | null;
  content_hash: string;
  created_at: string;
};
export type DraftCase = { id: string; kind: string; [key: string]: unknown };
export type Dataset = DatasetMeta & {
  name: string;
  definition: { cases: DraftCase[]; source_description: string };
  runs: RunMeta[];
};
export type RunMeta = {
  id: string;
  dataset_id: string;
  requested_by: string | null;
  status: string;
  attempts: number;
  error_code: string | null;
  result_hash: string | null;
  engine_version: string;
  created_at: string;
  finished_at: string | null;
};
export type CaseResult = {
  case_id: string;
  kind: string;
  status: string;
  error_code: string | null;
  metrics: Record<string, number | boolean | null>;
  latency_ms: number;
  ranked_ids?: string[];
  observed_output?: NonNullable<TaskDetail["result"]>;
  observed_claims?: {
    text: string;
    classification: string;
    evidence_ids: string[];
  }[];
  provenance?: { task_id: string; prompt_version: string; prompt_hash: string };
  issue_codes?: string[];
};
export type RunDetail = RunMeta & {
  data_kind: string;
  evidence: AgentEvidence[];
  dataset_hash: string;
  records: CaseResult[];
  summary: {
    case_count: number;
    measured_count: number;
    independent_fact_accuracy: number | null;
    independent_fact_judged_count: number;
    independent_fact_review_coverage: number | null;
    independent_model_usability_rate: number | null;
    independent_usability_case_count: number;
    independent_numeric_case_accuracy: number | null;
    independent_numeric_case_count: number;
    new_model_calls: number;
    p50_case_latency_ms: number | null;
    p95_case_latency_ms: number | null;
    upstream_cost_micros: number | null;
    upstream_call_count: number;
    unique_upstream_tasks: number;
    conflicting_human_judgment_count: number;
    failure_types: Record<string, number>;
    business_assessment: string;
    limitations: string[];
  };
  feedback: {
    id: string;
    case_id: string;
    independent: boolean;
    notes: string;
    category: string;
    severity: string;
    created_at: string;
  }[];
};
export function displayMetric(value: number | boolean | null | undefined) {
  if (value === null || value === undefined) return "未评测／未知";
  if (typeof value === "boolean") return value ? "通过" : "未通过";
  return Number.isInteger(value) ? String(value) : value.toFixed(4);
}
export function percent(value: number | null | undefined) {
  return value === null || value === undefined
    ? "未评测／未知"
    : `${(value * 100).toFixed(1)}%`;
}
