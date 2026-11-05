"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CatalogShell } from "@/components/catalog-shell";
import { api, ApiError, type Identity, type Project } from "@/lib/api";
import { type PrivateDocument, type EligibleMember } from "@/lib/knowledge";
import { workflows, sectionLabels, type Task } from "@/lib/agents";
import { type ReportMeta } from "@/lib/reports";
import {
  caseKinds,
  evaluationStates,
  metricLabels,
  displayMetric,
  percent,
  type DatasetMeta,
  type Dataset,
  type DraftCase,
  type RunMeta,
  type RunDetail,
} from "@/lib/evaluation";

export default function Page() {
  return (
    <CatalogShell title="评测与反馈">
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
  const [docs, setDocs] = useState<PrivateDocument[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [reports, setReports] = useState<ReportMeta[]>([]);
  const [members, setMembers] = useState<EligibleMember[]>([]);
  const [rows, setRows] = useState<DatasetMeta[]>([]);
  const [dataset, setDataset] = useState<Dataset>();
  const [run, setRun] = useState<RunDetail>();
  const [runID, setRunID] = useState("");
  const [cases, setCases] = useState<DraftCase[]>([]);
  const [kind, setKind] = useState("knowledge_retrieval");
  const [feedbackCase, setFeedbackCase] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const writable = !!projects.find((p) => p.id === project)?.can_write;
  const base = `organizations/${org}/projects/${project}/evaluations`;
  const selectedCase = run?.records.find((r) => r.case_id === feedbackCase);
  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else if (e instanceof Error && e.name !== "AbortError")
        setError(e.message);
    },
    [router],
  );
  function clear() {
    setDataset(undefined);
    setRun(undefined);
    setRunID("");
    setRows([]);
    setCases([]);
    setFeedbackCase("");
    setError("");
    setNotice("");
  }
  useEffect(() => {
    const c = new AbortController();
    api<{ items: { id: string; canonical_name: string }[] }>(
      "companies?limit=100",
      { signal: c.signal },
    )
      .then((r) => setCompanies(r.items))
      .catch(fail);
    return () => c.abort();
  }, [fail]);
  useEffect(() => {
    if (!org) return;
    const c = new AbortController();
    clear();
    setProjects([]);
    setProject("");
    setLoading(true);
    api<Project[]>(`organizations/${org}/projects`, { signal: c.signal })
      .then((p) => {
        setProjects(p);
        setProject(p[0]?.id || "");
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
    clear();
    setDocs([]);
    setTasks([]);
    setReports([]);
    setMembers([]);
    setLoading(true);
    Promise.all([
      api<DatasetMeta[]>(base, { signal: c.signal }),
      api<PrivateDocument[]>(
        `organizations/${org}/projects/${project}/documents`,
        { signal: c.signal },
      ),
      api<Task[]>(`organizations/${org}/projects/${project}/agent-tasks`, {
        signal: c.signal,
      }),
      api<ReportMeta[]>(`organizations/${org}/projects/${project}/reports`, {
        signal: c.signal,
      }),
    ])
      .then(([ds, files, ts, rs]) => {
        setRows(ds);
        setDocs(
          files.filter((d) => d.can_read && d.current?.status === "indexed"),
        );
        setTasks(ts.filter((t) => t.status === "review_required"));
        setReports(rs);
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
  useEffect(() => {
    setRun(undefined);
    setFeedbackCase("");
    if (!runID) return;
    const c = new AbortController();
    api<RunDetail>(`${base}/runs/${runID}`, { signal: c.signal })
      .then(setRun)
      .catch(fail);
    return () => c.abort();
  }, [runID, base, fail]);
  const pending = !!run && ["queued", "running"].includes(run.status);
  useEffect(() => {
    if (!pending || !runID) return;
    const c = new AbortController();
    const timer = setInterval(async () => {
      try {
        const data = await api<RunDetail>(`${base}/runs/${runID}`, {
          signal: c.signal,
        });
        if (!["queued", "running"].includes(data.status) && dataset)
          setDataset(
            await api<Dataset>(`${base}/${dataset.id}`, { signal: c.signal }),
          );
        setRun(data);
      } catch (e) {
        setRun(undefined);
        fail(e);
      }
    }, 1200);
    return () => {
      clearInterval(timer);
      c.abort();
    };
  }, [pending, runID, base, dataset?.id, fail]);
  useEffect(() => {
    if (!run) return;
    if (
      !run.records.some(
        (r) => r.case_id === feedbackCase && r.status === "measured",
      )
    )
      setFeedbackCase(
        run.records.find((r) => r.status === "measured")?.case_id || "",
      );
  }, [run, feedbackCase]);
  async function revokeReviewer(id: string) {
    setBusy(true);
    setError("");
    try {
      await api(
        `${base}/${id}/reviewer`,
        { method: "DELETE" },
        identity.csrf_token,
      );
      setDataset(undefined);
      setRun(undefined);
      setRunID("");
      setRows(await api<DatasetMeta[]>(base));
      setNotice("已撤销评审访问；历史反馈保留，若需换人请建立新版本。");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function openDataset(id: string) {
    setBusy(true);
    setError("");
    setDataset(undefined);
    setRun(undefined);
    setRunID("");
    try {
      setDataset(await api<Dataset>(`${base}/${id}`));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    if (!dataset) return;
    setBusy(true);
    setError("");
    try {
      const item = await api<RunMeta>(
        `${base}/${dataset.id}/runs`,
        {
          method: "POST",
          body: JSON.stringify({ idempotency_key: crypto.randomUUID() }),
        },
        identity.csrf_token,
      );
      setDataset(await api<Dataset>(`${base}/${dataset.id}`));
      setRunID(item.id);
      setNotice("评测已排队，不会触发新的外部模型调用。");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function action(verb: string) {
    if (!run) return;
    setBusy(true);
    setError("");
    try {
      await api(
        `${base}/runs/${run.id}/${verb}`,
        { method: "POST" },
        identity.csrf_token,
      );
      setRun(await api<RunDetail>(`${base}/runs/${run.id}`));
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
          <div className="eyebrow">MEASURE WHAT YOU CAN VERIFY</div>
          <h1>评测与反馈</h1>
          <p>固定样本、明示分母，把工程回归、模型表现与独立人工判断分开。</p>
        </div>
        <Link className="refresh" href="/reports">
          报告与审核 →
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
      <section className="workspace-panel">
        <h2>评测边界</h2>
        <p className="form-note">
          合成集只验证工程；授权数据需要人工标注。未配置模型或没有完成的模型草案时，对应案例标为未评测。文本精确匹配不等于事实正确，作者自评不进入独立业务指标。
        </p>
        <p className="form-note">
          所有检索只在当前项目授权范围内执行；数据集、结果和反馈仅作者与明确指定评审可见，持续检查原文和来源版本。评测本身不外发原文给新模型。
        </p>
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
              clear();
              setProjects([]);
              setProject("");
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
          {loading ? "正在读取授权项目…" : "暂无获授权项目。"}
        </p>
      ) : (
        <>
          {writable && (
            <>
              <section className="workspace-panel">
                <h2>准备评测案例</h2>
                <form
                  className="catalog-form"
                  key={`${org}-${project}-${kind}`}
                  onSubmit={(e) => {
                    e.preventDefault();
                    setError("");
                    if (cases.length >= 20) {
                      setError("每份数据集最多二十项案例。");
                      return;
                    }
                    const data = new FormData(e.currentTarget);
                    const id = `case_${cases.length + 1}_${crypto.randomUUID().slice(0, 8)}`;
                    let value: DraftCase = { id, kind };
                    if (
                      kind === "company_search" ||
                      kind === "knowledge_retrieval"
                    ) {
                      const pos = data.getAll("positive").map(String);
                      const neg = data.getAll("negative").map(String);
                      if (!pos.length && !neg.length) {
                        setError("至少明确标注一个相关或不相关对象。");
                        return;
                      }
                      if (pos.some((v) => neg.includes(v))) {
                        setError("同一对象不能同时标为相关与不相关。");
                        return;
                      }
                      const key =
                        kind === "company_search"
                          ? "company_id"
                          : "document_id";
                      value = {
                        ...value,
                        k: Number(data.get("k")),
                        relevance: [
                          ...pos.map((id) => ({ [key]: id, grade: 3 })),
                          ...neg.map((id) => ({ [key]: id, grade: 0 })),
                        ],
                      };
                      if (kind === "company_search")
                        value.filters = { q: data.get("query") || null };
                      else {
                        value.query = data.get("query");
                        value.mode = data.get("mode");
                      }
                    } else if (kind === "report_quality")
                      value = {
                        ...value,
                        report_id: data.get("report"),
                        expected_gate_passed: data.get("gate") === "true",
                      };
                    else
                      value = {
                        ...value,
                        task_id: data.get("task") || null,
                        expected_claims: [
                          {
                            text: data.get("expected_text"),
                            classification: data.get("classification"),
                          },
                        ],
                      };
                    setCases([...cases, value]);
                    setNotice("案例已加入待保存数据集；可继续添加或移除。");
                  }}
                >
                  <label>
                    案例类型
                    <select
                      aria-label="案例类型"
                      value={kind}
                      onChange={(e) => setKind(e.target.value)}
                    >
                      {Object.entries(caseKinds).map(([id, label]) => (
                        <option key={id} value={id}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {["company_search", "knowledge_retrieval"].includes(kind) ? (
                    <>
                      <label>
                        返回上限 k
                        <input
                          name="k"
                          type="number"
                          min={1}
                          max={20}
                          defaultValue={10}
                          required
                        />
                      </label>
                      <label className="wide">
                        查询或企业名称关键词
                        <input
                          name="query"
                          required={kind === "knowledge_retrieval"}
                          maxLength={500}
                        />
                      </label>
                      {kind === "knowledge_retrieval" && (
                        <label>
                          检索方式
                          <select name="mode" aria-label="检索方式">
                            <option value="keyword">关键词</option>
                            <option value="hybrid">关键词与本地语义</option>
                            <option value="semantic">本地语义</option>
                          </select>
                        </label>
                      )}
                      {["positive", "negative"].map((key, index) => (
                        <label key={key}>
                          {index ? "明确不相关" : "明确相关"}（可多选）
                          <select
                            multiple
                            name={key}
                            aria-label={index ? "明确不相关" : "明确相关"}
                          >
                            {kind === "company_search"
                              ? companies.map((c) => (
                                  <option key={c.id} value={c.id}>
                                    {c.canonical_name}
                                  </option>
                                ))
                              : docs.map((d) => (
                                  <option key={d.id} value={d.id}>
                                    {d.title}
                                  </option>
                                ))}
                          </select>
                        </label>
                      ))}
                      <p className="wide form-note">
                        未选对象是未标注，不会擅自按不相关计算。P@k 按请求 k
                        为分母，未返回位置不算命中；覆盖不足时完整 P@k／NDCG
                        显示未知。
                      </p>
                    </>
                  ) : kind === "report_quality" ? (
                    <>
                      <label>
                        已授权报告
                        <select name="report" aria-label="已授权报告" required>
                          <option value="">请选择</option>
                          {reports.map((r) => (
                            <option key={r.id} value={r.id}>
                              {workflows[r.template_version.split("@")[0]]} ·{" "}
                              {r.id.slice(-8)}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        预期机械质量闸
                        <select name="gate" aria-label="预期机械质量闸">
                          <option value="false">应被机械质量闸阻止</option>
                          <option value="true">应通过机械检查</option>
                        </select>
                      </label>
                      <p className="wide form-note">
                        这只核对机械质量闸，不代表已获正式导出批准。
                      </p>
                    </>
                  ) : (
                    <>
                      <label>
                        已完成模型草案（可空）
                        <select name="task" aria-label="已完成模型草案">
                          <option value="">暂缺模型结果，列为未评测</option>
                          {tasks
                            .filter(
                              (t) =>
                                kind !== "bp_screening" ||
                                t.kind === "bp_screening",
                            )
                            .map((t) => (
                              <option key={t.id} value={t.id}>
                                {workflows[t.kind]} · {t.id.slice(-8)}
                              </option>
                            ))}
                        </select>
                      </label>
                      <label>
                        预期陈述分类
                        <select name="classification" aria-label="预期陈述分类">
                          <option value="unknown">未知</option>
                          <option value="unverified">待核验</option>
                          <option value="fact">事实</option>
                          <option value="inference">推断</option>
                          <option value="conflicting">来源冲突</option>
                        </select>
                      </label>
                      <label className="wide">
                        预期陈述原文
                        <textarea
                          name="expected_text"
                          required
                          maxLength={1600}
                          rows={3}
                        />
                      </label>
                      <p className="wide form-note">
                        机器评分只做去重后的文本与分类精确对照；事实正确性、数字与业务可用性须另行人工标注。
                      </p>
                    </>
                  )}
                  <button className="primary" disabled={busy}>
                    添加评测案例
                  </button>
                </form>
                <div className="evaluation-case-drafts">
                  {cases.map((c, i) => (
                    <div className="private-doc-row" key={c.id}>
                      <span>
                        {i + 1}. {caseKinds[c.kind]} · {c.id}
                      </span>
                      <button
                        className="inline-button danger"
                        onClick={() =>
                          setCases(cases.filter((_, j) => i !== j))
                        }
                      >
                        移除此案例
                      </button>
                    </div>
                  ))}
                </div>
              </section>
              <section className="workspace-panel">
                <h2>保存固定版本评测集</h2>
                <p className="form-note">
                  版本不能覆盖，来源或标注变化应另建版本。指定评审必须是另一位具备项目编辑及全部来源权限的成员；对于报告案例，还须已有相应报告读取资格。
                </p>
                <form
                  className="catalog-form"
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const data = new FormData(e.currentTarget);
                    setBusy(true);
                    setError("");
                    try {
                      const saved = await api<Dataset>(
                        base,
                        {
                          method: "POST",
                          body: JSON.stringify({
                            name: data.get("name"),
                            version: Number(data.get("version")),
                            data_kind: data.get("data_kind"),
                            source_description: data.get("source_description"),
                            authorized_for_evaluation: !!data.get("authorized"),
                            reviewer_id: data.get("reviewer") || null,
                            idempotency_key: crypto.randomUUID(),
                            cases,
                          }),
                        },
                        identity.csrf_token,
                      );
                      setDataset(await api<Dataset>(`${base}/${saved.id}`));
                      setRows(await api<DatasetMeta[]>(base));
                      setRunID("");
                      setRun(undefined);
                      setNotice(
                        "固定版本数据集已保存，尚未运行或产生业务质量结论。",
                      );
                    } catch (e) {
                      fail(e);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <label>
                    评测集名称
                    <input name="name" required maxLength={120} />
                  </label>
                  <label>
                    版本
                    <input
                      name="version"
                      type="number"
                      min={1}
                      max={100000}
                      defaultValue={1}
                      required
                    />
                  </label>
                  <label>
                    样本来源类型
                    <select name="data_kind" aria-label="样本来源类型">
                      <option value="synthetic">明确合成的工程样本</option>
                      <option value="authorized">
                        获授权的实际数据（人工声明）
                      </option>
                    </select>
                  </label>
                  <label>
                    指定独立评审（可选）
                    <select name="reviewer" aria-label="指定独立评审">
                      <option value="">暂不指定，仅作者可见</option>
                      {members
                        .filter(
                          (m) => m.can_edit && m.user_id !== identity.user.id,
                        )
                        .map((m) => (
                          <option key={m.user_id} value={m.user_id}>
                            {m.full_name} · {m.email}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label className="wide">
                    来源、范围与标注说明
                    <textarea
                      name="source_description"
                      rows={3}
                      required
                      minLength={5}
                      maxLength={3000}
                    />
                  </label>
                  <label className="checkbox-label wide">
                    <input type="checkbox" name="authorized" required />
                    我确认有权在本项目中使用这些样本及标注；实际授权与标注完整性由机构负责。
                  </label>
                  <button className="primary" disabled={busy || !cases.length}>
                    保存评测集（{cases.length} 项案例）
                  </button>
                </form>
                <details>
                  <summary className="form-section-title">
                    导入已标注 JSON 案例（高级）
                  </summary>
                  <p className="form-note">
                    仅在浏览器读取文件，正式保存时才提交。文件需含 cases
                    数组，最多一
                    MiB；范围、类型及来源会由后端重新校验，不因导入自动获得授权。
                  </p>
                  <input
                    type="file"
                    accept=".json,application/json"
                    aria-label="导入评测 JSON"
                    onChange={async (e) => {
                      setError("");
                      try {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        if (file.size > 1024 * 1024)
                          throw new Error("JSON 超过一 MiB");
                        const parsed: unknown = JSON.parse(await file.text());
                        if (
                          !parsed ||
                          typeof parsed !== "object" ||
                          !("cases" in parsed) ||
                          !Array.isArray(parsed.cases) ||
                          parsed.cases.length > 20 ||
                          !parsed.cases.length
                        )
                          throw new Error("需要含一至二十项 cases 的对象");
                        const cs = parsed.cases as DraftCase[];
                        if (
                          cs.some(
                            (c) =>
                              !c ||
                              typeof c.id !== "string" ||
                              typeof c.kind !== "string" ||
                              !caseKinds[c.kind],
                          )
                        )
                          throw new Error("案例类型或编号不正确");
                        setCases(cs);
                        setNotice(
                          "案例已载入，请补充名称、来源说明及授权确认后保存。",
                        );
                      } catch (e) {
                        fail(e);
                      }
                    }}
                  />
                </details>
              </section>
            </>
          )}
          <section className="workspace-panel">
            <div className="section-heading">
              <h2>我的与获授权的评测集</h2>
              <button
                className="refresh"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  try {
                    setRows(await api<DatasetMeta[]>(base));
                    if (dataset)
                      setDataset(await api<Dataset>(`${base}/${dataset.id}`));
                    if (runID)
                      setRun(await api<RunDetail>(`${base}/runs/${runID}`));
                  } catch (e) {
                    setDataset(undefined);
                    setRun(undefined);
                    fail(e);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                刷新评测
              </button>
            </div>
            {!rows.length ? (
              <p className="empty-state">暂无固定版本评测集。</p>
            ) : (
              rows.map((d) => (
                <div className="private-doc-row" key={d.id}>
                  <div>
                    <strong>
                      版本 {d.version} · {d.id.slice(-8)}
                    </strong>
                    <p>
                      {d.data_kind === "synthetic"
                        ? "合成工程回归"
                        : "实际授权数据（人工声明）"}
                    </p>
                  </div>
                  <button
                    className="refresh"
                    disabled={busy}
                    onClick={() => openDataset(d.id)}
                  >
                    打开评测集
                  </button>
                  {writable &&
                    d.created_by === identity.user.id &&
                    d.reviewer_id && (
                      <button
                        className="refresh danger"
                        disabled={busy}
                        onClick={() => revokeReviewer(d.id)}
                      >
                        撤销评审访问
                      </button>
                    )}
                </div>
              ))
            )}
          </section>
          {dataset && (
            <section className="workspace-panel evaluation-dataset">
              <h2>
                {dataset.name} · v{dataset.version}
              </h2>
              <p>
                {dataset.data_kind === "synthetic"
                  ? "合成数据，不作为业务效果证明"
                  : "授权数据与标注范围由机构声明，仍需人工核查"}
              </p>
              <p className="form-note">
                {dataset.definition.source_description}
              </p>
              <p className="form-note">
                样本与来源绑定摘要 {dataset.content_hash}
              </p>
              <p>
                案例 {dataset.definition.cases.length}{" "}
                项；当前引擎不会新调用外部模型。
              </p>
              {writable && (
                <button className="primary" disabled={busy} onClick={start}>
                  运行固定版本评测
                </button>
              )}
              <h3>运行记录</h3>
              {!dataset.runs.length ? (
                <p className="empty-state">尚未运行。</p>
              ) : (
                dataset.runs.map((r) => (
                  <div className="private-doc-row" key={r.id}>
                    <span>
                      {evaluationStates[r.status]} · {r.id.slice(-8)}
                    </span>
                    <button
                      className="refresh"
                      onClick={() => {
                        setError("");
                        setRun(undefined);
                        setRunID(r.id);
                        if (runID === r.id)
                          api<RunDetail>(`${base}/runs/${r.id}`)
                            .then(setRun)
                            .catch(fail);
                      }}
                    >
                      查看本次结果
                    </button>
                  </div>
                ))
              )}
            </section>
          )}
          {run && (
            <section className="workspace-panel evaluation-run">
              <h2>本次评测结果</h2>
              <a
                className="refresh"
                href={`/api/${base}/runs/${run.id}/export`}
                download
              >
                下载评测证据 JSON
              </a>
              <p>
                {evaluationStates[run.status]} · 第 {run.attempts} 次执行
              </p>
              {run.error_code && (
                <p className="error-message">
                  任务未完成：{run.error_code}
                  。权限或来源变更后应核对数据并创建新版本。
                </p>
              )}
              <p className="form-note">
                {run.data_kind === "synthetic"
                  ? "此为合成回归，不提供真实试点成功结论。"
                  : "仅依据已提交标注与反馈，不代表未覆盖样本质量。"}
              </p>
              <div className="catalog-actions">
                {writable && run.status === "failed" && run.attempts < 3 && (
                  <button
                    className="refresh"
                    disabled={busy}
                    onClick={() => action("retry")}
                  >
                    重试评测
                  </button>
                )}
                {writable && ["queued", "running"].includes(run.status) && (
                  <button
                    className="refresh danger"
                    disabled={busy}
                    onClick={() => action("cancel")}
                  >
                    取消评测
                  </button>
                )}
              </div>
              <div className="evaluation-metrics">
                <article>
                  <strong>
                    {run.summary.measured_count} / {run.summary.case_count}
                  </strong>
                  <span>已测量案例／已生成记录</span>
                </article>
                <article>
                  <strong>
                    {percent(run.summary.independent_fact_accuracy)}
                  </strong>
                  <span>
                    独立事实正确率 · 已评{" "}
                    {run.summary.independent_fact_judged_count} 条
                  </span>
                </article>
                <article>
                  <strong>
                    {percent(run.summary.independent_fact_review_coverage)}
                  </strong>
                  <span>独立事实评审覆盖率</span>
                </article>
                <article>
                  <strong>
                    {percent(run.summary.independent_model_usability_rate)}
                  </strong>
                  <span>
                    独立可用率 · 已评{" "}
                    {run.summary.independent_usability_case_count} 例
                  </span>
                </article>
                <article>
                  <strong>
                    {displayMetric(run.summary.p95_case_latency_ms)} ms
                  </strong>
                  <span>本次案例 P95 耗时，非模型推理时长</span>
                </article>
                <article>
                  <strong>{run.summary.new_model_calls}</strong>
                  <span>本次新增外部模型调用</span>
                </article>
              </div>
              <p className="form-note">
                不同来源任务 {run.summary.unique_upstream_tasks}{" "}
                个；重复任务已去重。人工标注冲突{" "}
                {run.summary.conflicting_human_judgment_count}{" "}
                项，冲突不计为正确。
              </p>
              <p className="form-note">
                已有任务调用记录 {run.summary.upstream_call_count}{" "}
                次；其估算费用 USD{" "}
                {run.summary.upstream_cost_micros === null
                  ? "未知"
                  : (run.summary.upstream_cost_micros / 1000000).toFixed(6)}
                ，不重复算作本次模型调用。
              </p>
              {run.summary.limitations.map((text, i) => (
                <p className="form-note" key={i}>
                  {text}
                </p>
              ))}
              {run.records.map((record) => (
                <article
                  className="citation-card evaluation-case-result"
                  key={record.case_id}
                >
                  <h3>
                    {caseKinds[record.kind]} · {record.case_id}
                  </h3>
                  <p>
                    {record.status === "measured"
                      ? "已测量，不等于通过业务验收"
                      : record.status === "blocked"
                        ? "未评测／来源未就绪"
                        : "执行失败"}{" "}
                    · {record.latency_ms} ms
                  </p>
                  {record.error_code && (
                    <p className="error-message">
                      {record.error_code === "MODEL_NOT_CONFIGURED"
                        ? "模型未配置，没有可评分结果；不计入已测量或通过样本。"
                        : record.error_code}
                    </p>
                  )}
                  <dl className="evaluation-score-list">
                    {Object.entries(record.metrics).map(([key, value]) => (
                      <div key={key}>
                        <dt>{metricLabels[key] || key}</dt>
                        <dd>{displayMetric(value)}</dd>
                      </div>
                    ))}
                  </dl>
                  {record.provenance && (
                    <p className="form-note">
                      来源任务 {record.provenance.task_id} ·{" "}
                      {record.provenance.prompt_version}
                    </p>
                  )}
                  {!!record.issue_codes?.length && (
                    <p className="form-note">
                      质量闸类型：{record.issue_codes.join("、")}
                    </p>
                  )}
                </article>
              ))}
              {writable && run.status === "completed" && run.result_hash && (
                <>
                  {selectedCase?.observed_output && (
                    <details>
                      <summary className="form-section-title">
                        核对所选模型草案的完整输出
                      </summary>
                      <p>{selectedCase.observed_output.summary.text}</p>
                      {selectedCase.observed_output.sections.map((section) => (
                        <div key={section.key}>
                          <h3>{sectionLabels[section.key] || section.key}</h3>
                          {section.claims.map((claim, i) => (
                            <p key={i}>
                              {claim.text}（{claim.classification}）
                            </p>
                          ))}
                        </div>
                      ))}
                      {selectedCase.observed_output.questions.map((q, i) => (
                        <article className="citation-card" key={i}>
                          <strong>{q.question}</strong>
                          <p>
                            {q.reason}；{q.risk}；{q.known_information}；
                            {q.missing_evidence}；{q.verification_method}
                          </p>
                        </article>
                      ))}
                      {[
                        ...selectedCase.observed_output.unknowns,
                        ...selectedCase.observed_output.limitations,
                      ].map((text, i) => (
                        <p key={i}>{text}</p>
                      ))}
                    </details>
                  )}
                  <h3>人工反馈与问题记录</h3>
                  <p className="form-note">
                    {dataset?.reviewer_id === identity.user.id
                      ? "你是指定评审；非来源作者的明确标注可计入独立指标。"
                      : "你提交的是作者自评，会单列，不计入独立事实正确率和可用率。"}
                    只标注实际核对的项目，留空表示未评，不自动当作正确。
                  </p>
                  <form
                    className="catalog-form"
                    key={`${run.id}-${feedbackCase}`}
                    onSubmit={async (e) => {
                      e.preventDefault();
                      const data = new FormData(e.currentTarget);
                      setBusy(true);
                      setError("");
                      try {
                        const judgments = (
                          selectedCase?.observed_claims || []
                        ).flatMap((_, index) => {
                          const value = data.get(`claim_${index}`);
                          return value === "true" || value === "false"
                            ? [{ index, correct: value === "true" }]
                            : [];
                        });
                        const bool = (key: string) =>
                          data.get(key) === "true"
                            ? true
                            : data.get(key) === "false"
                              ? false
                              : null;
                        await api(
                          `${base}/runs/${run.id}/feedback`,
                          {
                            method: "POST",
                            body: JSON.stringify({
                              case_id: feedbackCase,
                              result_hash: run.result_hash,
                              usable: bool("usable"),
                              numeric_correct: bool("numeric_correct"),
                              claim_judgments: judgments,
                              category: data.get("category"),
                              severity: data.get("severity"),
                              notes: data.get("notes"),
                            }),
                          },
                          identity.csrf_token,
                        );
                        setRun(await api<RunDetail>(`${base}/runs/${run.id}`));
                        setNotice(
                          "反馈已追加记录；统计按同一评审对同一案例的最新标注更新。",
                        );
                      } catch (e) {
                        fail(e);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    <label>
                      反馈案例
                      <select
                        aria-label="反馈案例"
                        value={feedbackCase}
                        onChange={(e) => setFeedbackCase(e.target.value)}
                      >
                        {run.records
                          .filter((r) => r.status === "measured")
                          .map((r) => (
                            <option key={r.case_id} value={r.case_id}>
                              {caseKinds[r.kind]} · {r.case_id}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label>
                      业务可用性
                      <select name="usable" aria-label="业务可用性">
                        <option value="">未评</option>
                        <option value="true">人工判断可用</option>
                        <option value="false">人工判断不可用</option>
                      </select>
                    </label>
                    <label>
                      数字案例准确性
                      <select
                        name="numeric_correct"
                        aria-label="数字案例准确性"
                      >
                        <option value="">未评／不适用</option>
                        <option value="true">核对正确</option>
                        <option value="false">存在错误</option>
                      </select>
                    </label>
                    <label>
                      问题分类
                      <select name="category" aria-label="问题分类">
                        {[
                          ["relevance", "相关性"],
                          ["citation", "引用"],
                          ["fact", "事实"],
                          ["number", "数字"],
                          ["unknown", "未知"],
                          ["conflict", "冲突"],
                          ["usability", "可用性"],
                          ["access", "权限"],
                          ["latency", "延迟"],
                          ["other", "其他"],
                        ].map(([key, label]) => (
                          <option key={key} value={key}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      严重程度
                      <select name="severity" aria-label="严重程度">
                        <option value="low">低</option>
                        <option value="medium">中</option>
                        <option value="high">高</option>
                      </select>
                    </label>
                    {selectedCase?.observed_claims?.map((claim, i) => (
                      <label className="wide" key={i}>
                        陈述 {i + 1}（{claim.classification}）：{claim.text}
                        <select
                          aria-label={`陈述${i + 1}人工判断`}
                          name={`claim_${i}`}
                        >
                          <option value="">尚未核对</option>
                          <option value="true">核对正确</option>
                          <option value="false">存在错误</option>
                        </select>
                      </label>
                    ))}
                    <label className="wide">
                      反馈依据与改进建议
                      <textarea
                        name="notes"
                        rows={3}
                        minLength={5}
                        maxLength={3000}
                        required
                      />
                    </label>
                    <button
                      className="primary"
                      disabled={busy || !feedbackCase}
                    >
                      提交反馈
                    </button>
                  </form>
                </>
              )}
              <details>
                <summary className="form-section-title">
                  核对本次授权证据与来源
                </summary>
                {run.evidence.map((source) => (
                  <article className="citation-card" key={source.id}>
                    <strong>{source.id}</strong>
                    <blockquote>{source.excerpt}</blockquote>
                    {source.document_id ? (
                      <Link
                        href={`/knowledge?organization=${org}&project=${source.project_id}&document=${source.document_id}&version=${source.version_number}`}
                      >
                        核对授权原文版本 →
                      </Link>
                    ) : (
                      source.company_id && (
                        <Link href={`/companies/${source.company_id}`}>
                          核对公共企业档案 →
                        </Link>
                      )
                    )}
                  </article>
                ))}
              </details>
              <h3>反馈历史</h3>
              {!run.feedback.length ? (
                <p className="empty-state">
                  暂无人工反馈。业务正确率保持未评测，不自动生成分数。
                </p>
              ) : (
                run.feedback.map((f) => (
                  <article className="citation-card" key={f.id}>
                    <strong>
                      {f.independent ? "独立评审" : "作者自评"} · {f.case_id}
                    </strong>
                    <p>{f.notes}</p>
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
