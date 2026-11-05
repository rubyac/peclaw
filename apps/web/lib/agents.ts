export const workflows: Record<string, string> = {
  company_discovery: "企业发现",
  company_profile: "企业画像",
  project_match: "项目匹配",
  bp_screening: "BP 初筛",
  due_diligence: "尽调问题",
};
export const taskStates: Record<string, string> = {
  queued: "等待执行",
  retrieving: "检索与授权检查",
  calling: "模型处理中",
  validating: "校验结构与引用",
  review_required: "草案待人工审核",
  failed: "执行失败",
  cancelled: "已取消",
};
export const activeStates = ["queued", "retrieving", "calling", "validating"];
export const agentErrors: Record<string, string> = {
  MODEL_NOT_CONFIGURED: "模型尚未配置，请由部署管理员设置服务与凭据。",
  MODEL_AUTH_FAILED: "模型鉴权失败，请管理员检查凭据与模型权限。",
  MODEL_RATE_LIMIT: "模型服务限流，可稍后重试。",
  MODEL_TIMEOUT: "模型调用超时，可稍后重试。",
  MODEL_UNAVAILABLE: "模型服务暂时不可用。",
  MODEL_NETWORK_ERROR: "无法连接模型服务，请检查网络与端点配置。",
  MODEL_REQUEST_REJECTED: "模型服务拒绝请求，请检查接口和模型兼容性。",
  MODEL_INVALID_RESPONSE: "模型返回协议不合法，未保存为分析结果。",
  MODEL_INCOMPLETE: "模型输出不完整，请减少输入或调整输出上限。",
  OUTPUT_SCHEMA_INVALID: "模型结果不符合工作流结构，未作为草案展示。",
  OUTPUT_REFERENCE_INVALID:
    "模型引用了不在授权上下文中的证据或企业，结果已拒绝。",
  OUTPUT_REFERENCE_MISSING: "模型结论缺少证据引用，结果已拒绝。",
  OUTPUT_FACT_UNVERIFIED: "模型把未核验材料当成事实，结果已拒绝。",
  ACCESS_REVOKED: "账号、项目或原文权限已撤销，停止执行。",
  EVIDENCE_CHANGED: "引用材料已变化，请核对后新建任务。",
  DOCUMENT_NOT_INDEXED: "所选文档尚未完成索引。",
  CONTEXT_LIMIT: "资料超过任务上下文限制，请减少文件或缩小范围。",
  ORG_TOKEN_BUDGET:
    "本机构当日模型用量预算已用尽，请等待预算重置或联系管理员。",
  ATTEMPTS_EXHAUSTED: "已达到三次执行上限，请检查原因后新建任务。",
  PROMPT_VERSION_UNAVAILABLE: "原提示词版本不可用，请新建任务。",
  TASK_CANCELLED: "任务已取消。",
};
export const sectionLabels: Record<string, string> = {
  selection_reasons: "候选入选理由",
  verification_gaps: "待核验事项",
  company: "企业概况",
  products_technology: "产品与技术",
  industry_position: "产业位置",
  risks: "主要风险",
  fit: "匹配理由",
  mismatch: "不匹配因素",
  comparability: "历史可比性",
  gaps: "数据缺口",
  company_team: "企业与团队",
  market_competition: "市场与竞争",
  commercialization: "商业化进展",
  financial_financing: "财务与融资",
  strategy_fit: "投资策略匹配",
  technical: "技术真实性",
  commercial: "客户与商业化",
  financial: "财务",
  legal: "合规与法律",
};
export type Claim = {
  text: string;
  classification: string;
  evidence_ids: string[];
};
export type Task = {
  id: string;
  kind: string;
  status: string;
  attempts: number;
  error_code: string | null;
  prompt_version: string;
  prompt_hash: string;
  created_at: string;
  updated_at: string;
};
export type ModelConfig = {
  configured: boolean;
  provider: string;
  model: string;
  max_output_tokens: number;
  daily_token_limit: number;
  concurrency: number;
  definitions: {
    kind: string;
    prompt_version: string;
    prompt_hash: string;
    section_keys: string[];
  }[];
};
export type AgentEvidence = {
  id: string;
  kind: string;
  excerpt: string;
  company_id?: string;
  document_id?: string;
  project_id?: string;
  version_number?: number;
  page_number?: number | null;
  section_name?: string | null;
  locator?: Record<string, string | number>;
  classification?: string;
  verification_status?: string;
  updated_at?: string;
};
export type TaskDetail = Task & {
  inputs: { question: string; thesis: string };
  review_notice: string;
  evidence: AgentEvidence[];
  calls: {
    attempt: number;
    provider: string;
    model: string;
    status: string;
    reserved_tokens: number;
    input_tokens: number | null;
    output_tokens: number | null;
    latency_ms: number | null;
    estimated_cost_micros: number | null;
    error_code: string | null;
  }[];
  result: {
    workflow: string;
    summary: Claim;
    candidate_ids: string[];
    sections: { key: string; claims: Claim[] }[];
    questions: {
      question: string;
      reason: string;
      risk: string;
      known_information: string;
      missing_evidence: string;
      verification_method: string;
      priority: string;
      evidence_ids: string[];
    }[];
    unknowns: string[];
    limitations: string[];
  } | null;
};
