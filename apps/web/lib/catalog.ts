export const fieldLabels: Record<string, string> = {
  canonical_name: "标准名称",
  registration_name: "登记名称",
  listing_status: "上市状态",
  company_stage: "发展阶段",
  financing_stage: "融资阶段",
  country: "国家或地区",
  province: "省份",
  city: "城市",
  unified_social_credit_code: "统一社会信用代码",
};
export const labels: Record<string, string> = {
  unknown: "未知",
  listed: "已上市",
  unlisted: "未上市",
  delisted: "已退市",
  research: "研究",
  prototype: "原型",
  pilot: "中试",
  commercial: "商业化",
  scaled: "量产",
  seed: "种子轮",
  angel: "天使轮",
  A: "A轮",
  B: "B轮",
  C: "C轮",
  pre_ipo: "Pre-IPO",
  other: "其他",
  unverified: "待核验",
  verified: "人工已核验",
  conflicting: "存在冲突",
  rejected: "已拒绝",
  fact: "来源事实",
  inference: "分析推断",
  queued: "排队中",
  running: "处理中",
  completed: "已完成",
  failed: "失败",
  created: "已创建",
  skipped: "已跳过",
  review_required: "待人工核实",
  error: "行错误",
  announced: "公开声明",
  develops: "研发",
  manufactures: "制造",
  licenses: "许可",
  uses: "使用",
  researches: "研究",
};
export type Source = {
  id: string;
  source_name: string;
  source_type: string;
  source_url: string | null;
  publisher: string | null;
  license_type: string;
  permitted_use: string;
  reliability_level: string;
  accessed_at: string;
};
export type Taxonomy = {
  industries: {
    id: string;
    name: string;
    parent_id: string | null;
    level: number;
    description: string;
  }[];
  technologies: {
    id: string;
    name: string;
    aliases: string[];
    parent_id: string | null;
    description: string;
  }[];
};
export type CompanySummary = {
  id: string;
  canonical_name: string;
  province: string | null;
  city: string | null;
  listing_status: string;
  company_stage: string;
  financing_stage: string;
  source_status: string;
  source_id: string;
  version: number;
  description: string | null;
  updated_at: string;
  is_archived: boolean;
};
export type Evidence = {
  id: string;
  company_id: string;
  source_id: string;
  claim_text: string;
  excerpt: string;
  field_name: string | null;
  field_value: string | null;
  classification: string;
  verification_status: string;
  page_number: number | null;
  section_name: string | null;
  reviewer_id: string | null;
  reviewed_at: string | null;
};
export type Company = CompanySummary & {
  registration_name: string | null;
  country: string;
  website: string | null;
  unified_social_credit_code: string | null;
  founded_on: string | null;
  aliases: string[];
  industry_ids: string[];
  industries: { id: string; name: string }[];
  merged_into_id: string | null;
  sources: Source[];
  evidence: Evidence[];
  conflicts: { field_name: string; values: string[]; evidence_ids: string[] }[];
  products: {
    id: string;
    name: string;
    product_category: string;
    description: string;
    technical_route: string;
    commercialization_stage: string;
    verification_status: string;
    evidence_id: string;
  }[];
  technologies: {
    id: string;
    name: string;
    relation_type: string;
    verification_status: string;
    evidence_id: string;
  }[];
  related_records: { id: string; name: string; version: number }[];
  merges: {
    id: string;
    target_id: string;
    duplicate_id: string;
    reason: string;
    created_at: string;
    reverted_at: string | null;
  }[];
};
export type SearchResult = {
  items: CompanySummary[];
  total: number;
  limit: number;
  offset: number;
  matched_intent?: string[];
  limitations?: string;
  unparsed_criteria?: string[];
};
export type ImportJob = {
  id: string;
  source_id: string;
  state: string;
  attempts: number;
  error_code: string | null;
  created_at: string;
  result: {
    counts?: Record<string, number>;
    rows?: {
      row: number;
      status: string;
      company_id?: string;
      candidate_ids?: string[];
      code?: string;
    }[];
  };
};
export type Change = {
  id: string;
  source_id: string;
  action: string;
  reason: string;
  created_at: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
};
export function companyPayload(data: FormData) {
  const text = (key: string) => String(data.get(key) || "").trim();
  const nullable = (key: string) => text(key) || null;
  return {
    canonical_name: text("canonical_name"),
    registration_name: nullable("registration_name"),
    aliases: text("aliases")
      .split("|")
      .map((v) => v.trim())
      .filter(Boolean),
    country: text("country") || "unknown",
    province: nullable("province"),
    city: nullable("city"),
    website: nullable("website"),
    unified_social_credit_code: nullable("unified_social_credit_code"),
    founded_on: nullable("founded_on"),
    description: nullable("description"),
    listing_status: text("listing_status") || "unknown",
    company_stage: text("company_stage") || "unknown",
    financing_stage: text("financing_stage") || "unknown",
    industry_ids: data.getAll("industry_ids"),
    source_id: text("source_id"),
    reason: text("reason"),
  };
}
