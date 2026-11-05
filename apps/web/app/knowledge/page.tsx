"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Identity, type Project } from "@/lib/api";
import {
  documentStates,
  fileErrors,
  filePayload,
  locationLabel,
  type PrivateDocument,
  type Citation,
  type EligibleMember,
  type Permissions,
  type KnowledgeSearch,
} from "@/lib/knowledge";

const pendingStates = [
  "uploading",
  "uploaded",
  "validating",
  "parsing",
  "chunking",
  "embedding",
  "deleting",
];
export default function Page() {
  const router = useRouter();
  const [identity, setIdentity] = useState<Identity>();
  const [org, setOrg] = useState("");
  const [project, setProject] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [documents, setDocuments] = useState<PrivateDocument[]>([]);
  const [members, setMembers] = useState<EligibleMember[]>([]);
  const [detail, setDetail] = useState<PrivateDocument>();
  const [version, setVersion] = useState(1);
  const [offset, setOffset] = useState(0);
  const [chunks, setChunks] = useState<Citation[]>([]);
  const [results, setResults] = useState<KnowledgeSearch>();
  const [permissionDoc, setPermissionDoc] = useState<PrivateDocument>();
  const [permissions, setPermissions] = useState<Permissions>();
  const [permissionScope, setPermissionScope] = useState<
    "project" | "restricted"
  >("project");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const target = useRef<{
    project?: string;
    document?: string;
    version?: number;
  }>({});
  const selectedProject = projects.find((p) => p.id === project);
  const writable = !!selectedProject?.can_write;
  const base = `organizations/${org}/projects/${project}/documents`;
  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else if (e instanceof Error && e.name !== "AbortError")
        setError(e.message);
    },
    [router],
  );
  function clearScope() {
    setDocuments([]);
    setMembers([]);
    setDetail(undefined);
    setChunks([]);
    setResults(undefined);
    setPermissionDoc(undefined);
    setPermissions(undefined);
    setNotice("");
    setError("");
    setOffset(0);
  }
  useEffect(() => {
    const control = new AbortController();
    api<Identity>("auth/me", { signal: control.signal })
      .then((data) => {
        setIdentity(data);
        const params = new URLSearchParams(window.location.search);
        const desired = params.get("organization");
        const selected = desired
          ? data.organizations.find((o) => o.id === desired)
          : data.organizations[0];
        if (!selected) {
          setError("没有访问此机构的权限");
          return;
        }
        setOrg(selected.id);
        target.current = {
          project: params.get("project") || undefined,
          document: params.get("document") || undefined,
          version: Number(params.get("version")) || undefined,
        };
      })
      .catch(fail);
    return () => control.abort();
  }, [fail]);
  useEffect(() => {
    if (!org) return;
    const control = new AbortController();
    setLoading(true);
    api<Project[]>(`organizations/${org}/projects`, { signal: control.signal })
      .then((rows) => {
        setProjects(rows);
        const desired = target.current.project;
        if (desired && !rows.some((p) => p.id === desired)) {
          setProject("");
          setError("目标项目不存在或未授权");
          return;
        }
        setProject(desired || rows[0]?.id || "");
        target.current.project = undefined;
      })
      .catch(fail)
      .finally(() => {
        if (!control.signal.aborted) setLoading(false);
      });
    return () => control.abort();
  }, [org, fail]);
  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!project) return;
      const rows = await api<PrivateDocument[]>(
        `${base}?include_deleted=${includeDeleted && writable}`,
        { signal },
      );
      setDocuments(rows);
      if (writable)
        setMembers(
          await api<EligibleMember[]>(
            `organizations/${org}/projects/${project}/knowledge-members`,
            { signal },
          ),
        );
      else setMembers([]);
      return rows;
    },
    [project, base, org, includeDeleted, writable],
  );
  useEffect(() => {
    if (!project) return;
    const control = new AbortController();
    setLoading(true);
    setDocuments([]);
    setDetail(undefined);
    setChunks([]);
    setResults(undefined);
    setPermissionDoc(undefined);
    setError("");
    load(control.signal)
      .then(async (rows) => {
        const desired = target.current.document;
        if (desired) {
          target.current.document = undefined;
          const doc = rows?.find((d) => d.id === desired && d.can_read);
          if (!doc) {
            setError("目标文档不存在或未授权");
            return;
          }
          const full = await api<PrivateDocument>(`${base}/${doc.id}`, {
            signal: control.signal,
          });
          setDetail(full);
          setVersion(target.current.version || full.current_version);
          target.current.version = undefined;
        }
      })
      .catch(fail)
      .finally(() => {
        if (!control.signal.aborted) setLoading(false);
      });
    return () => control.abort();
  }, [project, load, base, fail]);
  const pending = documents.some(
    (d) => d.current && pendingStates.includes(d.current.status),
  );
  useEffect(() => {
    if (!pending || !project) return;
    const control = new AbortController();
    const timer = setInterval(() => {
      api<PrivateDocument[]>(
        `${base}?include_deleted=${includeDeleted && writable}`,
        { signal: control.signal },
      )
        .then(async (rows) => {
          // Refresh selected metadata before ending polling; otherwise the last
          // list update cancels its own detail request when pending becomes false.
          if (detail) {
            const row = rows.find((d) => d.id === detail.id);
            if (!row?.can_read) {
              setDetail(undefined);
              setChunks([]);
            } else if (
              row.current?.status !== detail.current?.status ||
              row.revision !== detail.revision
            ) {
              setDetail(
                await api<PrivateDocument>(`${base}/${detail.id}`, {
                  signal: control.signal,
                }),
              );
            }
          }
          setDocuments(rows);
        })
        .catch(fail);
    }, 1500);
    return () => {
      clearInterval(timer);
      control.abort();
    };
  }, [pending, project, base, includeDeleted, writable, detail, fail]);
  const viewed = detail?.versions?.find((v) => v.number === version);
  useEffect(() => {
    setChunks([]);
    if (!detail || viewed?.status !== "indexed") return;
    const control = new AbortController();
    api<Citation[]>(
      `${base}/${detail.id}/chunks?version=${version}&offset=${offset}&limit=50`,
      { signal: control.signal },
    )
      .then(setChunks)
      .catch((e) => {
        fail(e);
        if (e instanceof ApiError && (e.status === 403 || e.status === 404))
          setDetail(undefined);
      });
    return () => control.abort();
  }, [base, detail, viewed?.status, version, offset, fail]);
  async function openDoc(doc: PrivateDocument) {
    setBusy(true);
    setError("");
    try {
      const full = await api<PrivateDocument>(`${base}/${doc.id}`);
      setDetail(full);
      setVersion(full.current_version);
      setOffset(0);
    } catch (e) {
      fail(e);
      setDetail(undefined);
    } finally {
      setBusy(false);
    }
  }
  async function openPermissions(doc: PrivateDocument) {
    setBusy(true);
    setError("");
    try {
      const values = await api<Permissions>(`${base}/${doc.id}/permissions`);
      setPermissionDoc(doc);
      setPermissions(values);
      setPermissionScope(values.access_scope);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function mutate(path: string, method: string, data: unknown) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(
        path,
        { method, body: JSON.stringify(data) },
        identity?.csrf_token,
      );
      await load();
      setNotice("操作已保存");
      return true;
    } catch (e) {
      fail(e);
      return false;
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="shell">
      <aside className="sidebar">
        <Link className="brand" href="/">
          <span className="brand-icon">P</span>PEClaw
          <span className="brand-dot">.</span>
        </Link>
        <div className="workspace-label">PRIVATE KNOWLEDGE</div>
        <nav aria-label="私有知识导航">
          <Link href="/evaluation">
            ◷ <span>评测与反馈</span>
          </Link>
          <Link href="/reports">
            ▧ <span>报告与审核</span>
          </Link>
          <Link href="/agents">
            ◉ <span>AI 研究工作台</span>
          </Link>
          <Link href="/">
            ▦ <span>工作台</span>
          </Link>
          <Link href="/projects">
            ◇ <span>投资项目</span>
          </Link>
          <Link className="active" href="/knowledge">
            ▤ <span>私有知识库</span>
          </Link>
          <Link href="/companies">
            ◈ <span>公共企业情报</span>
          </Link>
          <Link href="/account">
            ◎ <span>账号安全</span>
          </Link>
        </nav>
        <div className="sidebar-note">
          机构与项目权限隔离<div>原文可定位 · 资料不外发给模型</div>
        </div>
      </aside>
      <main className="workspace-main">
        <header>
          <span>机构私有知识库</span>
          <span>{identity?.user.full_name}</span>
        </header>
        <div className="workspace-heading">
          <div>
            <div className="eyebrow">INSTITUTIONAL MEMORY</div>
            <h1>私有知识库</h1>
            <p>保存授权资料、检索历史经验，让引用回到原文。</p>
          </div>
        </div>
        {error && (
          <p role="alert" className="error-message">
            {error}
            <button className="inline-button" onClick={() => location.reload()}>
              重新加载
            </button>
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
              disabled={busy || loading || !identity}
              onChange={(e) => {
                clearScope();
                setProjects([]);
                setProject("");
                setOrg(e.target.value);
              }}
            >
              {identity?.organizations.map((o) => (
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
                clearScope();
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
              : "暂无可访问的项目，请先创建项目或获得授权。"}
          </p>
        ) : (
          <>
            {writable && (
              <section className="workspace-panel">
                <h2>上传项目资料</h2>
                <p className="form-note">
                  PDF、DOCX、XLSX、PPTX、TXT、Markdown；每份最多 10
                  MiB。本地解析与中文词向量索引，不调用外部模型。扫描 PDF 需先做
                  OCR。
                </p>
                <form
                  className="catalog-form"
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const form = e.currentTarget;
                    const data = new FormData(form);
                    const file = data.get("file");
                    if (!(file instanceof File)) return;
                    setBusy(true);
                    setError("");
                    try {
                      const result = await api<PrivateDocument>(
                        base,
                        {
                          method: "POST",
                          body: JSON.stringify({
                            ...(await filePayload(file)),
                            title: data.get("title") || file.name,
                            access_scope: data.get("access_scope"),
                            reader_ids: [],
                          }),
                        },
                        identity?.csrf_token,
                      );
                      await load();
                      setDetail(result);
                      setVersion(result.current_version);
                      setNotice("原文已保存，正在后台解析与索引");
                      form.reset();
                    } catch (e) {
                      fail(e);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <label>
                    文档名称
                    <input name="title" maxLength={200} required />
                  </label>
                  <label>
                    文档文件
                    <input
                      name="file"
                      type="file"
                      accept=".pdf,.docx,.xlsx,.pptx,.txt,.md"
                      required
                    />
                  </label>
                  <label>
                    上传可见范围
                    <select aria-label="上传可见范围" name="access_scope">
                      <option value="project">当前项目成员可读</option>
                      <option value="restricted">仅本人，之后可单独授权</option>
                    </select>
                  </label>
                  <button className="primary" disabled={busy}>
                    上传并建立索引
                  </button>
                </form>
              </section>
            )}
            <section className="workspace-panel">
              <div className="section-heading">
                <h2>
                  项目文档 <span className="count">{documents.length}</span>
                </h2>
                {writable && (
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={includeDeleted}
                      onChange={(e) => setIncludeDeleted(e.target.checked)}
                      disabled={busy}
                    />
                    显示删除记录
                  </label>
                )}
              </div>
              <p className="form-note">
                最多显示 100
                份文档。项目管理员可见未授权受限文档的编号以管理权限，原文件名和内容仍隐藏。
              </p>
              {loading ? (
                <p className="empty-state">正在加载…</p>
              ) : !documents.length ? (
                <p className="empty-state">暂无获授权文档。</p>
              ) : (
                documents.map((doc) => (
                  <article className="private-doc-row" key={doc.id}>
                    <div>
                      <strong>{doc.title}</strong>
                      <p>
                        {doc.current
                          ? `v${doc.current.number} · ${doc.current.filename} · ${documentStates[doc.current.status] || doc.current.status}`
                          : "内容受限"}
                      </p>
                      <small>
                        {doc.access_scope === "restricted"
                          ? "单独授权"
                          : "项目内共享"}{" "}
                        · 文档编号 {doc.id}
                      </small>
                      {doc.current?.error_code && (
                        <p className="error-message">
                          {fileErrors[doc.current.error_code] ||
                            "处理失败，请核对文件后重试。"}
                        </p>
                      )}
                    </div>
                    <div className="catalog-actions">
                      {doc.can_read && (
                        <button
                          className="refresh"
                          disabled={busy}
                          onClick={() => openDoc(doc)}
                        >
                          查看原文片段
                        </button>
                      )}
                      {doc.can_manage && !doc.is_deleted && (
                        <button
                          className="refresh"
                          disabled={busy}
                          onClick={() => openPermissions(doc)}
                        >
                          文档权限
                        </button>
                      )}
                      {doc.current?.status === "failed" &&
                        doc.can_write &&
                        doc.current.attempts < 3 && (
                          <button
                            className="refresh"
                            disabled={busy}
                            onClick={() =>
                              mutate(`${base}/${doc.id}/retry`, "POST", {
                                expected_revision: doc.revision,
                              })
                            }
                          >
                            重试处理
                          </button>
                        )}
                      {doc.is_deleted &&
                        doc.can_manage &&
                        doc.current?.status === "deleting" && (
                          <button
                            className="refresh"
                            disabled={busy}
                            onClick={() =>
                              mutate(`${base}/${doc.id}/retry`, "POST", {
                                expected_revision: doc.revision,
                              })
                            }
                          >
                            重试原文清理
                          </button>
                        )}
                    </div>
                  </article>
                ))
              )}
            </section>
            {detail && (
              <section className="workspace-panel">
                <div className="section-heading">
                  <h2>{detail.title} · 原文定位</h2>
                  <button
                    className="inline-button"
                    onClick={() => {
                      setDetail(undefined);
                      setChunks([]);
                    }}
                  >
                    关闭预览
                  </button>
                </div>
                <div className="knowledge-version">
                  <label>
                    查看版本
                    <select
                      aria-label="查看版本"
                      value={version}
                      onChange={(e) => {
                        setVersion(Number(e.target.value));
                        setOffset(0);
                      }}
                    >
                      {detail.versions?.map((v) => (
                        <option key={v.id} value={v.number}>
                          v{v.number} · {v.filename} ·{" "}
                          {documentStates[v.status]}
                        </option>
                      ))}
                    </select>
                  </label>
                  {viewed && (
                    <a
                      className="refresh"
                      href={`/api/${base}/${detail.id}/download?version=${version}`}
                      download
                    >
                      下载此版本原文件
                    </a>
                  )}
                </div>
                <p className="form-note">
                  {viewed
                    ? `${documentStates[viewed.status]} · ${viewed.chunk_count} 个片段 · 校验摘要 ${viewed.content_hash.slice(0, 16)}…`
                    : "版本尚未加载"}
                  。当前版本未就绪时不会用旧版本冒充当前结果，历史版本可在此查看。
                </p>
                {viewed?.error_code && (
                  <p className="error-message">
                    {fileErrors[viewed.error_code] || "当前版本处理失败"}
                  </p>
                )}
                {viewed?.status !== "indexed" ? (
                  <p className="empty-state">
                    {viewed?.status === "failed"
                      ? "此版本尚未建立索引，可下载原文件核对或重试。"
                      : "正在准备当前版本的原文片段…"}
                  </p>
                ) : (
                  chunks.map((c) => (
                    <article className="citation-card" key={c.chunk_id}>
                      <div className="section-heading">
                        <strong>{locationLabel(c)}</strong>
                        <small>
                          v{c.version_number} · 片段{" "}
                          {c.content_hash.slice(0, 10)}
                        </small>
                      </div>
                      <blockquote>{c.excerpt}</blockquote>
                    </article>
                  ))
                )}
                {viewed && viewed.chunk_count > 50 && (
                  <div className="pagination">
                    <button
                      className="refresh"
                      disabled={offset === 0}
                      onClick={() => setOffset(Math.max(0, offset - 50))}
                    >
                      上一页片段
                    </button>
                    <span>
                      {offset + 1}–{Math.min(offset + 50, viewed.chunk_count)} /{" "}
                      {viewed.chunk_count}
                    </span>
                    <button
                      className="refresh"
                      disabled={offset + 50 >= viewed.chunk_count}
                      onClick={() => setOffset(offset + 50)}
                    >
                      下一页片段
                    </button>
                  </div>
                )}
                {detail.can_write && (
                  <details>
                    <summary className="form-section-title">上传新版本</summary>
                    <form
                      className="review-form"
                      onSubmit={async (e) => {
                        e.preventDefault();
                        const form = e.currentTarget;
                        const data = new FormData(form);
                        const file = data.get("file");
                        if (!(file instanceof File)) return;
                        setBusy(true);
                        setError("");
                        try {
                          const result = await api<PrivateDocument>(
                            `${base}/${detail.id}/versions`,
                            {
                              method: "POST",
                              body: JSON.stringify({
                                ...(await filePayload(file)),
                                expected_revision: detail.revision,
                              }),
                            },
                            identity?.csrf_token,
                          );
                          await load();
                          setDetail(result);
                          setVersion(result.current_version);
                          setOffset(0);
                          setNotice("新版本已保存，旧版本保留");
                          form.reset();
                        } catch (e) {
                          fail(e);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      <label>
                        新版本文件
                        <input
                          name="file"
                          type="file"
                          required
                          accept=".pdf,.docx,.xlsx,.pptx,.txt,.md"
                        />
                      </label>
                      <button className="primary" disabled={busy}>
                        保存新版本
                      </button>
                    </form>
                  </details>
                )}
                {detail.can_write && (
                  <details>
                    <summary className="form-section-title danger">
                      删除文档及全部版本
                    </summary>
                    <form
                      className="review-form"
                      onSubmit={async (e) => {
                        e.preventDefault();
                        if (
                          await mutate(`${base}/${detail.id}`, "DELETE", {
                            expected_revision: detail.revision,
                          })
                        ) {
                          setDetail(undefined);
                          setChunks([]);
                          setResults(undefined);
                        }
                      }}
                    >
                      <label className="checkbox-label">
                        <input type="checkbox" required />
                        确认移除全部索引并清理原文，删除后无法通过应用恢复。
                      </label>
                      <button className="refresh danger" disabled={busy}>
                        确认删除文档
                      </button>
                    </form>
                  </details>
                )}
              </section>
            )}
            {permissionDoc && permissions && (
              <section className="workspace-panel">
                <div className="section-heading">
                  <h2>文档权限 · {permissionDoc.title}</h2>
                  <button
                    className="inline-button"
                    onClick={() => setPermissionDoc(undefined)}
                  >
                    关闭权限
                  </button>
                </div>
                <p className="form-note">
                  受限文档编号 {permissionDoc.id}
                  。管理权限不等于已读取内容；明确授权后才可检索或下载。
                </p>
                <form
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const data = new FormData(e.currentTarget);
                    const grants = members
                      .map((m) => ({
                        user_id: m.user_id,
                        role: String(data.get(`grant_${m.user_id}`) || "none"),
                      }))
                      .filter((g) => g.role !== "none");
                    if (
                      await mutate(
                        `${base}/${permissionDoc.id}/permissions`,
                        "PUT",
                        {
                          expected_revision: permissions.revision,
                          access_scope: permissionScope,
                          grants,
                        },
                      )
                    ) {
                      setPermissionDoc(undefined);
                      setDetail(undefined);
                      setChunks([]);
                      setResults(undefined);
                    }
                  }}
                >
                  <label>
                    文档可见范围
                    <select
                      aria-label="文档可见范围"
                      value={permissionScope}
                      onChange={(e) =>
                        setPermissionScope(
                          e.target.value as "project" | "restricted",
                        )
                      }
                    >
                      <option value="project">当前项目成员可读</option>
                      <option value="restricted">仅指定成员可读</option>
                    </select>
                  </label>
                  {permissionScope === "restricted" && (
                    <div className="document-grants">
                      {members.map((m) => (
                        <label key={m.user_id}>
                          {m.full_name} · {m.email}
                          <select
                            aria-label={`${m.full_name} 文档权限`}
                            name={`grant_${m.user_id}`}
                            defaultValue={
                              permissions.grants.find(
                                (g) => g.user_id === m.user_id,
                              )?.role ||
                              (m.user_id === identity?.user.id
                                ? "editor"
                                : "none")
                            }
                          >
                            <option value="none">无权限</option>
                            <option value="reader">可读</option>
                            {m.can_edit && (
                              <option value="editor">可编辑</option>
                            )}
                          </select>
                        </label>
                      ))}
                    </div>
                  )}
                  <p className="form-note">
                    至少保留一名有项目编辑资格的文档编辑者。项目只读角色不会因文档授权获得上传或删除能力。
                  </p>
                  <button className="primary" disabled={busy}>
                    保存文档权限
                  </button>
                </form>
              </section>
            )}
            <section className="workspace-panel">
              <h2>检索机构知识</h2>
              <form
                className="knowledge-search"
                onSubmit={async (e) => {
                  e.preventDefault();
                  const data = new FormData(e.currentTarget);
                  setBusy(true);
                  setError("");
                  setResults(undefined);
                  try {
                    setResults(
                      await api<KnowledgeSearch>(
                        `organizations/${org}/knowledge/search`,
                        {
                          method: "POST",
                          body: JSON.stringify({
                            query: data.get("query"),
                            mode: data.get("mode"),
                            project_id: data.get("all_projects")
                              ? null
                              : project,
                            limit: 10,
                          }),
                        },
                        identity?.csrf_token,
                      ),
                    );
                  } catch (e) {
                    fail(e);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <label className="wide">
                  研究问题 / 关键词
                  <input
                    name="query"
                    required
                    maxLength={500}
                    placeholder="例如：项目盈利能力、客户验证或技术成熟度"
                  />
                </label>
                <label>
                  检索方式
                  <select aria-label="检索方式" name="mode">
                    <option value="hybrid">关键词 + 本地语义</option>
                    <option value="keyword">仅关键词</option>
                    <option value="semantic">仅本地语义</option>
                  </select>
                </label>
                <label className="checkbox-label">
                  <input type="checkbox" name="all_projects" />
                  搜索本机构内我有权限的全部项目
                </label>
                <button className="primary" disabled={busy}>
                  检索原文证据
                </button>
              </form>
              <p className="form-note">
                检索结果为授权原文，不代表事实已核验。语义匹配使用本地中文静态词向量，未调用外部生成模型。
              </p>
              {results && (
                <>
                  <p className="form-note">
                    {results.limitations}
                    {!results.semantic_available &&
                      " 当前查询没有可用语义向量，请使用关键词或改写查询。"}
                  </p>
                  {!results.items.length ? (
                    <p className="empty-state">暂无授权范围内的匹配原文。</p>
                  ) : (
                    results.items.map((c, index) => (
                      <article
                        className="citation-card search-citation"
                        key={c.chunk_id}
                      >
                        <div className="section-heading">
                          <strong>
                            [{index + 1}] {c.document_title} · v
                            {c.version_number}
                          </strong>
                          <small>
                            {c.matched_by
                              .map((v) => (v === "keyword" ? "关键词" : "语义"))
                              .join(" + ")}
                          </small>
                        </div>
                        <p className="form-note">{locationLabel(c)}</p>
                        <blockquote>{c.excerpt}</blockquote>
                        <div className="catalog-actions">
                          <a
                            className="back-link"
                            href={`/knowledge?organization=${org}&project=${c.project_id}&document=${c.document_id}&version=${c.version_number}`}
                          >
                            定位文档版本 →
                          </a>
                          <a
                            className="back-link"
                            href={`/api/organizations/${org}/projects/${c.project_id}/documents/${c.document_id}/download?version=${c.version_number}`}
                            download
                          >
                            下载原文件
                          </a>
                        </div>
                      </article>
                    ))
                  )}
                </>
              )}
            </section>
          </>
        )}
        <footer>
          <span>PEClaw · 机构私有知识</span>
          <span>仅检索授权资料 · 原文不作为系统指令</span>
        </footer>
      </main>
    </div>
  );
}
