"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CatalogShell } from "@/components/catalog-shell";
import { api, type Identity } from "@/lib/api";
import {
  labels,
  type Source,
  type Taxonomy,
  type ImportJob,
} from "@/lib/catalog";
export default function Page() {
  return (
    <CatalogShell title="公共数据维护">
      {(identity) =>
        identity.can_curate_public_data ? (
          <Maintenance identity={identity} />
        ) : (
          <p className="empty-state">
            公共数据发布需要部署管理员授予的公共数据维护员权限，机构管理员不会自动获得此权限。
          </p>
        )
      }
    </CatalogShell>
  );
}
function Maintenance({ identity }: { identity: Identity }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [taxonomy, setTaxonomy] = useState<Taxonomy>({
    industries: [],
    technologies: [],
  });
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    const [s, t, j] = await Promise.all([
      api<Source[]>("catalog/sources", { signal }),
      api<Taxonomy>("catalog/taxonomy", { signal }),
      api<ImportJob[]>("catalog/imports", { signal }),
    ]);
    setSources(s);
    setTaxonomy(t);
    setJobs(j);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).catch((e) => {
      if (e.name !== "AbortError") setError(e.message);
    });
    return () => controller.abort();
  }, [load]);
  const pending = jobs.some(
    (j) => j.state === "queued" || j.state === "running",
  );
  useEffect(() => {
    if (!pending) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      api<ImportJob[]>("catalog/imports", { signal: controller.signal })
        .then((data) => {
          setJobs(data);
          if (data.every((j) => j.state !== "queued" && j.state !== "running"))
            void load(controller.signal).catch((e) => {
              if (e.name !== "AbortError") setError(e.message);
            });
        })
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        });
    }, 1500);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [pending, load]);
  async function write(path: string, payload: unknown, method = "POST") {
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
      setNotice(
        path === "catalog/imports"
          ? "导入任务已排队，完成后逐行显示结果"
          : "公共数据维护记录已保存",
      );
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
      return false;
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="workspace-heading">
        <div>
          <div className="eyebrow">CURATED PUBLIC DATA</div>
          <h1>公共数据维护</h1>
          <p>
            在明确的来源许可范围内发布共享档案，私有项目资料不会自动进入这里。
          </p>
        </div>
        <Link href="/companies" className="refresh">
          查看企业情报 →
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
        <h2>登记公开来源</h2>
        <form
          className="catalog-form"
          onSubmit={async (e) => {
            e.preventDefault();
            const form = e.currentTarget;
            const data = new FormData(form);
            if (
              await write("catalog/sources", {
                source_name: data.get("source_name"),
                source_type: data.get("source_type"),
                source_url: data.get("source_url") || null,
                publisher: data.get("publisher") || null,
                license_type: data.get("license_type"),
                permitted_use: data.get("permitted_use"),
                reliability_level: data.get("reliability_level"),
                public_confirmed: true,
              })
            )
              form.reset();
          }}
        >
          <label>
            来源名称
            <input name="source_name" required maxLength={200} />
          </label>
          <label>
            来源类型
            <select name="source_type">
              <option value="manual">人工整理</option>
              <option value="official">企业官网</option>
              <option value="announcement">公告</option>
              <option value="patent">专利</option>
              <option value="licensed_api">授权 API</option>
            </select>
          </label>
          <label>
            原始来源 URL
            <input
              name="source_url"
              type="url"
              maxLength={2000}
              placeholder="真实来源请填写可定位的 HTTP(S) 地址"
            />
          </label>
          <label>
            发布方
            <input name="publisher" maxLength={200} />
          </label>
          <label>
            许可类型
            <select name="license_type">
              <option value="synthetic_demo">合成演示资料（非真实企业）</option>
              <option value="authorized">已获得共享授权</option>
              <option value="public_licensed">明确许可的公共资料</option>
            </select>
          </label>
          <label>
            来源可靠性
            <select name="reliability_level">
              <option value="unknown">未知</option>
              <option value="primary">一手来源</option>
              <option value="secondary">二手来源</option>
            </select>
          </label>
          <label className="wide">
            允许用途 / 授权范围
            <textarea
              name="permitted_use"
              required
              minLength={5}
              maxLength={3000}
              placeholder="说明为何可以进入公共数据域，以及允许的使用和共享范围"
            />
          </label>
          <label className="checkbox-label wide">
            <input type="checkbox" required />
            我已核对授权范围，确认资料可以在平台所有有效机构之间共享，不包含未获授权的机构私有资料。
          </label>
          <button className="primary" disabled={busy}>
            登记来源
          </button>
        </form>
        <p className="form-note">
          系统记录维护员声明，不自动判断法律授权是否成立；公开可访问不等于可任意采集和转售。
        </p>
        <details>
          <summary>已登记来源（{sources.length}）</summary>
          {sources.map((s) => (
            <article className="source-card" key={s.id}>
              <strong>{s.source_name}</strong>
              <p>{s.permitted_use}</p>
              <small>
                {s.license_type} ·{" "}
                {new Date(s.accessed_at).toLocaleString("zh-CN")}
              </small>
            </article>
          ))}
        </details>
      </section>
      <section className="workspace-panel">
        <h2>产业链与技术分类</h2>
        <form
          className="catalog-form"
          onSubmit={async (e) => {
            e.preventDefault();
            const form = e.currentTarget;
            const data = new FormData(form);
            const kind = String(data.get("kind"));
            if (
              await write(`catalog/taxonomy/${kind}`, {
                name: data.get("name"),
                description: data.get("description") || "",
                parent_id: data.get("parent_id") || null,
                aliases: String(data.get("aliases") || "")
                  .split("|")
                  .map((v) => v.trim())
                  .filter(Boolean),
              })
            )
              form.reset();
          }}
        >
          <label>
            分类类型
            <select name="kind">
              <option value="industries">产业节点</option>
              <option value="technologies">技术路线</option>
            </select>
          </label>
          <label>
            分类名称
            <input name="name" required maxLength={100} />
          </label>
          <label>
            上级分类 ID（可选）
            <input name="parent_id" placeholder="须与分类类型一致" />
          </label>
          <label>
            技术别名（| 分隔）
            <input name="aliases" />
          </label>
          <label className="wide">
            分类说明
            <textarea name="description" maxLength={2000} />
          </label>
          <button className="primary" disabled={busy}>
            创建分类
          </button>
        </form>
        <div className="taxonomy-map">
          {taxonomy.industries.map((n) => (
            <article
              key={n.id}
              style={{ marginLeft: Math.min(n.level - 1, 4) * 14 }}
            >
              <strong>{n.name}</strong>
              <small>
                层级 {n.level} · {n.id}
              </small>
              <p>{n.description || "暂无分类说明"}</p>
            </article>
          ))}
        </div>
        <div className="company-tags">
          {taxonomy.technologies.map((t) => (
            <span key={t.id}>
              {t.name}
              {t.aliases.length ? ` · ${t.aliases.join(" / ")}` : ""}
            </span>
          ))}
        </div>
      </section>
      <section className="workspace-panel">
        <h2>CSV / XLSX 企业批量导入</h2>
        <p className="form-note">
          UTF-8 CSV 或单工作表 XLSX，每次最多 200 行、1 MiB。英文列名以仓库
          examples/companies.csv 为模板；空字段保持未知。XLSX
          不接受公式、宏或外链。疑似重复进入人工核实，不自动合并。
        </p>
        <form
          className="catalog-form"
          onSubmit={async (e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            const file = data.get("file");
            setError("");
            if (
              !(file instanceof File) ||
              !file.size ||
              file.size > 1024 * 1024
            ) {
              setError("请选择不超过 1 MiB 的 CSV 或 XLSX 文件");
              return;
            }
            const format = file.name.toLowerCase().endsWith(".csv")
              ? "csv"
              : file.name.toLowerCase().endsWith(".xlsx")
                ? "xlsx"
                : null;
            if (!format) {
              setError("仅支持 CSV / XLSX");
              return;
            }
            try {
              const bytes = new Uint8Array(await file.arrayBuffer());
              let binary = "";
              for (let i = 0; i < bytes.length; i += 32768)
                binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
              await write("catalog/imports", {
                source_id: data.get("source_id"),
                reason: data.get("reason"),
                format,
                content_base64: btoa(binary),
                idempotency_key: crypto.randomUUID(),
                public_confirmed: true,
              });
            } catch (e) {
              setError(e instanceof Error ? e.message : "文件读取失败");
            }
          }}
        >
          <label>
            导入文件
            <input name="file" type="file" accept=".csv,.xlsx" required />
          </label>
          <label>
            导入来源
            <select name="source_id" required>
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.source_name}
                </option>
              ))}
            </select>
          </label>
          <label className="wide">
            导入原因
            <input name="reason" required minLength={3} maxLength={1000} />
          </label>
          <label className="checkbox-label wide">
            <input type="checkbox" required />
            确认本文件内容可以在已登记许可范围内发布为公共企业资料。
          </label>
          <button className="primary" disabled={busy || !sources.length}>
            提交导入任务
          </button>
        </form>
        <h3>我的导入任务</h3>
        {!jobs.length ? (
          <p className="empty-state">暂无导入任务。</p>
        ) : (
          jobs.map((j) => (
            <article className="source-card import-job" key={j.id}>
              <div className="section-heading">
                <strong>{labels[j.state]}</strong>
                <small>
                  执行 {j.attempts} 次 ·{" "}
                  {new Date(j.created_at).toLocaleString("zh-CN")}
                </small>
              </div>
              {j.result.counts && (
                <p className="import-counts">
                  {Object.entries(j.result.counts).map(([key, count]) => (
                    <span key={key}>
                      {labels[key]}：{count}
                    </span>
                  ))}
                </p>
              )}
              {j.error_code && (
                <p className="error-message">
                  任务失败：{j.error_code}
                  。请核对文件表头、格式与维护权限；原始错误和文件内容不会写入日志。
                </p>
              )}
              {j.state === "failed" && j.attempts < 3 && (
                <button
                  className="refresh"
                  disabled={busy}
                  onClick={() =>
                    write(`catalog/imports/${j.id}/retry`, {}, "POST")
                  }
                >
                  重试失败任务
                </button>
              )}
              {j.result.rows && (
                <details>
                  <summary>逐行结果</summary>
                  <ul className="import-rows">
                    {j.result.rows.map((row) => (
                      <li key={row.row}>
                        第 {row.row} 行 · {labels[row.status]}{" "}
                        {row.company_id && (
                          <Link href={`/companies/${row.company_id}`}>
                            查看档案 →
                          </Link>
                        )}
                        {row.candidate_ids?.map((id) => (
                          <Link key={id} href={`/companies/${id}`}>
                            核对候选 →
                          </Link>
                        ))}
                        {row.code && ` · ${row.code}`}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </article>
          ))
        )}
      </section>
    </>
  );
}
