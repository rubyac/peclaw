"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  type Audit,
  type Identity,
  type Member,
  type Project,
} from "@/lib/api";

type View = "projects" | "members" | "audit" | "account";
const roles: Record<string, string> = {
  owner: "机构所有者",
  admin: "机构管理员",
  member: "成员",
  viewer: "只读",
  manager: "项目管理员",
  editor: "可编辑",
};
const titles: Record<View, string> = {
  projects: "投资项目",
  members: "机构成员",
  audit: "操作审计",
  account: "账号安全",
};

export function IdentityWorkspace({ view }: { view: View }) {
  const router = useRouter();
  const [identity, setIdentity] = useState<Identity>();
  const [orgId, setOrgId] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [logs, setLogs] = useState<Audit[]>([]);
  const [selected, setSelected] = useState<Project>();
  const [projectMembers, setProjectMembers] = useState<Member[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const organization = identity?.organizations.find((o) => o.id === orgId);
  const canManage =
    organization && ["owner", "admin"].includes(organization.role);
  const base = `organizations/${orgId}`;

  const fail = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) {
        router.replace("/login");
        return;
      }
      if (error instanceof Error && error.name !== "AbortError")
        setError(error.message);
    },
    [router],
  );

  useEffect(() => {
    const controller = new AbortController();
    api<Identity>("auth/me", { signal: controller.signal })
      .then((data) => {
        setIdentity(data);
        setOrgId(data.organizations[0]?.id || "");
        if (!data.organizations.length || view === "account") setLoading(false);
      })
      .catch(fail);
    return () => controller.abort();
  }, [fail, view]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!orgId || !identity || view === "account") return;
      if (view === "projects") {
        setProjects(await api<Project[]>(`${base}/projects`, { signal }));
        if (canManage)
          setMembers(await api<Member[]>(`${base}/members`, { signal }));
      } else if (canManage && view === "members")
        setMembers(await api<Member[]>(`${base}/members`, { signal }));
      else if (canManage && view === "audit")
        setLogs(await api<Audit[]>(`${base}/audit`, { signal }));
    },
    [base, orgId, identity, view, canManage],
  );

  useEffect(() => {
    if (!orgId || !identity || view === "account") return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setNotice("");
    setProjects([]);
    setMembers([]);
    setLogs([]);
    setSelected(undefined);
    setProjectMembers([]);
    load(controller.signal)
      .catch(fail)
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [orgId, identity, view, load, fail]);

  async function mutate(path: string, method: string, payload?: unknown) {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await api(
        path,
        {
          method,
          body: payload === undefined ? undefined : JSON.stringify(payload),
        },
        identity?.csrf_token,
      );
      await load();
      setNotice("操作已保存");
      return true;
    } catch (error) {
      fail(error);
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function openProject(project: Project) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const detail = await api<Project>(`${base}/projects/${project.id}`);
      const people = detail.can_manage_members
        ? await api<Member[]>(`${base}/projects/${project.id}/members`)
        : [];
      setSelected(detail);
      setProjectMembers(people);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    setBusy(true);
    setError("");
    try {
      await api("auth/logout", { method: "POST" }, identity?.csrf_token);
      router.replace("/login");
    } catch (error) {
      fail(error);
      setBusy(false);
    }
  }

  return (
    <div className="shell auth-shell">
      <aside className="sidebar">
        <Link href="/" className="brand">
          <span className="brand-icon">P</span>PEClaw
          <span className="brand-dot">.</span>
        </Link>
        <div className="workspace-label">PRIVATE WORKSPACE</div>
        <nav aria-label="工作空间导航">
          <Link href="/evaluation">
            ◷ <span>评测与反馈</span>
          </Link>
          <Link href="/reports">
            ▧ <span>报告与审核</span>
          </Link>
          <Link href="/agents">
            ◉ <span>AI 研究工作台</span>
          </Link>
          <Link href="/knowledge">
            ▤ <span>私有知识库</span>
          </Link>
          <Link href="/companies">
            ◈ <span>企业情报</span>
          </Link>
          <Link href="/">
            ▦ <span>工作台</span>
          </Link>
          {(["projects", "members", "audit", "account"] as View[]).map((v) => (
            <Link key={v} className={view === v ? "active" : ""} href={`/${v}`}>
              ◇ <span>{titles[v]}</span>
            </Link>
          ))}
        </nav>
        <div className="sidebar-note">
          机构数据按权限隔离<div>V1.0 · 身份与多租户</div>
        </div>
      </aside>
      <main className="workspace-main">
        <header>
          <span>{titles[view]}</span>
          <div className="user-menu">
            <span>{identity?.user.full_name}</span>
            <button
              className="refresh"
              onClick={logout}
              disabled={busy || !identity}
            >
              退出登录
            </button>
          </div>
        </header>
        <div className="workspace-heading">
          <div>
            <div className="eyebrow">YOUR AUTHORIZED WORKSPACE</div>
            <h1>{titles[view]}</h1>
            <p>只展示当前账号获授权的机构与项目。</p>
          </div>
          {identity && (
            <label className="org-picker">
              当前机构
              <select
                aria-label="当前机构"
                value={orgId}
                disabled={busy || loading || !identity.organizations.length}
                onChange={(e) => setOrgId(e.target.value)}
              >
                {identity.organizations.map((o) => (
                  <option value={o.id} key={o.id}>
                    {o.name} · {roles[o.role]}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {error && (
          <div className="error-message" role="alert">
            {error}
            <button className="inline-button" onClick={() => location.reload()}>
              重新加载
            </button>
          </div>
        )}
        {notice && (
          <p className="success-message" role="status">
            {notice}
          </p>
        )}
        {!identity ? (
          <p className="empty-state">
            {error ? "工作空间暂时无法加载。" : "正在验证登录状态…"}
          </p>
        ) : view !== "account" && !organization ? (
          <div className="empty-state">尚无可访问的机构，请联系管理员。</div>
        ) : loading && view !== "account" ? (
          <p className="empty-state">正在加载当前机构…</p>
        ) : (
          <>
            {view === "projects" && (
              <>
                {organization?.role !== "viewer" && (
                  <section className="workspace-panel">
                    <h2>创建投资项目</h2>
                    <form
                      className="project-form"
                      onSubmit={async (e) => {
                        e.preventDefault();
                        const form = e.currentTarget;
                        const data = new FormData(form);
                        if (
                          await mutate(`${base}/projects`, "POST", {
                            name: data.get("name"),
                            description: data.get("description"),
                          })
                        )
                          form.reset();
                      }}
                    >
                      <label>
                        项目名称
                        <input
                          name="name"
                          maxLength={150}
                          required
                          placeholder="例如：先进封装设备项目"
                        />
                      </label>
                      <label>
                        项目说明
                        <textarea
                          name="description"
                          maxLength={10000}
                          placeholder="记录项目研究范围，不填写未核验的结论"
                        />
                      </label>
                      <button className="primary" disabled={busy}>
                        创建项目
                      </button>
                    </form>
                  </section>
                )}
                <section className="workspace-panel">
                  <div className="section-heading">
                    <h2>
                      我的项目 <span className="count">{projects.length}</span>
                    </h2>
                    <span>机构权限与项目权限分别校验</span>
                  </div>
                  {!projects.length ? (
                    <p className="empty-state">
                      暂无获授权的项目。创建新项目，或联系项目管理员授权。
                    </p>
                  ) : (
                    <div className="project-list">
                      {projects.map((p) => (
                        <button
                          key={p.id}
                          className="project-row"
                          disabled={busy}
                          onClick={() => openProject(p)}
                        >
                          <span>
                            <strong>{p.name}</strong>
                            <small>{p.description || "暂无项目说明"}</small>
                          </span>
                          <span className="role-chip">
                            {roles[p.my_role] || "已授权"} →
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </section>
                {selected && (
                  <section className="workspace-panel" aria-label="项目详情">
                    <div className="section-heading">
                      <h2>{selected.name}</h2>
                      <button
                        className="inline-button"
                        onClick={() => setSelected(undefined)}
                      >
                        关闭详情
                      </button>
                    </div>
                    <p className="form-note">项目 ID：{selected.id}</p>
                    {selected.can_write ? (
                      <form
                        key={selected.id}
                        className="project-form"
                        onSubmit={async (e) => {
                          e.preventDefault();
                          const data = new FormData(e.currentTarget);
                          if (
                            await mutate(
                              `${base}/projects/${selected.id}`,
                              "PATCH",
                              {
                                name: data.get("name"),
                                description: data.get("description"),
                              },
                            )
                          ) {
                            await openProject(selected);
                          }
                        }}
                      >
                        <label>
                          修改项目名称
                          <input
                            name="name"
                            defaultValue={selected.name}
                            required
                            maxLength={150}
                          />
                        </label>
                        <label>
                          修改项目说明
                          <textarea
                            name="description"
                            defaultValue={selected.description}
                            maxLength={10000}
                          />
                        </label>
                        <button className="primary" disabled={busy}>
                          保存项目
                        </button>
                      </form>
                    ) : (
                      <p>{selected.description || "暂无项目说明"}</p>
                    )}
                    {selected.can_manage_members && (
                      <div className="project-permissions">
                        <h3>项目访问权限</h3>
                        <p className="form-note">
                          仅可授权当前机构的有效成员。机构管理员的授权变更也会记录审计。
                        </p>
                        <ul className="people-list">
                          {projectMembers.map((m) => (
                            <li key={m.user_id}>
                              <span>
                                {m.full_name} · {m.email}
                              </span>
                              <span>
                                {roles[m.role]}{" "}
                                <button
                                  className="inline-button danger"
                                  disabled={busy}
                                  onClick={async () => {
                                    if (
                                      await mutate(
                                        `${base}/projects/${selected.id}/members/${m.user_id}`,
                                        "DELETE",
                                      )
                                    )
                                      await openProject(selected);
                                  }}
                                >
                                  移除权限
                                </button>
                              </span>
                            </li>
                          ))}
                        </ul>
                        <form
                          className="member-form"
                          onSubmit={async (e) => {
                            e.preventDefault();
                            const data = new FormData(e.currentTarget);
                            if (
                              await mutate(
                                `${base}/projects/${selected.id}/members`,
                                "PUT",
                                {
                                  user_id: data.get("user_id"),
                                  role: data.get("role"),
                                },
                              )
                            )
                              await openProject(selected);
                          }}
                        >
                          <label>
                            机构成员
                            {canManage ? (
                              <select name="user_id" required>
                                {members
                                  .filter((m) => m.is_active)
                                  .map((m) => (
                                    <option key={m.user_id} value={m.user_id}>
                                      {m.full_name} · {m.email}
                                    </option>
                                  ))}
                              </select>
                            ) : (
                              <input
                                name="user_id"
                                required
                                placeholder="成员用户 ID"
                              />
                            )}
                          </label>
                          <label>
                            项目角色
                            <select name="role">
                              <option value="viewer">只读</option>
                              <option value="editor">可编辑</option>
                              <option value="manager">项目管理员</option>
                            </select>
                          </label>
                          <button className="primary" disabled={busy}>
                            保存项目权限
                          </button>
                        </form>
                      </div>
                    )}
                  </section>
                )}
              </>
            )}
            {view === "members" &&
              (canManage ? (
                <>
                  <section className="workspace-panel">
                    <h2>添加已开通账号</h2>
                    <p className="form-note">
                      新账号由部署管理员通过命令行开通；此处将已有账号加入当前机构。
                    </p>
                    <form
                      className="member-form"
                      onSubmit={async (e) => {
                        e.preventDefault();
                        const data = new FormData(e.currentTarget);
                        await mutate(`${base}/members`, "POST", {
                          email: data.get("email"),
                          role: data.get("role"),
                        });
                      }}
                    >
                      <label>
                        成员邮箱
                        <input
                          name="email"
                          type="email"
                          required
                          maxLength={254}
                        />
                      </label>
                      <label>
                        机构角色
                        <select name="role">
                          {[
                            "member",
                            "viewer",
                            "admin",
                            ...(organization?.role === "owner"
                              ? ["owner"]
                              : []),
                          ].map((r) => (
                            <option key={r} value={r}>
                              {roles[r]}
                            </option>
                          ))}
                        </select>
                      </label>
                      <button className="primary" disabled={busy}>
                        添加机构成员
                      </button>
                    </form>
                  </section>
                  <section className="workspace-panel">
                    <h2>机构成员与角色</h2>
                    <div className="member-list">
                      {members.map((m) => (
                        <MemberRow
                          key={`${m.user_id}-${m.role}-${m.is_active}`}
                          member={m}
                          owner={organization?.role === "owner"}
                          busy={busy}
                          onSave={async (role, active) => {
                            if (
                              (await mutate(
                                `${base}/members/${m.user_id}`,
                                "PATCH",
                                { role, is_active: active },
                              )) &&
                              m.user_id === identity.user.id
                            ) {
                              try {
                                setIdentity(await api<Identity>("auth/me"));
                              } catch (error) {
                                fail(error);
                              }
                            }
                          }}
                        />
                      ))}
                    </div>
                  </section>
                </>
              ) : (
                <p className="empty-state">
                  仅机构所有者与管理员可管理机构成员。
                </p>
              ))}
            {view === "audit" &&
              (canManage ? (
                <section className="workspace-panel">
                  <h2>最近操作记录</h2>
                  <p className="form-note">
                    显示当前机构最近 50 条记录，不包含密码、会话令牌或项目内容。
                  </p>
                  {!logs.length ? (
                    <p className="empty-state">当前机构暂无操作记录。</p>
                  ) : (
                    <div className="audit-list">
                      {logs.map((log) => (
                        <article key={log.id}>
                          <div>
                            <strong>{log.action}</strong>
                            <span
                              className={
                                log.result === "denied"
                                  ? "unhealthy"
                                  : "healthy"
                              }
                            >
                              {log.result === "denied" ? "已拒绝" : "成功"}
                            </span>
                          </div>
                          <small>
                            {new Date(log.created_at).toLocaleString("zh-CN")} ·
                            操作者 {log.actor_id || "部署管理员"}
                          </small>
                          <p>资源：{log.resource_id || "—"}</p>
                          <details>
                            <summary>变更元数据</summary>
                            <pre>{JSON.stringify(log.details, null, 2)}</pre>
                          </details>
                        </article>
                      ))}
                    </div>
                  )}
                </section>
              ) : (
                <p className="empty-state">
                  仅机构所有者与管理员可查看机构审计。
                </p>
              ))}
            {view === "account" && (
              <section className="workspace-panel account-panel">
                <h2>修改登录密码</h2>
                <p className="form-note">
                  {identity.user.email} · 修改后会撤销全部会话，需要重新登录。
                </p>
                <form
                  className="project-form"
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const data = new FormData(e.currentTarget);
                    if (data.get("new_password") !== data.get("confirmation")) {
                      setError("两次输入的新密码不一致");
                      return;
                    }
                    setBusy(true);
                    setError("");
                    try {
                      await api(
                        "auth/password",
                        {
                          method: "POST",
                          body: JSON.stringify({
                            current_password: data.get("current_password"),
                            new_password: data.get("new_password"),
                          }),
                        },
                        identity.csrf_token,
                      );
                      router.replace("/login");
                    } catch (error) {
                      fail(error);
                      setBusy(false);
                    }
                  }}
                >
                  <label>
                    当前密码
                    <input
                      name="current_password"
                      type="password"
                      required
                      autoComplete="current-password"
                      maxLength={256}
                    />
                  </label>
                  <label>
                    新密码
                    <input
                      name="new_password"
                      type="password"
                      required
                      autoComplete="new-password"
                      minLength={12}
                      maxLength={256}
                    />
                  </label>
                  <label>
                    确认新密码
                    <input
                      name="confirmation"
                      type="password"
                      required
                      autoComplete="new-password"
                      minLength={12}
                      maxLength={256}
                    />
                  </label>
                  <button className="primary" disabled={busy}>
                    修改密码并退出
                  </button>
                </form>
              </section>
            )}
          </>
        )}
        <footer>
          <span>PEClaw · 私有工作空间</span>
          <span>AI、文档检索与报告功能尚未接入</span>
        </footer>
      </main>
    </div>
  );
}
function MemberRow({
  member,
  owner,
  busy,
  onSave,
}: {
  member: Member;
  owner: boolean;
  busy: boolean;
  onSave: (role: string, active: boolean) => Promise<void>;
}) {
  const [role, setRole] = useState(member.role);
  return (
    <div className="member-row">
      <div>
        <strong>{member.full_name}</strong>
        <small>{member.email}</small>
      </div>
      <select
        aria-label={`${member.email} 角色`}
        value={role}
        disabled={busy || (!owner && member.role === "owner")}
        onChange={(e) => setRole(e.target.value)}
      >
        {[
          "viewer",
          "member",
          "admin",
          ...(owner || member.role === "owner" ? ["owner"] : []),
        ].map((r) => (
          <option key={r} value={r}>
            {roles[r]}
          </option>
        ))}
      </select>
      <span className={member.is_active ? "healthy" : "unhealthy"}>
        {member.user_is_active === false
          ? "账号已停用"
          : member.is_active
            ? "有效"
            : "已停用"}
      </span>
      <button
        className="refresh"
        disabled={busy || (!owner && member.role === "owner")}
        onClick={() => onSave(role, member.is_active)}
      >
        保存角色
      </button>
      <button
        className="inline-button"
        disabled={busy || (!owner && member.role === "owner")}
        onClick={() => onSave(member.role, !member.is_active)}
      >
        {member.is_active ? "停用成员" : "启用成员"}
      </button>
    </div>
  );
}
