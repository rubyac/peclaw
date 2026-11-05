"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { CatalogShell } from "@/components/catalog-shell";
import { api } from "@/lib/api";
import { labels, type SearchResult, type Taxonomy } from "@/lib/catalog";
export default function Page() {
  return <CatalogShell title="产业地图">{() => <IndustryMap />}</CatalogShell>;
}
function IndustryMap() {
  const [taxonomy, setTaxonomy] = useState<Taxonomy>({
    industries: [],
    technologies: [],
  });
  const [selection, setSelection] = useState<{
    id: string;
    name: string;
    kind: "industry" | "technology";
  }>();
  const [result, setResult] = useState<SearchResult>();
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<Taxonomy>("catalog/taxonomy", { signal: controller.signal })
      .then(setTaxonomy)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!selection) return;
    const controller = new AbortController();
    setError("");
    setResult(undefined);
    api<SearchResult>(
      `companies?${selection.kind}_id=${selection.id}&limit=50`,
      { signal: controller.signal },
    )
      .then(setResult)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [selection]);
  return (
    <>
      <div className="workspace-heading">
        <div>
          <div className="eyebrow">INDUSTRY LANDSCAPE</div>
          <h1>产业链与技术地图</h1>
          <p>根据已维护的分类和企业关联浏览，不代表完整产业覆盖。</p>
        </div>
        <Link href="/companies" className="refresh">
          查看全部企业 →
        </Link>
      </div>
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      <section className="workspace-panel">
        <h2>产业链节点</h2>
        {!taxonomy.industries.length ? (
          <p className="empty-state">暂无产业节点，需由公共数据维护员登记。</p>
        ) : (
          <div className="taxonomy-map">
            {taxonomy.industries.map((node) => (
              <article
                key={node.id}
                style={{ marginLeft: Math.min(node.level - 1, 4) * 14 }}
              >
                <button
                  className="inline-button"
                  onClick={() =>
                    setSelection({
                      id: node.id,
                      name: node.name,
                      kind: "industry",
                    })
                  }
                >
                  {node.name} →
                </button>
                <p>{node.description || "暂无分类说明"}</p>
              </article>
            ))}
          </div>
        )}
        <h2>技术路线</h2>
        <div className="company-tags">
          {taxonomy.technologies.map((t) => (
            <button
              className="refresh"
              key={t.id}
              onClick={() =>
                setSelection({ id: t.id, name: t.name, kind: "technology" })
              }
            >
              {t.name}
            </button>
          ))}
        </div>
      </section>
      {selection && (
        <section className="workspace-panel">
          <div className="section-heading">
            <h2>{selection.name} · 已关联企业</h2>
            <span>
              {result ? `${result.total} 家；展示前 50 家` : "正在读取…"}
            </span>
          </div>
          {result?.items.length === 0 && (
            <p className="empty-state">
              此分类尚无企业关联，不据此判断产业中没有企业。
            </p>
          )}
          <div className="company-grid">
            {result?.items.map((c) => (
              <Link
                className="company-card"
                key={c.id}
                href={`/companies/${c.id}`}
              >
                <h3>{c.canonical_name}</h3>
                <p>{c.description || "企业简介未知"}</p>
                <div className="company-tags">
                  <span>{labels[c.listing_status]}</span>
                  <span>{labels[c.company_stage]}</span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
