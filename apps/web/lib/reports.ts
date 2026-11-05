import type { TaskDetail, AgentEvidence } from "./agents";
export const reportStates: Record<string, string> = {
  draft: "草稿",
  review_required: "待独立审核",
  approved_for_export: "已批准正式导出",
  exported: "已正式导出",
};
export const verificationStates: Record<string, string> = {
  unverified: "未核验",
  verified: "已核验",
  conflicting: "存在冲突",
  rejected: "已拒绝",
  not_applicable: "不适用",
};
export const metricTypes: Record<string, string> = {
  revenue: "收入",
  gross_margin: "毛利率",
  shipment_volume: "出货量",
  capacity: "产能",
  market_size: "市场规模",
  financing_amount: "融资金额",
  valuation: "估值",
  customer_count: "客户数量",
  market_share: "市场份额",
  other: "其他",
};
export type ReportBody = NonNullable<TaskDetail["result"]>;
export type Metric = {
  id: string;
  metric_name: string;
  metric_type: string;
  metric_value: string | null;
  unit: string;
  currency: string | null;
  period: string;
  evidence_id: string | null;
  source_quote: string;
  verification_status: string;
  notes: string;
  review_notes: string;
  reviewer_id: string | null;
  reviewed_at: string | null;
};
export type ReportMeta = {
  id: string;
  template_version: string;
  revision: number;
  status: string;
  created_by: string;
  reviewer_id: string | null;
  can_edit: boolean;
  can_review: boolean;
  updated_at: string;
};
export type ReportDetail = ReportMeta & {
  title: string;
  content: ReportBody;
  provenance: Record<string, string>;
  metrics: Metric[];
  quality: {
    passed: boolean;
    policy_version: string;
    issues: { code: string; message: string; resource_id: string | null }[];
    limitations: string[];
    evidence: AgentEvidence[];
  };
  reviews: {
    id: string;
    revision: number;
    reviewer_id: string;
    decision: string;
    notes: string;
    content_hash: string;
    created_at: string;
  }[];
  exports: {
    id: string;
    revision: number;
    mode: string;
    format: string;
    file_hash: string;
    created_at: string;
  }[];
};
export const reportSectionLabels: Record<string, string> = {
  project_basics: "项目基本情况",
  advantages: "潜在优势",
  diligence_questions: "尽调问题",
  sources: "证据与来源",
  conclusion_limitations: "初步结论与局限性",
};
export type Templates = {
  templates: {
    id: string;
    version: string;
    sections: { key: string; title: string }[];
  }[];
  allow_draft_export: boolean;
  policy_version: string;
};
