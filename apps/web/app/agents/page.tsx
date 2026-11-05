"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CatalogShell } from "@/components/catalog-shell";
import { api, ApiError, type Identity, type Project } from "@/lib/api";
import { type PrivateDocument } from "@/lib/knowledge";
import {
  workflows,
  taskStates,
  activeStates,
  agentErrors,
  sectionLabels,
  type Claim,
  type Task,
  type TaskDetail,
  type ModelConfig,
} from "@/lib/agents";

export default function Page() {
  return (
    <CatalogShell title="AI 研究工作台">
      {(identity) => <Workbench identity={identity} />}
    </CatalogShell>
  );
}
function Workbench({ identity }: { identity: Identity }) {
  const router = useRouter();
  const [org, setOrg] = useState(identity.organizations[0]?.id || "");
  const [project, setProject] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [companies, setCompanies] = useState<
    { id: string; canonical_name: string }[]
  >([]);
  const [documents, setDocuments] = useState<PrivateDocument[]>([]);
  const [config, setConfig] = useState<ModelConfig>();
  const [kind, setKind] = useState("company_profile");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<TaskDetail>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const base = `organizations/${org}/projects/${project}/agent-tasks`;
  const writable = !!projects.find((p) => p.id === project)?.can_write;
  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else if (e instanceof Error && e.name !== "AbortError")
        setError(e.message);
    },
    [router],
  );
  useEffect(() => {
    const c = new AbortController();
    Promise.all([
      api<ModelConfig>("agents/config", { signal: c.signal }),
      api<{ items: { id: string; canonical_name: string }[] }>(
        "companies?limit=100",
        { signal: c.signal },
      ),
    ])
      .then(([cfg, rows]) => {
        setConfig(cfg);
        setCompanies(rows.items);
      })
      .catch(fail);
    return () => c.abort();
  }, [fail]);
  useEffect(() => {
    if (!org) return;
    const c = new AbortController();
    setLoading(true);
    setProjects([]);
    setProject("");
    setTasks([]);
    setSelected("");
    setDetail(undefined);
    api<Project[]>(`organizations/${org}/projects`, { signal: c.signal })
      .then((rows) => {
        setProjects(rows);
        setProject(rows[0]?.id || "");
      })
      .catch(fail)
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [org, fail]);
  useEffect(() => {
    if (!project) return;
    const c = new AbortController();
    setTasks([]);
    setDocuments([]);
    setSelected("");
    setDetail(undefined);
    setError("");
    setNotice("");
    setLoading(true);
    Promise.all([
      api<Task[]>(base, { signal: c.signal }),
      api<PrivateDocument[]>(
        `organizations/${org}/projects/${project}/documents`,
        { signal: c.signal },
      ),
    ])
      .then(([rows, docs]) => {
        setTasks(rows);
        setDocuments(
          docs.filter(
            (d) =>
              d.can_read && !d.is_deleted && d.current?.status === "indexed",
          ),
        );
      })
      .catch(fail)
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [org, project, base, fail]);
  useEffect(() => {
    setDetail(undefined);
    if (!selected) return;
    const c = new AbortController();
    api<TaskDetail>(`${base}/${selected}`, { signal: c.signal })
      .then(setDetail)
      .catch(fail);
    return () => c.abort();
  }, [selected, base, fail]);
  const pending = tasks.some((t) => activeStates.includes(t.status));
  useEffect(() => {
    if (!project || !pending) return;
    const c = new AbortController();
    const timer = setInterval(async () => {
      try {
        const rows = await api<Task[]>(base, { signal: c.signal });
        if (selected) {
          try {
            setDetail(
              await api<TaskDetail>(`${base}/${selected}`, {
                signal: c.signal,
              }),
            );
          } catch (e) {
            setDetail(undefined);
            fail(e);
          }
        }
        setTasks(rows);
      } catch (e) {
        fail(e);
      }
    }, 1500);
    return () => {
      clearInterval(timer);
      c.abort();
    };
  }, [base, project, pending, selected, fail]);
  async function action(task: Task, verb: string) {
    setBusy(true);
    setError("");
    try {
      await api(
        `${base}/${task.id}/${verb}`,
        {
          method: "POST",
          body: JSON.stringify({ expected_attempts: task.attempts }),
        },
        identity.csrf_token,
      );
      if (selected === task.id)
        setDetail(await api<TaskDetail>(`${base}/${task.id}`));
      setTasks(await api<Task[]>(base));
      setNotice(
        verb === "cancel"
          ? "取消已登记；已发出的调用可能仍产生费用，其结果不会发布。"
          : "已重新排队，执行前会再次检查权限与预算。",
      );
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  const name = (id: string) => `evidence-${id.replaceAll(":", "-")}`;
  function claim(value: Claim, index: number) {
    return (
      <article className="agent-claim" key={index}>
        <span className={`claim-label claim-${value.classification}`}>
          {(
            {
              fact: "事实（引用已核验来源）",
              inference: "推断",
              unverified: "待核验",
              unknown: "未知",
              conflicting: "来源冲突",
            } as Record<string, string>
          )[value.classification] || value.classification}
        </span>
        <p>{value.text}</p>
        <div className="agent-reference-links">
          {value.evidence_ids.map((id) => (
            <a href={`#${name(id)}`} key={id}>
              引用 {id.slice(-8)} ↗
            </a>
          ))}
        </div>
      </article>
    );
  }
  return (
    <>
      <div className="workspace-heading">
        <div>
          <div className="eyebrow">EVIDENCE-GUIDED RESEARCH</div>
          <h1>AI 研究工作台</h1>
          <p>明确任务、授权材料、结构化草案；重要判断交由研究员审核。</p>
        </div>
        <Link className="refresh" href="/reports">
          报告与审核 →
        </Link>
        <Link className="refresh" href="/knowledge">
          准备项目资料 →
        </Link>
      </div>
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="success-message">
          {notice}
        </p>
      )}
      <section className="workspace-panel agent-model-status">
        <h2>模型连接</h2>
        {config ? (
          <>
            <p className={config.configured ? "healthy" : "unhealthy"}>
              {config.configured
                ? `已配置 · ${config.provider} / ${config.model}`
                : "尚未配置生成模型"}
            </p>
            <p className="form-note">
              {config.configured
                ? "已配置不代表连接测试通过。提交后将发送研究问题、Thesis 与明确选中的授权证据。"
                : "需要部署管理员设置模型端点、模型名和凭据；当前不会生成分析占位结果。"}
            </p>
            <p className="form-note">
              机构每日预算 {config.daily_token_limit.toLocaleString()} tokens ·
              并发 {config.concurrency} · 每次输出上限{" "}
              {config.max_output_tokens} tokens。预算按 UTC
              日重置，采用保守预留，不等于服务商账单。
            </p>
          </>
        ) : (
          <p className="empty-state">正在读取模型配置…</p>
        )}
      </section>
      <div className="knowledge-scope">
        <label>
          当前机构
          <select
            aria-label="当前机构"
            value={org}
            disabled={busy || loading}
            onChange={(e) => {
              if (e.target.value === org) return;
              setDetail(undefined);
              setSelected("");
              setTasks([]);
              setProject("");
              setProjects([]);
              setOrg(e.target.value);
            }}
          >
            {identity.organizations.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          当前项目
          <select
            aria-label="当前项目"
            value={project}
            disabled={busy || loading || !projects.length}
            onChange={(e) => {
              setDetail(undefined);
              setSelected("");
              setTasks([]);
              setProject(e.target.value);
            }}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {!project ? (
        <p className="empty-state">
          {loading
            ? "正在读取授权项目…"
            : "暂无获授权项目，请先创建项目或联系项目管理员。"}
        </p>
      ) : (
        <>
          {writable ? (
            <section className="workspace-panel">
              <h2>新建研究任务</h2>
              <p className="form-note">
                任务输入和结果仅发起人可见，并持续受项目及原文权限约束。不会自动读取其他项目或访问互联网。单次最多
                20 家公共候选，每家 6 条证据；每份文件前 8
                个片段，覆盖不完整时须人工补充。
              </p>
              <form
                className="catalog-form"
                key={`${org}-${project}`}
                onSubmit={async (e) => {
                  e.preventDefault();
                  const form = e.currentTarget;
                  const data = new FormData(form);
                  setBusy(true);
                  setError("");
                  try {
                    const selectedDocs = data.getAll("document_ids");
                    if (selectedDocs.length > 10)
                      throw new Error("单次最多选择 10 份私有文件。");
                    if (kind === "bp_screening" && !selectedDocs.length)
                      throw new Error(
                        "BP 初筛至少选择一份已完成索引的授权文档。",
                      );
                    if (selectedDocs.length && !data.get("private_consent"))
                      throw new Error(
                        "请确认有权将选中文档发送给已配置模型服务。",
                      );
                    const result = await api<Task>(
                      base,
                      {
                        method: "POST",
                        body: JSON.stringify({
                          kind,
                          idempotency_key: crypto.randomUUID(),
                          question: data.get("question"),
                          company_id: data.get("company") || null,
                          thesis: data.get("thesis") || "",
                          document_ids: data.getAll("document_ids"),
                          allow_private_to_model: !!data.get("private_consent"),
                          filters:
                            kind === "company_discovery"
                              ? {
                                  q: data.get("q") || null,
                                  province: data.get("province") || null,
                                  listing_status:
                                    data.get("listing_status") || null,
                                  limit: 20,
                                }
                              : {},
                        }),
                      },
                      identity.csrf_token,
                    );
                    setSelected(result.id);
                    setTasks(await api<Task[]>(base));
                    setNotice(
                      "任务已排队；后台会检查权限、证据版本与模型预算。",
                    );
                  } catch (e) {
                    fail(e);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <label>
                  工作流
                  <select
                    aria-label="工作流"
                    value={kind}
                    disabled={busy}
                    onChange={(e) => setKind(e.target.value)}
                  >
                    {Object.entries(workflows).map(([id, label]) => (
                      <option key={id} value={id}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  提示词版本
                  <input
                    readOnly
                    value={
                      config?.definitions.find((d) => d.kind === kind)
                        ?.prompt_version || ""
                    }
                  />
                </label>
                {kind !== "company_discovery" ? (
                  <label className="wide">
                    目标企业
                    {["company_profile", "project_match"].includes(kind)
                      ? "（必选）"
                      : "（可选）"}
                    <select
                      name="company"
                      aria-label="目标企业"
                      required={["company_profile", "project_match"].includes(
                        kind,
                      )}
                    >
                      <option value="">请选择公共企业档案</option>
                      {companies.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.canonical_name}
                        </option>
                      ))}
                    </select>
                    <span className="form-note">
                      展示最多 100 家已登记档案；缺少档案请先维护公共企业库。
                    </span>
                  </label>
                ) : (
                  <>
                    <label>
                      企业名称关键词
                      <input name="q" maxLength={300} />
                    </label>
                    <label>
                      省份
                      <input name="province" maxLength={80} />
                    </label>
                    <label>
                      上市状态
                      <select name="listing_status">
                        <option value="">不限</option>
                        <option value="unlisted">未上市</option>
                        <option value="listed">已上市</option>
                        <option value="unknown">未知</option>
                      </select>
                    </label>
                  </>
                )}
                <label className="wide">
                  研究问题
                  <textarea
                    name="question"
                    rows={3}
                    minLength={3}
                    maxLength={2000}
                    required
                    placeholder="例如：哪些客户验证与商业化假设缺少证据？"
                  />
                </label>
                {kind === "project_match" && (
                  <label className="wide">
                    机构投资 Thesis
                    <textarea
                      name="thesis"
                      rows={4}
                      required
                      maxLength={3000}
                      placeholder="明确行业、技术路线、地域、阶段、排除条件及待验证假设。"
                    />
                  </label>
                )}
                {kind !== "company_discovery" && (
                  <fieldset className="wide agent-document-options">
                    <legend>
                      明确选择私有材料
                      {kind === "bp_screening"
                        ? "（BP 初筛至少一份）"
                        : "（可选）"}
                    </legend>
                    {!documents.length ? (
                      <p className="form-note">
                        当前项目没有已完成索引且获授权的文档，请先到私有知识库上传。
                      </p>
                    ) : (
                      documents.map((d) => (
                        <label className="checkbox-label" key={d.id}>
                          <input
                            type="checkbox"
                            name="document_ids"
                            value={d.id}
                          />
                          {d.title} · v{d.current_version}
                        </label>
                      ))
                    )}
                    <label className="checkbox-label">
                      <input type="checkbox" name="private_consent" />
                      我有权将明确选中的私有材料发送给上述已配置模型服务。未勾选时不会提交所选文件。
                    </label>
                  </fieldset>
                )}
                <p className="wide form-note">
                  模型输出仅为待人工审核草案。引用存在不代表结论正确；数字、冲突与来源须人工核验。取消任务不能保证服务商停止计费。
                </p>
                <button
                  className="primary"
                  disabled={busy || !config?.configured || loading}
                >
                  {busy
                    ? "正在提交…"
                    : config?.configured
                      ? "提交研究任务"
                      : "模型未配置，暂不可提交"}
                </button>
              </form>
            </section>
          ) : (
            <p className="empty-state">
              当前项目为只读，不能创建、重试或取消研究任务。
            </p>
          )}
          <section className="workspace-panel">
            <div className="section-heading">
              <h2>
                我的任务 <span className="count">{tasks.length}</span>
              </h2>
              <button
                className="refresh"
                disabled={busy || loading}
                onClick={() => api<Task[]>(base).then(setTasks).catch(fail)}
              >
                刷新任务
              </button>
            </div>
            <p className="form-note">
              最多显示最近 50 项，API
              支持分页。任务最多执行三次，自动恢复过期租约也计入次数。
            </p>
            {!tasks.length ? (
              <p className="empty-state">暂无研究任务。</p>
            ) : (
              tasks.map((task) => (
                <article
                  className="private-doc-row agent-task-row"
                  key={task.id}
                >
                  <div>
                    <strong>{workflows[task.kind]}</strong>
                    <p>
                      {taskStates[task.status]} · 第 {task.attempts} 次执行 ·{" "}
                      {new Date(task.created_at).toLocaleString("zh-CN")}
                    </p>
                    <small>
                      {task.prompt_version} · {task.id}
                    </small>
                    {task.error_code && (
                      <p className="error-message">
                        {agentErrors[task.error_code] ||
                          "任务执行失败，请核查配置或材料后重试。"}
                      </p>
                    )}
                  </div>
                  <div className="catalog-actions">
                    <button
                      className="refresh"
                      onClick={() => {
                        setError("");
                        setDetail(undefined);
                        setSelected(task.id);
                        if (selected === task.id)
                          api<TaskDetail>(`${base}/${task.id}`)
                            .then(setDetail)
                            .catch(fail);
                      }}
                    >
                      查看任务
                    </button>
                    {writable &&
                      task.status === "failed" &&
                      task.attempts < 3 && (
                        <button
                          className="refresh"
                          disabled={busy}
                          onClick={() => action(task, "retry")}
                        >
                          重试任务
                        </button>
                      )}
                    {writable && activeStates.includes(task.status) && (
                      <button
                        className="refresh danger"
                        disabled={busy}
                        onClick={() => action(task, "cancel")}
                      >
                        取消任务
                      </button>
                    )}
                  </div>
                </article>
              ))
            )}
          </section>
          {selected && detail && (
            <section className="workspace-panel agent-detail">
              <div className="section-heading">
                <h2>{workflows[detail.kind]} · 任务详情</h2>
                <button
                  className="inline-button"
                  onClick={() => {
                    setSelected("");
                    setDetail(undefined);
                  }}
                >
                  关闭详情
                </button>
              </div>
              <p>
                {taskStates[detail.status]} · {detail.prompt_version}
              </p>
              <p className="form-note">{detail.review_notice}</p>
              <p className="form-note">提示词校验摘要 {detail.prompt_hash}</p>
              <h3>研究问题</h3>
              <p className="agent-text">{detail.inputs.question}</p>
              {detail.inputs.thesis && (
                <>
                  <h3>投资 Thesis</h3>
                  <p className="agent-text">{detail.inputs.thesis}</p>
                </>
              )}
              {detail.result && (
                <>
                  <h3>分析摘要</h3>
                  {claim(detail.result.summary, 0)}
                  {detail.result.sections.map((section) => (
                    <div key={section.key}>
                      <h3>{sectionLabels[section.key] || section.key}</h3>
                      {section.claims.map(claim)}
                    </div>
                  ))}
                  <h3>尽调问题</h3>
                  {detail.result.questions.map((q, i) => (
                    <article className="citation-card" key={i}>
                      <strong>
                        {i + 1}. {q.question}
                      </strong>
                      <p>
                        优先级：
                        {
                          (
                            { high: "高", medium: "中", low: "低" } as Record<
                              string,
                              string
                            >
                          )[q.priority]
                        }
                      </p>
                      <p>原因：{q.reason}</p>
                      <p>风险：{q.risk}</p>
                      <p>已知信息：{q.known_information}</p>
                      <p>缺失证据：{q.missing_evidence}</p>
                      <p>验证方式：{q.verification_method}</p>
                      <div className="agent-reference-links">
                        {q.evidence_ids.map((id) => (
                          <a key={id} href={`#${name(id)}`}>
                            引用 {id.slice(-8)} ↗
                          </a>
                        ))}
                      </div>
                    </article>
                  ))}
                  <h3>未知与数据缺口</h3>
                  <ul>
                    {detail.result.unknowns.map((text, i) => (
                      <li key={i}>{text}</li>
                    ))}
                  </ul>
                  <h3>局限性</h3>
                  <ul>
                    {detail.result.limitations.map((text, i) => (
                      <li key={i}>{text}</li>
                    ))}
                  </ul>
                </>
              )}
              <h3>授权证据 · {detail.evidence.length}</h3>
              <p className="form-note">
                服务器重新校验引用及原文权限。证据只是来源材料；模型的事实与数字正确性仍需人工核查。
              </p>
              {detail.evidence.map((e) => (
                <article className="citation-card" key={e.id} id={name(e.id)}>
                  <strong>{e.id}</strong>
                  <p className="form-note">
                    {e.kind === "private_chunk"
                      ? `私有文档 · v${e.version_number}`
                      : "公共企业资料"}
                    {e.page_number ? ` · 第 ${e.page_number} 页` : ""}
                    {e.section_name ? ` · ${e.section_name}` : ""}
                  </p>
                  <blockquote>{e.excerpt}</blockquote>
                  {e.document_id ? (
                    <Link
                      className="back-link"
                      href={`/knowledge?organization=${org}&project=${e.project_id}&document=${e.document_id}&version=${e.version_number}`}
                    >
                      回到授权文档版本 →
                    </Link>
                  ) : (
                    e.company_id && (
                      <Link
                        className="back-link"
                        href={`/companies/${e.company_id}`}
                      >
                        查看公共企业档案 →
                      </Link>
                    )
                  )}
                </article>
              ))}
              <h3>模型调用记录</h3>
              {!detail.calls.length ? (
                <p className="form-note">
                  尚未调用模型；不伪造 token 或费用数据。
                </p>
              ) : (
                detail.calls.map((call) => (
                  <article className="citation-card" key={call.attempt}>
                    <strong>
                      第 {call.attempt} 次 · {call.provider} / {call.model}
                    </strong>
                    <p>
                      状态：{call.status} · 耗时 {call.latency_ms ?? "未知"} ms
                    </p>
                    <p>
                      输入 {call.input_tokens ?? "未知"} / 输出{" "}
                      {call.output_tokens ?? "未知"} tokens · 预算预留{" "}
                      {call.reserved_tokens}
                    </p>
                    <p>
                      估算费用（USD）：
                      {call.estimated_cost_micros === null
                        ? "未知（未配置费率或缺少用量）"
                        : (call.estimated_cost_micros / 1000000).toFixed(6)}
                    </p>
                    {call.error_code && (
                      <p>{agentErrors[call.error_code] || "执行未成功"}</p>
                    )}
                  </article>
                ))
              )}
            </section>
          )}
        </>
      )}
    </>
  );
}
