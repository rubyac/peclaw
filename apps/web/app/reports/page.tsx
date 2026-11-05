"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CatalogShell } from "@/components/catalog-shell";
import { api, ApiError, type Identity, type Project } from "@/lib/api";
import { type PrivateDocument, type EligibleMember } from "@/lib/knowledge";
import { workflows, sectionLabels, type Claim, type Task } from "@/lib/agents";
import {
  reportStates,
  verificationStates,
  metricTypes,
  reportSectionLabels,
  type ReportBody,
  type ReportMeta,
  type ReportDetail,
  type Templates,
} from "@/lib/reports";

export default function Page() {
  return (
    <CatalogShell title="报告与审核">
      {(identity) => <Workbench identity={identity} />}
    </CatalogShell>
  );
}
function Workbench({ identity }: { identity: Identity }) {
  const router = useRouter();
  const [org, setOrg] = useState(identity.organizations[0]?.id || "");
  const [project, setProject] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [documents, setDocuments] = useState<PrivateDocument[]>([]);
  const [companies, setCompanies] = useState<
    { id: string; canonical_name: string }[]
  >([]);
  const [members, setMembers] = useState<EligibleMember[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [rows, setRows] = useState<ReportMeta[]>([]);
  const [templates, setTemplates] = useState<Templates>();
  const [template, setTemplate] = useState("bp_screening");
  const [sourceMode, setSourceMode] = useState("manual");
  const [detail, setDetail] = useState<ReportDetail>();
  const [snapshot, setSnapshot] = useState<{
    title: string;
    revision: number;
    content: ReportBody;
    metrics: ReportDetail["metrics"];
  }>();
  const [draft, setDraft] = useState<ReportBody>();
  const [metricEdit, setMetricEdit] = useState("");
  const [decision, setDecision] = useState("approve");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const writable = !!projects.find((p) => p.id === project)?.can_write;
  const base = `organizations/${org}/projects/${project}/reports`;
  const selectedMetric = detail?.metrics.find((m) => m.id === metricEdit);
  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else if (e instanceof Error && e.name !== "AbortError")
        setError(e.message);
    },
    [router],
  );
  function clear() {
    setDetail(undefined);
    setSnapshot(undefined);
    setDraft(undefined);
    setMetricEdit("");
    setRows([]);
    setError("");
    setNotice("");
  }
  function show(data: ReportDetail) {
    setDetail(data);
    setSnapshot(undefined);
    setDraft(structuredClone(data.content));
    setMetricEdit("");
  }
  useEffect(() => {
    const c = new AbortController();
    Promise.all([
      api<Templates>("reports/templates", { signal: c.signal }),
      api<{ items: { id: string; canonical_name: string }[] }>(
        "companies?limit=100",
        { signal: c.signal },
      ),
    ])
      .then(([t, cs]) => {
        setTemplates(t);
        setCompanies(cs.items);
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
    clear();
    api<Project[]>(`organizations/${org}/projects`, { signal: c.signal })
      .then((data) => {
        setProjects(data);
        setProject(data[0]?.id || "");
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
    setLoading(true);
    clear();
    setMembers([]);
    setDocuments([]);
    setTasks([]);
    Promise.all([
      api<ReportMeta[]>(base, { signal: c.signal }),
      api<PrivateDocument[]>(
        `organizations/${org}/projects/${project}/documents`,
        { signal: c.signal },
      ),
      api<Task[]>(`organizations/${org}/projects/${project}/agent-tasks`, {
        signal: c.signal,
      }),
    ])
      .then(([rs, ds, ts]) => {
        setRows(rs);
        setDocuments(
          ds.filter((d) => d.can_read && d.current?.status === "indexed"),
        );
        setTasks(ts.filter((t) => t.status === "review_required"));
      })
      .catch(fail)
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    if (writable)
      api<EligibleMember[]>(
        `organizations/${org}/projects/${project}/knowledge-members`,
        { signal: c.signal },
      )
        .then(setMembers)
        .catch(fail);
    return () => c.abort();
  }, [base, org, project, writable, fail]);
  async function refresh() {
    setBusy(true);
    setError("");
    try {
      if (detail) show(await api<ReportDetail>(`${base}/${detail.id}`));
      setRows(await api<ReportMeta[]>(base));
    } catch (e) {
      setDetail(undefined);
      setDraft(undefined);
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function mutate(suffix: string, values: object, method = "POST") {
    if (!detail) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      show(
        await api<ReportDetail>(
          `${base}/${detail.id}${suffix}`,
          {
            method,
            body: JSON.stringify({
              expected_revision: detail.revision,
              ...values,
            }),
          },
          identity.csrf_token,
        ),
      );
      setRows(await api<ReportMeta[]>(base));
      setNotice("操作已保存；批准与导出始终绑定当前修订和有效来源。");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function open(row: ReportMeta) {
    setBusy(true);
    setDetail(undefined);
    setSnapshot(undefined);
    setDraft(undefined);
    setError("");
    try {
      show(await api<ReportDetail>(`${base}/${row.id}`));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  function updateClaim(
    section: number | null,
    index: number,
    key: string,
    value: string | string[],
  ) {
    setDraft((previous) => {
      if (!previous) return previous;
      const next = structuredClone(previous);
      const target =
        section === null ? next.summary : next.sections[section].claims[index];
      Object.assign(target, { [key]: value });
      return next;
    });
  }
  function claimEditor(
    claim: Claim,
    label: string,
    section: number | null,
    index: number,
  ) {
    return (
      <fieldset className="report-claim-editor" key={`${section}-${index}`}>
        <legend>{label}</legend>
        <label>
          陈述内容
          <textarea
            aria-label={`${label}内容`}
            rows={3}
            maxLength={1600}
            minLength={1}
            required
            value={claim.text}
            onChange={(e) =>
              updateClaim(section, index, "text", e.target.value)
            }
          />
        </label>
        <label>
          陈述分类
          <select
            aria-label={`${label}分类`}
            value={claim.classification}
            onChange={(e) =>
              updateClaim(section, index, "classification", e.target.value)
            }
          >
            <option value="unknown">未知</option>
            <option value="unverified">待核验</option>
            <option value="inference">推断</option>
            <option value="fact">事实（需独立审核）</option>
            <option value="conflicting">来源冲突</option>
          </select>
        </label>
        <label>
          引用证据（可多选）
          <select
            aria-label={`${label}引用`}
            multiple
            value={claim.evidence_ids}
            onChange={(e) =>
              updateClaim(
                section,
                index,
                "evidence_ids",
                Array.from(e.target.selectedOptions, (o) => o.value),
              )
            }
          >
            {detail?.quality.evidence.map((source) => (
              <option key={source.id} value={source.id}>
                {source.kind === "private_chunk" ? "项目原文" : "公共资料"} ·{" "}
                {source.excerpt.slice(0, 70)}
              </option>
            ))}
          </select>
        </label>
      </fieldset>
    );
  }
  async function download(form: HTMLFormElement) {
    if (!detail) return;
    const data = new FormData(form);
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/${base}/${detail.id}/export`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": identity.csrf_token,
        },
        body: JSON.stringify({
          expected_revision: detail.revision,
          mode: data.get("mode"),
          format: data.get("format"),
          idempotency_key: crypto.randomUUID(),
        }),
      });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error?.message || "导出失败");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download =
        response.headers
          .get("Content-Disposition")
          ?.match(/filename="([^"]+)"/)?.[1] || `report.${data.get("format")}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      show(await api<ReportDetail>(`${base}/${detail.id}`));
      setRows(await api<ReportMeta[]>(base));
      setNotice(
        "文件已生成并记录导出摘要。草稿不代表已审核，已下载副本无法由应用追回。",
      );
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="workspace-heading">
        <div>
          <div className="eyebrow">REVIEW BEFORE YOU EXPORT</div>
          <h1>报告与审核</h1>
          <p>让每个关键数字回到原文，让正式导出经过独立审核。</p>
        </div>
        <Link className="refresh" href="/agents">
          研究工作流 →
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
      <div className="knowledge-scope">
        <label>
          当前机构
          <select
            aria-label="当前机构"
            value={org}
            disabled={busy || loading}
            onChange={(e) => {
              if (e.target.value === org) return;
              clear();
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
              clear();
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
            : "暂无获授权项目，请先创建项目或联系管理员。"}
        </p>
      ) : (
        <>
          {writable && (
            <section className="workspace-panel">
              <h2>创建报告草稿</h2>
              <p className="form-note">
                人工模板不调用生成模型；从 Agent
                转入也只是草稿。报告仅作者与明确指定的审核人可见，两人都须拥有所引原文权限。
              </p>
              <form
                className="catalog-form"
                key={`${org}-${project}`}
                onSubmit={async (e) => {
                  e.preventDefault();
                  const data = new FormData(e.currentTarget);
                  setBusy(true);
                  setError("");
                  try {
                    const created = await api<ReportDetail>(
                      base,
                      {
                        method: "POST",
                        body: JSON.stringify({
                          title: data.get("title"),
                          template,
                          idempotency_key: crypto.randomUUID(),
                          source_task_id:
                            sourceMode === "task"
                              ? data.get("source_task_id")
                              : null,
                          company_id:
                            sourceMode === "manual"
                              ? data.get("company_id") || null
                              : null,
                          document_ids:
                            sourceMode === "manual"
                              ? data.getAll("document_ids")
                              : [],
                        }),
                      },
                      identity.csrf_token,
                    );
                    show(created);
                    setRows(await api<ReportMeta[]>(base));
                    setNotice(
                      "报告草稿已创建，请填写正文、登记数字并指定独立审核人。",
                    );
                  } catch (e) {
                    fail(e);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <label>
                  报告标题
                  <input name="title" maxLength={200} required />
                </label>
                <label>
                  创建方式
                  <select
                    aria-label="创建方式"
                    value={sourceMode}
                    onChange={(e) => setSourceMode(e.target.value)}
                  >
                    <option value="manual">人工填写模板（无需模型）</option>
                    <option value="task">从本人已完成的 Agent 草案转入</option>
                  </select>
                </label>
                <label>
                  报告模板
                  <select
                    aria-label="报告模板"
                    value={template}
                    disabled={sourceMode === "task"}
                    onChange={(e) => setTemplate(e.target.value)}
                  >
                    {templates?.templates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {workflows[t.id]}报告
                      </option>
                    ))}
                  </select>
                </label>
                {sourceMode === "task" ? (
                  <label>
                    已完成的研究草案
                    <select
                      aria-label="已完成的研究草案"
                      name="source_task_id"
                      required
                      onChange={(e) => {
                        const task = tasks.find((t) => t.id === e.target.value);
                        if (task) setTemplate(task.kind);
                      }}
                    >
                      <option value="">请选择</option>
                      {tasks.map((t) => (
                        <option key={t.id} value={t.id}>
                          {workflows[t.kind]} · {t.id.slice(-8)}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <>
                    <label>
                      公共企业（可选）
                      <select aria-label="公共企业" name="company_id">
                        <option value="">不选择公共企业</option>
                        {companies.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.canonical_name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <fieldset className="wide agent-document-options">
                      <legend>授权私有材料（最多十份，不外发模型）</legend>
                      {!documents.length ? (
                        <p className="form-note">
                          当前没有可选的已索引文档，也可先创建未知信息模板。
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
                    </fieldset>
                  </>
                )}
                <button className="primary" disabled={busy || loading}>
                  创建报告草稿
                </button>
              </form>
            </section>
          )}
          <section className="workspace-panel">
            <div className="section-heading">
              <h2>
                我的报告与待审报告 <span className="count">{rows.length}</span>
              </h2>
              <button
                className="refresh"
                disabled={busy || loading}
                onClick={refresh}
              >
                刷新报告
              </button>
            </div>
            <p className="form-note">
              列表仅显示有限元数据；标题、正文与附件每次打开都重新授权。最多展示最近五十项。
            </p>
            {!rows.length ? (
              <p className="empty-state">
                暂无本人创建或获明确审核授权的报告。
              </p>
            ) : (
              rows.map((row) => (
                <article className="private-doc-row" key={row.id}>
                  <div>
                    <strong>
                      {workflows[row.template_version.split("@")[0]]}报告 ·{" "}
                      {row.id.slice(-8)}
                    </strong>
                    <p>
                      {reportStates[row.status]} · 修订 {row.revision} ·{" "}
                      {row.can_edit ? "我是作者" : "我是指定审核人"}
                    </p>
                  </div>
                  <button
                    className="refresh"
                    disabled={busy}
                    onClick={() => open(row)}
                  >
                    打开报告
                  </button>
                </article>
              ))
            )}
          </section>
          {detail && draft && (
            <>
              <section className="workspace-panel report-detail">
                <div className="section-heading">
                  <h2>{detail.title}</h2>
                  <button
                    className="inline-button"
                    onClick={() => {
                      setDetail(undefined);
                      setDraft(undefined);
                    }}
                  >
                    关闭报告
                  </button>
                </div>
                <p>
                  {reportStates[detail.status]} · 修订 {detail.revision} ·{" "}
                  {detail.template_version}
                </p>
                <p className="form-note">
                  数字与来源规则只做机械检查，不能证明财务真实性、语义蕴含或投资结论正确。更改报告、数字或审核人会撤销已有批准。
                </p>
                <section className="report-quality" aria-label="报告质量闸">
                  <h3>
                    {detail.quality.passed
                      ? "机械质量检查通过，仍需独立审核"
                      : "质量闸未通过"}
                  </h3>
                  {detail.quality.issues.map((issue, i) => (
                    <p className="error-message" key={i}>
                      {issue.message}
                    </p>
                  ))}
                  {detail.quality.limitations.map((text, i) => (
                    <p className="form-note" key={i}>
                      {text}
                    </p>
                  ))}
                </section>
                {detail.can_edit && writable ? (
                  <details>
                    <summary className="form-section-title">
                      编辑报告正文
                    </summary>
                    <form
                      className="report-editor"
                      onSubmit={(e) => {
                        e.preventDefault();
                        const data = new FormData(e.currentTarget);
                        mutate(
                          "",
                          { title: data.get("title"), content: draft },
                          "PUT",
                        );
                      }}
                    >
                      <label>
                        修改报告标题
                        <input
                          name="title"
                          required
                          maxLength={200}
                          defaultValue={detail.title}
                          key={detail.title}
                        />
                      </label>
                      {claimEditor(draft.summary, "摘要", null, 0)}
                      {draft.sections.map((section, i) => (
                        <div key={section.key}>
                          <h3>
                            {reportSectionLabels[section.key] ||
                              sectionLabels[section.key] ||
                              section.key}
                          </h3>
                          {section.claims.map((c, j) =>
                            claimEditor(
                              c,
                              `${reportSectionLabels[section.key] || sectionLabels[section.key] || section.key}陈述${j + 1}`,
                              i,
                              j,
                            ),
                          )}
                        </div>
                      ))}
                      <label>
                        未知与数据缺口（每行一项）
                        <textarea
                          rows={3}
                          value={draft.unknowns.join("\n")}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              unknowns: e.target.value.split("\n"),
                            })
                          }
                        />
                      </label>
                      <label>
                        局限性（每行一项）
                        <textarea
                          rows={3}
                          value={draft.limitations.join("\n")}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              limitations: e.target.value.split("\n"),
                            })
                          }
                        />
                      </label>
                      {draft.questions.map((q, i) => (
                        <details key={i}>
                          <summary>修改尽调问题：{q.question}</summary>
                          {(
                            [
                              "question",
                              "reason",
                              "risk",
                              "known_information",
                              "missing_evidence",
                              "verification_method",
                            ] as const
                          ).map((key, index) => (
                            <label key={key}>
                              {
                                [
                                  "问题",
                                  "原因",
                                  "风险",
                                  "已知信息",
                                  "缺失证据",
                                  "验证方式",
                                ][index]
                              }
                              <textarea
                                rows={2}
                                maxLength={800}
                                value={q[key]}
                                onChange={(e) => {
                                  const next = structuredClone(draft);
                                  next.questions[i][key] = e.target.value;
                                  setDraft(next);
                                }}
                              />
                            </label>
                          ))}
                          <button
                            type="button"
                            className="inline-button danger"
                            onClick={() =>
                              setDraft({
                                ...draft,
                                questions: draft.questions.filter(
                                  (_, j) => i !== j,
                                ),
                              })
                            }
                          >
                            删除此尽调问题
                          </button>
                        </details>
                      ))}
                      <button className="primary" disabled={busy}>
                        保存正文并撤销旧批准
                      </button>
                    </form>
                  </details>
                ) : (
                  <div className="report-preview">
                    <h3>摘要</h3>
                    <p>{detail.content.summary.text}</p>
                    {detail.content.sections.map((section) => (
                      <div key={section.key}>
                        <h3>
                          {reportSectionLabels[section.key] ||
                            sectionLabels[section.key]}
                        </h3>
                        {section.claims.map((c, i) => (
                          <article className="agent-claim" key={i}>
                            <span className="claim-label">
                              {
                                (
                                  {
                                    fact: "事实（需审核）",
                                    inference: "推断",
                                    unverified: "待核验",
                                    unknown: "未知",
                                    conflicting: "来源冲突",
                                  } as Record<string, string>
                                )[c.classification]
                              }
                            </span>
                            <p>{c.text}</p>
                            <small>
                              引用：{c.evidence_ids.join("；") || "无"}
                            </small>
                          </article>
                        ))}
                      </div>
                    ))}
                    <h3>未知与局限性</h3>
                    {[
                      ...detail.content.unknowns,
                      ...detail.content.limitations,
                    ].map((text, i) => (
                      <p key={i}>{text}</p>
                    ))}
                  </div>
                )}
              </section>
              <section className="workspace-panel">
                <h2>关键数字登记与核验</h2>
                <p className="form-note">
                  保存精确十进制数字，不静默换算单位或币种。原文必须包含数值、单位、币种与期间；非适用项不填数字，由审核人明确标记。不在正文中保留未核验数值。
                </p>
                {detail.can_edit && writable && (
                  <form
                    className="catalog-form"
                    key={`${detail.id}-${metricEdit || "new"}`}
                    onSubmit={(e) => {
                      e.preventDefault();
                      const data = new FormData(e.currentTarget);
                      mutate(
                        metricEdit ? `/metrics/${metricEdit}` : "/metrics",
                        {
                          metric_name: data.get("metric_name"),
                          metric_type: data.get("metric_type"),
                          metric_value: data.get("metric_value") || null,
                          unit: data.get("unit"),
                          currency: data.get("currency") || null,
                          period: data.get("period"),
                          evidence_id: data.get("evidence_id") || null,
                          source_quote: data.get("source_quote") || "",
                          notes: data.get("notes") || "",
                        },
                        metricEdit ? "PUT" : "POST",
                      );
                    }}
                  >
                    <label>
                      数字名称
                      <input
                        name="metric_name"
                        required
                        maxLength={200}
                        defaultValue={selectedMetric?.metric_name}
                      />
                    </label>
                    <label>
                      数字类型
                      <select
                        name="metric_type"
                        aria-label="数字类型"
                        defaultValue={selectedMetric?.metric_type || "revenue"}
                      >
                        {Object.entries(metricTypes).map(([key, label]) => (
                          <option value={key} key={key}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      数值（不适用时留空）
                      <input
                        name="metric_value"
                        maxLength={100}
                        inputMode="decimal"
                        defaultValue={selectedMetric?.metric_value || ""}
                      />
                    </label>
                    <label>
                      单位
                      <input
                        name="unit"
                        required
                        maxLength={40}
                        placeholder="例如：亿元、台、%"
                        defaultValue={selectedMetric?.unit}
                      />
                    </label>
                    <label>
                      币种
                      <select
                        name="currency"
                        aria-label="币种"
                        defaultValue={selectedMetric?.currency || ""}
                      >
                        <option value="">不适用</option>
                        {["CNY", "USD", "EUR", "HKD", "JPY", "other"].map(
                          (v) => (
                            <option key={v}>{v}</option>
                          ),
                        )}
                      </select>
                    </label>
                    <label>
                      期间
                      <input
                        name="period"
                        required
                        maxLength={100}
                        placeholder="与引用原文一致，例如：2025年"
                        defaultValue={selectedMetric?.period}
                      />
                    </label>
                    <label className="wide">
                      数字来源
                      <select
                        name="evidence_id"
                        aria-label="数字来源"
                        defaultValue={selectedMetric?.evidence_id || ""}
                      >
                        <option value="">不适用或暂未提供</option>
                        {detail.quality.evidence.map((e) => (
                          <option key={e.id} value={e.id}>
                            {e.excerpt.slice(0, 100)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="wide">
                      精确引用原文
                      <textarea
                        name="source_quote"
                        rows={3}
                        maxLength={2000}
                        defaultValue={selectedMetric?.source_quote}
                      />
                    </label>
                    <label className="wide">
                      登记备注
                      <textarea
                        name="notes"
                        maxLength={2000}
                        defaultValue={selectedMetric?.notes}
                      />
                    </label>
                    <div className="catalog-actions">
                      <button className="primary" disabled={busy}>
                        {metricEdit ? "保存数字修改并重置核验" : "登记关键数字"}
                      </button>
                      {metricEdit && (
                        <button
                          className="refresh"
                          type="button"
                          onClick={() => setMetricEdit("")}
                        >
                          取消修改
                        </button>
                      )}
                    </div>
                  </form>
                )}
                {!detail.metrics.length ? (
                  <p className="empty-state">
                    尚未登记关键数字；正文中的数字仍会触发检查，不能通过空登记表绕过质量闸。
                  </p>
                ) : (
                  detail.metrics.map((m) => (
                    <article className="citation-card report-metric" key={m.id}>
                      <h3>
                        {m.metric_name} ·{" "}
                        {verificationStates[m.verification_status]}
                      </h3>
                      <p>
                        {m.metric_value ?? "未提供／不适用"} {m.unit} ·{" "}
                        {m.currency || "不适用"} · {m.period}
                      </p>
                      <blockquote>{m.source_quote || "暂无原文"}</blockquote>
                      <p>登记备注：{m.notes || "无"}</p>
                      <p>核验备注：{m.review_notes || "尚未核验"}</p>
                      {detail.can_edit && writable && (
                        <div className="catalog-actions">
                          <button
                            className="refresh"
                            onClick={() => setMetricEdit(m.id)}
                          >
                            修改数字
                          </button>
                          <button
                            className="refresh danger"
                            disabled={busy}
                            onClick={() =>
                              mutate(`/metrics/${m.id}`, {}, "DELETE")
                            }
                          >
                            删除数字登记
                          </button>
                        </div>
                      )}
                      {detail.can_review &&
                        writable &&
                        detail.status === "review_required" && (
                          <form
                            className="catalog-form"
                            onSubmit={(e) => {
                              e.preventDefault();
                              const data = new FormData(e.currentTarget);
                              mutate(`/metrics/${m.id}/review`, {
                                status: data.get("status"),
                                notes: data.get("notes"),
                              });
                            }}
                          >
                            <label>
                              数字核验结论
                              <select
                                name="status"
                                aria-label={`${m.metric_name}核验结论`}
                              >
                                <option
                                  value="verified"
                                  disabled={m.metric_value === null}
                                >
                                  已核验
                                </option>
                                <option value="conflicting">存在冲突</option>
                                <option value="rejected">拒绝</option>
                                <option
                                  value="not_applicable"
                                  disabled={m.metric_value !== null}
                                >
                                  不适用
                                </option>
                              </select>
                            </label>
                            <label>
                              数字核验说明
                              <textarea
                                name="notes"
                                required
                                minLength={5}
                                maxLength={2000}
                              />
                            </label>
                            <button className="primary" disabled={busy}>
                              保存数字核验
                            </button>
                          </form>
                        )}
                    </article>
                  ))
                )}
              </section>
              <section className="workspace-panel">
                <h2>独立审核</h2>
                <p className="form-note">
                  作者不能批准自己的报告；审核人须具备项目编辑及全部引用的读取权限。换人会重置数字核验，改动会撤销批准。
                </p>
                {detail.can_edit && writable && (
                  <>
                    <form
                      className="member-form"
                      onSubmit={(e) => {
                        e.preventDefault();
                        const data = new FormData(e.currentTarget);
                        mutate(
                          "/reviewer",
                          { reviewer_id: data.get("reviewer") },
                          "PUT",
                        );
                      }}
                    >
                      <label>
                        指定独立审核人
                        <select
                          aria-label="指定独立审核人"
                          name="reviewer"
                          required
                          defaultValue={detail.reviewer_id || ""}
                          key={detail.reviewer_id || "none"}
                        >
                          <option value="">请选择另一位有编辑资格的成员</option>
                          {members
                            .filter(
                              (m) =>
                                m.can_edit && m.user_id !== identity.user.id,
                            )
                            .map((m) => (
                              <option key={m.user_id} value={m.user_id}>
                                {m.full_name} · {m.email}
                              </option>
                            ))}
                        </select>
                      </label>
                      <button className="primary" disabled={busy}>
                        保存审核人
                      </button>
                    </form>
                    <button
                      className="primary"
                      disabled={
                        busy || !detail.reviewer_id || detail.status !== "draft"
                      }
                      onClick={() => mutate("/submit", {})}
                    >
                      提交当前修订审核
                    </button>
                  </>
                )}
                {detail.can_review &&
                  writable &&
                  detail.status === "review_required" && (
                    <form
                      className="report-editor"
                      onSubmit={(e) => {
                        e.preventDefault();
                        const data = new FormData(e.currentTarget);
                        mutate("/review", {
                          decision,
                          notes: data.get("notes"),
                          citations_checked: !!data.get("citations_checked"),
                          facts_checked: !!data.get("facts_checked"),
                          numeric_registry_complete: !!data.get(
                            "numeric_registry_complete",
                          ),
                          conflicts_checked: !!data.get("conflicts_checked"),
                          no_invented_data: !!data.get("no_invented_data"),
                        });
                      }}
                    >
                      <label>
                        审核结论
                        <select
                          aria-label="审核结论"
                          value={decision}
                          onChange={(e) => setDecision(e.target.value)}
                        >
                          <option value="approve">批准正式导出</option>
                          <option value="request_changes">退回修改</option>
                        </select>
                      </label>
                      {(
                        [
                          ["citations_checked", "已逐条核对引用与原文定位"],
                          ["facts_checked", "已核对事实与推断分类"],
                          [
                            "numeric_registry_complete",
                            "已确认关键数字登记完整且逐项核验",
                          ],
                          ["conflicts_checked", "已核对来源冲突并处理缺口"],
                          ["no_invented_data", "已确认没有静默补全或虚构数据"],
                        ] as const
                      ).map(([key, label]) => (
                        <label className="checkbox-label" key={key}>
                          <input
                            type="checkbox"
                            name={key}
                            required={decision === "approve"}
                          />
                          {label}
                        </label>
                      ))}
                      <label>
                        审核意见
                        <textarea
                          name="notes"
                          required
                          minLength={5}
                          maxLength={4000}
                        />
                      </label>
                      <button
                        className="primary"
                        disabled={
                          busy ||
                          (decision === "approve" && !detail.quality.passed)
                        }
                      >
                        {decision === "approve" && !detail.quality.passed
                          ? "质量闸未通过，不能批准"
                          : "保存审核结论"}
                      </button>
                    </form>
                  )}
                <h3>审核记录</h3>
                {!detail.reviews.length ? (
                  <p className="empty-state">暂无审核记录。</p>
                ) : (
                  detail.reviews.map((row) => (
                    <article className="citation-card" key={row.id}>
                      <strong>
                        {(
                          {
                            submit: "提交审核",
                            approve: "批准",
                            request_changes: "退回修改",
                            metric_verified: "数字已核验",
                            metric_conflicting: "数字冲突",
                            metric_rejected: "数字拒绝",
                            metric_not_applicable: "数字不适用",
                          } as Record<string, string>
                        )[row.decision] || row.decision}{" "}
                        · 修订 {row.revision}
                      </strong>
                      <p>{row.notes}</p>
                      <button
                        className="refresh"
                        disabled={busy}
                        onClick={async () => {
                          setBusy(true);
                          setError("");
                          setSnapshot(undefined);
                          try {
                            const result = await api<{
                              snapshot: NonNullable<typeof snapshot>;
                            }>(`${base}/${detail.id}/reviews/${row.id}`);
                            setSnapshot(result.snapshot);
                          } catch (e) {
                            fail(e);
                          } finally {
                            setBusy(false);
                          }
                        }}
                      >
                        查看该次审核快照
                      </button>
                      <small>
                        操作者 {row.reviewer_id} ·{" "}
                        {new Date(row.created_at).toLocaleString("zh-CN")}
                      </small>
                    </article>
                  ))
                )}
              </section>
              {snapshot && (
                <section className="workspace-panel report-review-snapshot">
                  <div className="section-heading">
                    <h2>审核快照 · 修订 {snapshot.revision}</h2>
                    <button
                      className="inline-button"
                      onClick={() => setSnapshot(undefined)}
                    >
                      关闭快照
                    </button>
                  </div>
                  <h3>{snapshot.title}</h3>
                  <p>{snapshot.content.summary.text}</p>
                  {snapshot.content.sections.map((section) => (
                    <div key={section.key}>
                      <h3>
                        {reportSectionLabels[section.key] ||
                          sectionLabels[section.key]}
                      </h3>
                      {section.claims.map((claim, i) => (
                        <p key={i}>{claim.text}</p>
                      ))}
                    </div>
                  ))}
                  <h3>当时的数字登记</h3>
                  {snapshot.metrics.map((metric) => (
                    <p key={metric.id}>
                      {metric.metric_name}：{metric.metric_value ?? "不适用"}{" "}
                      {metric.unit} ·{" "}
                      {verificationStates[metric.verification_status]}
                    </p>
                  ))}
                </section>
              )}
              <section className="workspace-panel">
                <h2>导出报告</h2>
                <p className="form-note">
                  草稿带未审核标记；正式导出要求当前修订已获批准、质量闸通过且审核人与引用权限持续有效。正式文件保留来源定位，不自动附带未经逐项核验的全文片段。已下载副本无法追回。
                </p>
                {writable && (
                  <form
                    className="catalog-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      download(e.currentTarget);
                    }}
                  >
                    <label>
                      导出用途
                      <select name="mode" aria-label="导出用途">
                        <option
                          value="draft"
                          disabled={!templates?.allow_draft_export}
                        >
                          内部草稿（未审核）
                        </option>
                        <option
                          value="formal"
                          disabled={
                            !["approved_for_export", "exported"].includes(
                              detail.status,
                            ) || !detail.quality.passed
                          }
                        >
                          正式报告（当前修订已批准）
                        </option>
                      </select>
                    </label>
                    <label>
                      文件格式
                      <select name="format" aria-label="文件格式">
                        <option value="md">Markdown</option>
                        <option value="docx">Word / DOCX</option>
                      </select>
                    </label>
                    <button className="primary" disabled={busy}>
                      下载报告
                    </button>
                  </form>
                )}
                <h3>导出记录</h3>
                {!detail.exports.length ? (
                  <p className="empty-state">
                    暂无导出记录；文件只在请求中生成，不保存绕过授权的公开附件链接。
                  </p>
                ) : (
                  detail.exports.map((row) => (
                    <p className="form-note" key={row.id}>
                      {row.mode === "formal" ? "正式" : "草稿"} ·{" "}
                      {row.format.toUpperCase()} · 修订 {row.revision} · SHA-256{" "}
                      {row.file_hash}
                    </p>
                  ))
                )}
              </section>
              <section className="workspace-panel">
                <h2>授权证据与原文定位</h2>
                {!detail.quality.evidence.length ? (
                  <p className="empty-state">
                    暂无引用来源，只能保留明确的未知信息，不能编造事实或数字。
                  </p>
                ) : (
                  detail.quality.evidence.map((source) => (
                    <article className="citation-card" key={source.id}>
                      <strong>{source.id}</strong>
                      <blockquote>{source.excerpt}</blockquote>
                      {source.document_id ? (
                        <Link
                          href={`/knowledge?organization=${org}&project=${source.project_id}&document=${source.document_id}&version=${source.version_number}`}
                        >
                          查看授权原文版本 →
                        </Link>
                      ) : (
                        source.company_id && (
                          <Link href={`/companies/${source.company_id}`}>
                            查看公共档案 →
                          </Link>
                        )
                      )}
                    </article>
                  ))
                )}
              </section>
            </>
          )}
        </>
      )}
    </>
  );
}
