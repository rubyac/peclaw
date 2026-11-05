export const documentStates: Record<string, string> = {
  uploading: "原文上传中",
  uploaded: "等待处理",
  validating: "正在校验",
  parsing: "正在解析",
  chunking: "正在切分",
  embedding: "正在建立语义索引",
  indexed: "已可检索",
  failed: "处理失败",
  deleting: "索引已撤下，原文清理中",
  deleted: "原文与索引已清理",
};
export const fileErrors: Record<string, string> = {
  NO_TEXT_LAYER: "扫描件或没有可提取文字，需要先做 OCR。",
  ENCRYPTED_PDF: "PDF 已加密，请先提供解密后的授权副本。",
  PARSER_FAILED: "文件无法正常解析，请检查内容或重新导出。",
  PARSER_RESOURCE_LIMIT: "文件解析超出资源或时间限制，请拆分文件后重新上传。",
  ACCESS_REVOKED: "任务执行者的权限已撤销，请由有权限的编辑者重试。",
  RAW_FILE_HASH_MISMATCH: "原始文件校验不一致，未使用受影响内容建立索引。",
  UPLOAD_FAILED: "原文存储失败，请重新上传同一文件或添加新版本。",
  UPLOAD_INTERRUPTED: "原文上传未完成，请重新上传。",
  ATTEMPTS_EXHAUSTED: "任务已达到三次执行上限，请检查原文件并添加新版本。",
  OBJECT_DELETE_FAILED:
    "原文尚未清理成功；内容已不可通过应用访问，可重试清理。",
  EXTRACTED_TEXT_LIMIT: "提取内容超过上限，请拆分文件。",
  CHUNK_LIMIT: "文档片段过多，请拆分文件。",
  TABLE_LIMIT: "表格规模超过解析上限，请拆分工作表。",
  UNSAFE_XML: "文件含有不允许的 XML 声明。",
  EMPTY_DOCUMENT: "没有可提取的文本。",
};
export type PrivateVersion = {
  id: string;
  number: number;
  filename: string;
  file_format: string;
  byte_size: number;
  content_hash: string;
  status: string;
  attempts: number;
  error_code: string | null;
  chunk_count: number;
  created_at: string;
  finished_at: string | null;
};
export type PrivateDocument = {
  id: string;
  organization_id: string;
  project_id: string;
  title: string;
  current_version: number;
  revision: number;
  access_scope: string;
  is_deleted: boolean;
  can_read: boolean;
  can_write: boolean;
  can_manage: boolean;
  current: PrivateVersion | null;
  created_at: string;
  updated_at: string;
  versions?: PrivateVersion[];
};
export type Citation = {
  chunk_id: string;
  document_id: string;
  version_id: string;
  version_number: number;
  document_title: string;
  project_id: string;
  excerpt: string;
  content_hash: string;
  file_hash: string;
  page_number: number | null;
  section_name: string | null;
  locator: Record<string, string | number>;
  start_offset: number;
  end_offset: number;
  matched_by: string[];
};
export type KnowledgeSearch = {
  items: Citation[];
  mode: string;
  semantic_available: boolean;
  limitations: string;
};
export type EligibleMember = {
  user_id: string;
  full_name: string;
  email: string;
  can_edit: boolean;
};
export type Permissions = {
  revision: number;
  access_scope: "project" | "restricted";
  grants: { user_id: string; role: string }[];
};
export function locationLabel(c: Citation): string {
  const p = c.locator;
  if (p.type === "pdf") return `第 ${c.page_number} 页`;
  if (p.type === "pptx")
    return `第 ${p.slide} 张幻灯片${p.row ? ` · 表格第 ${p.row} 行` : ""}`;
  if (p.type === "xlsx") return `工作表 ${p.sheet} · 第 ${p.row} 行`;
  if (p.type === "docx")
    return p.table ? `表格 ${p.table} · 第 ${p.row} 行` : `段落 ${p.paragraph}`;
  return `第 ${p.line_start}–${p.line_end} 行${c.section_name ? ` · ${c.section_name}` : ""}`;
}
export async function filePayload(file: File) {
  if (!file.size || file.size > 10 * 1024 * 1024)
    throw new Error("请选择不超过 10 MiB 的有效文件");
  if (!/\.(pdf|docx|xlsx|pptx|txt|md)$/i.test(file.name))
    throw new Error("仅支持 PDF、DOCX、XLSX、PPTX、TXT、Markdown");
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 32768)
    binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return {
    filename: file.name,
    content_base64: btoa(binary),
    idempotency_key: crypto.randomUUID(),
  };
}
