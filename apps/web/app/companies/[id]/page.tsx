"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CatalogShell } from "@/components/catalog-shell";
import { CompanyForm } from "@/components/company-form";
import { api, ApiError, type Identity } from "@/lib/api";
import {
  companyPayload,
  fieldLabels,
  labels,
  type Company,
  type Source,
  type Taxonomy,
  type Change,
  type CompanySummary,
} from "@/lib/catalog";
type Candidate = CompanySummary & { reasons: string[] };
export default function Page() {
  const { id } = useParams<{ id: string }>();
  return (
    <CatalogShell title="企业档案">
      {(identity) => <Profile key={id} id={id} identity={identity} />}
    </CatalogShell>
  );
}
function Profile({ id, identity }: { id: string; identity: Identity }) {
  const [record, setRecord] = useState<Company>();
  const [sources, setSources] = useState<Source[]>([]);
  const [taxonomy, setTaxonomy] = useState<Taxonomy>({
    industries: [],
    technologies: [],
  });
  const [changes, setChanges] = useState<Change[]>([]);
  const [duplicates, setDuplicates] = useState<{
    items: Candidate[];
    truncated: boolean;
  }>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const router = useRouter();
  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else if (e instanceof Error && e.name !== "AbortError")
        setError(e.message);
    },
    [router],
  );
  const load = useCallback(
    async (signal?: AbortSignal) => {
      const [c, s, t, h] = await Promise.all([
        api<Company>(`companies/${id}`, { signal }),
        api<Source[]>("catalog/sources", { signal }),
        api<Taxonomy>("catalog/taxonomy", { signal }),
        api<Change[]>(`companies/${id}/history`, { signal }),
      ]);
      setRecord(c);
      setSources(s);
      setTaxonomy(t);
      setChanges(h);
    },
    [id],
  );
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).catch(fail);
    return () => controller.abort();
  }, [load, fail]);
  async function mutate(path: string, method: string, payload: unknown) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(
        path,
        { method, body: JSON.stringify(payload) },
        identity.csrf_token,
      );
      await load();
      setDuplicates(undefined);
      setNotice("已保存，来源与操作记录已保留");
      return true;
    } catch (e) {
      fail(e);
      return false;
    } finally {
      setBusy(false);
    }
  }
  const writable =
    identity.can_curate_public_data &&
    record &&
    !record.is_archived &&
    !record.merged_into_id;
  const ownEvidence =
    record?.evidence.filter(
      (e) => e.company_id === id && e.verification_status !== "rejected",
    ) || [];
  return (
    <>
      <div className="workspace-heading">
        <div>
          <div className="eyebrow">COMPANY INTELLIGENCE</div>
          <Link className="back-link" href="/companies">
            ← 返回企业情报
          </Link>
          <h1 className="company-title">
            {record?.canonical_name || "企业档案"}
          </h1>
          <p>所有字段均来自已登记资料；未经核验的内容不作为已证实事实。</p>
        </div>
        {writable && (
          <button className="refresh" onClick={() => setEditing(!editing)}>
            {editing ? "关闭编辑" : "编辑企业"}
          </button>
        )}
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
      {!record ? (
        <p className="empty-state">
          {error ? "档案无法加载。" : "正在读取档案…"}
        </p>
      ) : (
        <>
          {record.merged_into_id && (
            <p className="scope-banner">
              此原始档案已关联到主档案，原文证据仍保留。
              <Link href={`/companies/${record.merged_into_id}`}>
                查看主档案 →
              </Link>
            </p>
          )}
          {record.is_archived && (
            <p className="scope-banner">
              此档案已归档，历史资料与证据没有删除。
            </p>
          )}
          {editing && writable && (
            <section className="workspace-panel">
              <h2>编辑企业 · 版本 {record.version}</h2>
              <CompanyForm
                key={record.version}
                record={record}
                sources={sources}
                taxonomy={taxonomy}
                busy={busy}
                onSubmit={async (data) => {
                  if (
                    await mutate(`companies/${id}`, "PATCH", {
                      ...companyPayload(data),
                      expected_version: record.version,
                    })
                  )
                    setEditing(false);
                }}
              />
            </section>
          )}
          <section className="workspace-panel">
            <div className="section-heading">
              <h2>企业画像 / 基础档案</h2>
              <span>
                版本 {record.version} ·{" "}
                {new Date(record.updated_at).toLocaleString("zh-CN")}
              </span>
            </div>
            <p className="profile-description">
              {record.description || "暂无有来源的企业简介。"}
            </p>
            <dl className="facts-grid">
              {[
                ["登记名称", record.registration_name],
                ["别名", record.aliases.join(" / ")],
                [
                  "国家或地区",
                  record.country === "unknown" ? "未知" : record.country,
                ],
                [
                  "地域",
                  [record.province, record.city].filter(Boolean).join(" / "),
                ],
                ["上市状态", labels[record.listing_status]],
                ["企业发展阶段", labels[record.company_stage]],
                ["融资阶段", labels[record.financing_stage]],
                ["成立日期", record.founded_on],
                ["统一社会信用代码", record.unified_social_credit_code],
                [
                  "产业链节点",
                  record.industries.map((n) => n.name).join(" / "),
                ],
              ].map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value || "未知"}</dd>
                </div>
              ))}
            </dl>
            {record.website && (
              <p className="form-note">
                官网：
                <a
                  href={record.website}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {record.website} ↗
                </a>
              </p>
            )}
            <p className="form-note">
              档案整体为待核验记录；核验状态只对具体证据主张有效，不意味着所有字段都已核验。
            </p>
            {record.related_records.length > 0 && (
              <p className="form-note">
                关联原始档案：
                {record.related_records.map((c) => (
                  <Link key={c.id} href={`/companies/${c.id}`}>
                    {c.name} ·{" "}
                  </Link>
                ))}
              </p>
            )}
          </section>
          {record.conflicts.length > 0 && (
            <section className="conflict-panel">
              <h2>存在不同来源说法</h2>
              {record.conflicts.map((c) => (
                <p key={c.field_name}>
                  {fieldLabels[c.field_name] || c.field_name}：
                  {c.values.join(" / ")}
                  。请核对下方证据，系统没有静默选择某个值。
                </p>
              ))}
            </section>
          )}
          <section className="workspace-panel">
            <h2>产品与技术</h2>
            {!record.products.length && !record.technologies.length ? (
              <p className="empty-state">
                暂无可追溯的产品或技术关联。不据此推断技术不存在。
              </p>
            ) : (
              <>
                <div className="company-tags">
                  {record.technologies.map((t) => (
                    <a key={t.id} href={`#evidence-${t.evidence_id}`}>
                      {t.name} · {labels[t.relation_type]} ·{" "}
                      {labels[t.verification_status]}
                    </a>
                  ))}
                </div>
                {record.products.map((p) => (
                  <article className="evidence-card" key={p.id}>
                    <h3>
                      {p.name} <small>{p.product_category}</small>
                    </h3>
                    <p>{p.description || "产品说明未知"}</p>
                    <p className="form-note">
                      技术路线：{p.technical_route || "未知"} · 商业化：
                      {labels[p.commercialization_stage]}
                    </p>
                    <a
                      className="back-link"
                      href={`#evidence-${p.evidence_id}`}
                    >
                      查看支持证据 →
                    </a>
                  </article>
                ))}
              </>
            )}
          </section>
          <section className="workspace-panel">
            <h2>事实、推断与证据</h2>
            {!record.evidence.length ? (
              <p className="empty-state">
                尚未登记原文证据，档案信息仍待核验。
              </p>
            ) : (
              record.evidence.map((e) => (
                <article
                  className="evidence-card"
                  id={`evidence-${e.id}`}
                  key={e.id}
                >
                  <div className="section-heading">
                    <h3>{e.claim_text}</h3>
                    <span>
                      {labels[e.classification]} ·{" "}
                      {labels[e.verification_status]}
                    </span>
                  </div>
                  <blockquote>{e.excerpt}</blockquote>
                  <p className="form-note">
                    {sources.find((s) => s.id === e.source_id)?.source_name ||
                      "已登记来源"}
                    {e.page_number ? ` · 第 ${e.page_number} 页` : ""}
                    {e.section_name ? ` · ${e.section_name}` : ""}
                    {e.field_name
                      ? ` · ${e.field_name}: ${e.field_value ?? "未知"}`
                      : ""}
                  </p>
                  {e.reviewed_at && (
                    <p className="form-note">
                      人工核验记录：
                      {new Date(e.reviewed_at).toLocaleString("zh-CN")}
                    </p>
                  )}
                  {writable && e.company_id === id && (
                    <form
                      className="review-form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const data = new FormData(event.currentTarget);
                        void mutate(
                          `companies/${id}/evidence/${e.id}`,
                          "PATCH",
                          {
                            verification_status: data.get(
                              "verification_status",
                            ),
                            reason: data.get("reason"),
                          },
                        );
                      }}
                    >
                      <label>
                        核验状态
                        <select
                          name="verification_status"
                          defaultValue={e.verification_status}
                        >
                          {[
                            "unverified",
                            "verified",
                            "conflicting",
                            "rejected",
                          ].map((v) => (
                            <option key={v} value={v}>
                              {labels[v]}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        核验原因
                        <input
                          name="reason"
                          required
                          minLength={3}
                          maxLength={1000}
                        />
                      </label>
                      <button className="refresh" disabled={busy}>
                        记录人工核验
                      </button>
                    </form>
                  )}
                </article>
              ))
            )}
          </section>
          {writable && (
            <section className="workspace-panel">
              <details>
                <summary className="form-section-title">
                  登记新的原文证据
                </summary>
                <form
                  className="catalog-form"
                  onSubmit={async (event) => {
                    event.preventDefault();
                    const form = event.currentTarget;
                    const data = new FormData(form);
                    if (
                      await mutate(`companies/${id}/evidence`, "POST", {
                        source_id: data.get("source_id"),
                        claim_text: data.get("claim_text"),
                        excerpt: data.get("excerpt"),
                        classification: data.get("classification"),
                        verification_status: "unverified",
                        field_name: data.get("field_name") || null,
                        field_value: data.get("field_value") || null,
                        page_number: data.get("page_number")
                          ? Number(data.get("page_number"))
                          : null,
                        section_name: data.get("section_name") || null,
                      })
                    )
                      form.reset();
                  }}
                >
                  <label>
                    资料来源
                    <select name="source_id" required>
                      {sources.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.source_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    内容类别
                    <select name="classification">
                      {[
                        "unverified",
                        "fact",
                        "inference",
                        "unknown",
                        "conflicting",
                      ].map((v) => (
                        <option key={v} value={v}>
                          {labels[v]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="wide">
                    支持的具体主张
                    <input
                      name="claim_text"
                      required
                      minLength={3}
                      maxLength={5000}
                    />
                  </label>
                  <label className="wide">
                    原文摘录
                    <textarea
                      name="excerpt"
                      required
                      minLength={3}
                      maxLength={10000}
                    />
                  </label>
                  <label>
                    关联字段（可选）
                    <input
                      name="field_name"
                      pattern="[a-z][a-z0-9_]*"
                      placeholder="例如 listing_status"
                    />
                  </label>
                  <label>
                    原文中的字段值（可选）
                    <input name="field_value" maxLength={500} />
                  </label>
                  <label>
                    页码
                    <input name="page_number" type="number" min={1} />
                  </label>
                  <label>
                    章节
                    <input name="section_name" maxLength={200} />
                  </label>
                  <button className="primary" disabled={busy}>
                    保存证据
                  </button>
                </form>
              </details>
              <details>
                <summary className="form-section-title">关联技术路线</summary>
                <form
                  className="review-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const data = new FormData(event.currentTarget);
                    void mutate(`companies/${id}/technologies`, "POST", {
                      technology_id: data.get("technology_id"),
                      evidence_id: data.get("evidence_id"),
                      relation_type: data.get("relation_type"),
                    });
                  }}
                >
                  <label>
                    技术路线
                    <select name="technology_id" required>
                      {taxonomy.technologies.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    支持证据
                    <select name="evidence_id" required>
                      {ownEvidence.map((e) => (
                        <option key={e.id} value={e.id}>
                          {e.claim_text}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    关系类型
                    <select name="relation_type">
                      {[
                        "announced",
                        "develops",
                        "manufactures",
                        "licenses",
                        "uses",
                        "researches",
                      ].map((v) => (
                        <option key={v} value={v}>
                          {labels[v]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="primary"
                    disabled={
                      busy ||
                      !ownEvidence.length ||
                      !taxonomy.technologies.length
                    }
                  >
                    保存技术关联
                  </button>
                </form>
              </details>
              <details>
                <summary className="form-section-title">登记产品</summary>
                <form
                  className="catalog-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const data = new FormData(event.currentTarget);
                    const evidence = ownEvidence.find(
                      (e) => e.id === data.get("evidence_id"),
                    );
                    if (!evidence) return;
                    void mutate(`companies/${id}/products`, "POST", {
                      name: data.get("name"),
                      product_category: data.get("product_category"),
                      description: data.get("description") || "",
                      technical_route: data.get("technical_route") || "",
                      commercialization_stage: data.get(
                        "commercialization_stage",
                      ),
                      evidence_id: evidence.id,
                      source_id: evidence.source_id,
                    });
                  }}
                >
                  <label>
                    产品名称
                    <input name="name" required maxLength={200} />
                  </label>
                  <label>
                    产品类别
                    <input name="product_category" required maxLength={100} />
                  </label>
                  <label>
                    技术路线描述
                    <input name="technical_route" maxLength={200} />
                  </label>
                  <label>
                    商业化阶段
                    <select name="commercialization_stage">
                      {[
                        "unknown",
                        "research",
                        "prototype",
                        "pilot",
                        "commercial",
                        "scaled",
                      ].map((v) => (
                        <option key={v} value={v}>
                          {labels[v]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="wide">
                    产品说明
                    <textarea name="description" maxLength={5000} />
                  </label>
                  <label className="wide">
                    产品支持证据
                    <select name="evidence_id" required>
                      {ownEvidence.map((e) => (
                        <option key={e.id} value={e.id}>
                          {e.claim_text}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="primary"
                    disabled={busy || !ownEvidence.length}
                  >
                    保存产品
                  </button>
                </form>
              </details>
            </section>
          )}
          <section className="workspace-panel">
            <h2>资料来源与许可</h2>
            {record.sources.map((s) => (
              <article className="source-card" key={s.id}>
                <h3>
                  {s.source_name}{" "}
                  {s.license_type === "synthetic_demo" && (
                    <span className="planned">合成演示资料</span>
                  )}
                </h3>
                <p>{s.permitted_use}</p>
                <p className="form-note">
                  许可声明：{s.license_type} · 获取时间：
                  {new Date(s.accessed_at).toLocaleString("zh-CN")} · 可靠性：
                  {s.reliability_level}
                </p>
                {s.source_url && (
                  <a
                    className="back-link"
                    href={s.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    查看原始来源 ↗
                  </a>
                )}
              </article>
            ))}
          </section>
          <section className="workspace-panel">
            <h2>档案变更记录</h2>
            {changes.map((c) => (
              <article className="source-card" key={c.id}>
                <strong>{c.reason}</strong>
                <p className="form-note">
                  {c.action} · {new Date(c.created_at).toLocaleString("zh-CN")}{" "}
                  ·{" "}
                  {sources.find((s) => s.id === c.source_id)?.source_name ||
                    c.source_id}
                </p>
                <details>
                  <summary>查看变更前后值</summary>
                  <pre className="change-json">
                    {JSON.stringify(
                      { before: c.before, after: c.after },
                      null,
                      2,
                    )}
                  </pre>
                </details>
              </article>
            ))}
          </section>
          {identity.can_curate_public_data && (
            <section className="workspace-panel">
              <h2>疑似重复与人工合并</h2>
              <p className="form-note">
                相似名称仅供核实，系统不会自动合并。合并保留原始企业、来源、证据和标识；可以撤销。
              </p>
              {writable && (
                <>
                  <button
                    className="refresh"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      setError("");
                      try {
                        setDuplicates(
                          await api<{ items: Candidate[]; truncated: boolean }>(
                            `companies/${id}/duplicates`,
                          ),
                        );
                      } catch (e) {
                        fail(e);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    检查疑似重复
                  </button>
                  {duplicates && (
                    <>
                      <p className="form-note">
                        {duplicates.items.length} 个候选
                        {duplicates.truncated
                          ? "；扫描达到上限，候选不代表全部重复记录。"
                          : ""}
                      </p>
                      {duplicates.items.map((c) => (
                        <article className="source-card" key={c.id}>
                          <Link href={`/companies/${c.id}`}>
                            {c.canonical_name} ↗
                          </Link>
                          <p className="form-note">{c.reasons.join(" · ")}</p>
                        </article>
                      ))}
                      {duplicates.items.length > 0 && (
                        <form
                          className="catalog-form"
                          onSubmit={(event) => {
                            event.preventDefault();
                            const data = new FormData(event.currentTarget);
                            const candidate = duplicates.items.find(
                              (c) => c.id === data.get("duplicate_id"),
                            );
                            if (!candidate) return;
                            void mutate(`companies/${id}/merge`, "POST", {
                              duplicate_id: candidate.id,
                              expected_target_version: record.version,
                              expected_duplicate_version: candidate.version,
                              source_id: record.source_id,
                              reason: data.get("reason"),
                              confirm: true,
                            });
                          }}
                        >
                          <label>
                            归入本主档案的候选
                            <select name="duplicate_id" required>
                              {duplicates.items.map((c) => (
                                <option key={c.id} value={c.id}>
                                  {c.canonical_name}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            人工确认依据
                            <input
                              name="reason"
                              required
                              minLength={3}
                              maxLength={1000}
                            />
                          </label>
                          <label className="checkbox-label wide">
                            <input type="checkbox" required />
                            我已核对身份信息，确认这两个档案属于同一企业。
                          </label>
                          <button className="primary" disabled={busy}>
                            确认合并并保留原档案
                          </button>
                        </form>
                      )}
                    </>
                  )}
                </>
              )}
              {record.merges
                .filter((m) => m.target_id === id && !m.reverted_at)
                .map((m) => (
                  <form
                    className="review-form"
                    key={m.id}
                    onSubmit={async (event) => {
                      event.preventDefault();
                      const data = new FormData(event.currentTarget);
                      setError("");
                      try {
                        const child = await api<Company>(
                          `companies/${m.duplicate_id}`,
                        );
                        await mutate(`catalog/merges/${m.id}/undo`, "POST", {
                          source_id: record.source_id,
                          reason: data.get("reason"),
                          expected_target_version: record.version,
                          expected_duplicate_version: child.version,
                        });
                      } catch (e) {
                        fail(e);
                      }
                    }}
                  >
                    <span>
                      已合并：
                      {record.related_records.find(
                        (c) => c.id === m.duplicate_id,
                      )?.name || m.duplicate_id}
                    </span>
                    <label>
                      撤销合并原因
                      <input
                        name="reason"
                        required
                        minLength={3}
                        maxLength={1000}
                      />
                    </label>
                    <button className="refresh" disabled={busy}>
                      撤销此合并
                    </button>
                  </form>
                ))}
              {!record.merged_into_id && (
                <form
                  className="review-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const data = new FormData(event.currentTarget);
                    void mutate(`companies/${id}/archive`, "POST", {
                      source_id: record.source_id,
                      reason: data.get("reason"),
                      expected_version: record.version,
                      archived: !record.is_archived,
                    });
                  }}
                >
                  <p className="form-note">归档不会物理删除档案或证据。</p>
                  <label>
                    归档或恢复原因
                    <input
                      name="reason"
                      required
                      minLength={3}
                      maxLength={1000}
                    />
                  </label>
                  <button className="refresh" disabled={busy}>
                    {record.is_archived ? "恢复档案" : "归档企业"}
                  </button>
                </form>
              )}
            </section>
          )}
        </>
      )}
    </>
  );
}
