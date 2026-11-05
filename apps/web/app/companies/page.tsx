"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CatalogShell } from "@/components/catalog-shell";
import { CompanyForm } from "@/components/company-form";
import { api, ApiError, type Identity } from "@/lib/api";
import {
  companyPayload,
  labels,
  type Company,
  type SearchResult,
  type Source,
  type Taxonomy,
} from "@/lib/catalog";
export default function Page() {
  return (
    <CatalogShell title="企业情报">
      {(identity) => <Companies identity={identity} />}
    </CatalogShell>
  );
}
function Companies({ identity }: { identity: Identity }) {
  const [result, setResult] = useState<SearchResult>({
    items: [],
    total: 0,
    offset: 0,
    limit: 20,
  });
  const [taxonomy, setTaxonomy] = useState<Taxonomy>({
    industries: [],
    technologies: [],
  });
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
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
    async (offset = 0, signal?: AbortSignal) => {
      const params = new URLSearchParams({
        ...filters,
        offset: String(offset),
        limit: "20",
      });
      return api<SearchResult>(`companies?${params}`, { signal });
    },
    [filters],
  );
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    Promise.all([
      load(0, controller.signal),
      api<Taxonomy>("catalog/taxonomy", { signal: controller.signal }),
      api<Source[]>("catalog/sources", { signal: controller.signal }),
    ])
      .then(([r, t, s]) => {
        setResult(r);
        setTaxonomy(t);
        setSources(s);
      })
      .catch(fail)
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [load, fail]);
  async function pageResult(offset: number) {
    return activeQuery
      ? api<SearchResult>(
          "companies/search",
          {
            method: "POST",
            body: JSON.stringify({
              query: activeQuery,
              filters: { ...filters, limit: 20, offset },
            }),
          },
          identity.csrf_token,
        )
      : load(offset);
  }
  async function natural() {
    setBusy(true);
    setError("");
    try {
      setResult(
        await api<SearchResult>(
          "companies/search",
          {
            method: "POST",
            body: JSON.stringify({
              query,
              filters: { ...filters, limit: 20, offset: 0 },
            }),
          },
          identity.csrf_token,
        ),
      );
      setActiveQuery(query);
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
          <div className="eyebrow">DISCOVER WITH EVIDENCE</div>
          <h1>企业情报</h1>
          <p>按产业、技术和公开档案发现企业，逐条核对来源。</p>
        </div>
        {identity.can_curate_public_data && (
          <div className="catalog-actions">
            <Link className="refresh" href="/catalog">
              来源与批量导入
            </Link>
            <button className="primary" onClick={() => setAdding(!adding)}>
              {adding ? "关闭录入" : "新增企业"}
            </button>
          </div>
        )}
      </div>
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      {adding && (
        <section className="workspace-panel">
          <h2>登记公共企业档案</h2>
          <CompanyForm
            taxonomy={taxonomy}
            sources={sources}
            busy={busy}
            onSubmit={async (data) => {
              setBusy(true);
              setError("");
              try {
                const c = await api<Company>(
                  "companies",
                  {
                    method: "POST",
                    body: JSON.stringify(companyPayload(data)),
                  },
                  identity.csrf_token,
                );
                router.push(`/companies/${c.id}`);
              } catch (e) {
                fail(e);
              } finally {
                setBusy(false);
              }
            }}
          />
        </section>
      )}
      <section className="workspace-panel">
        <form
          className="discovery-query"
          onSubmit={(e) => {
            e.preventDefault();
            void natural();
          }}
        >
          <label>
            企业搜索 / 条件描述
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              maxLength={500}
              required
              placeholder="例如：江苏先进封装混合键合未上市中试企业"
            />
          </label>
          <button className="primary" disabled={busy || loading}>
            搜索企业
          </button>
        </form>
        <p className="form-note">
          按已维护的行业、技术、地域与阶段词规则匹配，不联网补全；未知状态不会被当作未上市。
        </p>
        <form
          className="catalog-filters"
          onSubmit={(e) => {
            e.preventDefault();
            setQuery("");
            setActiveQuery("");
            const form = new FormData(e.currentTarget);
            const values = Object.fromEntries(
              [...form.entries()]
                .filter(([, value]) => String(value))
                .map(([key, value]) => [key, String(value)]),
            );
            if (values.updated_since)
              values.updated_since = new Date(
                values.updated_since,
              ).toISOString();
            setFilters(values);
          }}
        >
          <label>
            名称或别名
            <input name="q" maxLength={300} placeholder="输入企业名称" />
          </label>
          <label>
            产业节点
            <select name="industry_id">
              <option value="">全部产业</option>
              {taxonomy.industries.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            技术路线
            <select name="technology_id">
              <option value="">全部技术</option>
              {taxonomy.technologies.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            国家或地区
            <input name="country" placeholder="中国 / unknown" />
          </label>
          <label>
            省份
            <input name="province" placeholder="例如：江苏" />
          </label>
          <label>
            城市
            <input name="city" placeholder="例如：苏州" />
          </label>
          <label>
            成立日期从
            <input name="founded_after" type="date" />
          </label>
          <label>
            成立日期至
            <input name="founded_before" type="date" />
          </label>
          <label>
            最近更新于之后
            <input name="updated_since" type="datetime-local" />
          </label>
          <label>
            上市状态
            <select name="listing_status">
              <option value="">全部状态</option>
              {["unknown", "unlisted", "listed", "delisted"].map((v) => (
                <option key={v} value={v}>
                  {labels[v]}
                </option>
              ))}
            </select>
          </label>
          <label>
            发展阶段
            <select name="company_stage">
              <option value="">全部阶段</option>
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
          <label>
            融资阶段
            <select name="financing_stage">
              <option value="">全部阶段</option>
              {[
                "unknown",
                "seed",
                "angel",
                "A",
                "B",
                "C",
                "pre_ipo",
                "other",
              ].map((v) => (
                <option key={v} value={v}>
                  {labels[v]}
                </option>
              ))}
            </select>
          </label>
          <label>
            资料来源
            <select name="source_id">
              <option value="">全部来源</option>
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.source_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            包含归档
            <select name="include_archived">
              <option value="">不包含</option>
              <option value="true">包含归档</option>
            </select>
          </label>
          <button className="refresh" disabled={busy || loading}>
            应用筛选
          </button>
        </form>
      </section>
      <section className="workspace-panel">
        <div className="section-heading">
          <h2>
            企业档案 <span className="count">{result.total}</span>
          </h2>
          <span>结果基于现有数据，非完整市场覆盖</span>
        </div>
        {result.matched_intent && (
          <p className="form-note">
            已提取条件：
            {result.matched_intent.join(" · ") || "按名称与文本匹配"}。
            {result.limitations}
          </p>
        )}
        {!!result.unparsed_criteria?.length && (
          <p className="error-message">
            以下描述未作为筛选条件执行：{result.unparsed_criteria.join("、")}
            。请核对资料，不能据搜索结果认定企业满足这些条件。
          </p>
        )}
        {loading ? (
          <p className="empty-state">正在检索档案…</p>
        ) : !result.items.length ? (
          <p className="empty-state">
            暂无符合条件的企业档案。尚未登记的数据不会被自动推断。
          </p>
        ) : (
          <div className="company-grid">
            {result.items.map((c) => (
              <Link
                className="company-card"
                href={`/companies/${c.id}`}
                key={c.id}
              >
                <div>
                  <span className="role-chip">
                    {c.province || "地域未知"} {c.city || ""}
                  </span>
                  <span className="planned">
                    {c.is_archived ? "已归档" : "待核验档案"}
                  </span>
                </div>
                <h3>{c.canonical_name}</h3>
                <p>{c.description || "企业简介尚未补充。"}</p>
                <div className="company-tags">
                  <span>{labels[c.listing_status]}</span>
                  <span>{labels[c.company_stage]}</span>
                  <span>融资：{labels[c.financing_stage]}</span>
                </div>
                <small>
                  更新于 {new Date(c.updated_at).toLocaleDateString("zh-CN")}
                </small>
              </Link>
            ))}
          </div>
        )}
        {result.total > 20 && (
          <div className="pagination">
            <button
              className="refresh"
              disabled={busy || result.offset === 0}
              onClick={async () => {
                setBusy(true);
                try {
                  setResult(await pageResult(Math.max(0, result.offset - 20)));
                } catch (e) {
                  fail(e);
                } finally {
                  setBusy(false);
                }
              }}
            >
              上一页
            </button>
            <span>
              {result.offset + 1}–{Math.min(result.offset + 20, result.total)} /{" "}
              {result.total}
            </span>
            <button
              className="refresh"
              disabled={busy || result.offset + 20 >= result.total}
              onClick={async () => {
                setBusy(true);
                try {
                  setResult(await pageResult(result.offset + 20));
                } catch (e) {
                  fail(e);
                } finally {
                  setBusy(false);
                }
              }}
            >
              下一页
            </button>
          </div>
        )}
      </section>
    </>
  );
}
