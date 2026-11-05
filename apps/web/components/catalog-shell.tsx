"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type Identity } from "@/lib/api";
export function CatalogShell({
  title,
  children,
}: {
  title: string;
  children: (identity: Identity) => ReactNode;
}) {
  const [identity, setIdentity] = useState<Identity>();
  const [error, setError] = useState("");
  const router = useRouter();
  useEffect(() => {
    const controller = new AbortController();
    api<Identity>("auth/me", { signal: controller.signal })
      .then(setIdentity)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
        else if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [router]);
  return (
    <div className="shell">
      <aside className="sidebar">
        <Link className="brand" href="/">
          <span className="brand-icon">P</span>PEClaw
          <span className="brand-dot">.</span>
        </Link>
        <div className="workspace-label">INDUSTRY INTELLIGENCE</div>
        <nav aria-label="产业情报导航">
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
          <Link href="/">
            ▦ <span>工作台</span>
          </Link>
          <Link
            className={["企业情报", "企业档案"].includes(title) ? "active" : ""}
            href="/companies"
          >
            ◈ <span>企业情报</span>
          </Link>
          <Link
            href="/industry"
            className={title === "产业地图" ? "active" : ""}
          >
            ◉ <span>产业地图</span>
          </Link>
          <Link href="/projects">
            ◇ <span>投资项目</span>
          </Link>
          {identity?.can_curate_public_data && (
            <Link
              className={title === "公共数据维护" ? "active" : ""}
              href="/catalog"
            >
              ≡ <span>公共数据维护</span>
            </Link>
          )}
          <Link href="/account">
            ◎ <span>账号安全</span>
          </Link>
        </nav>
        <div className="sidebar-note">
          公共产业数据域<div>来源可追溯 · 未知不补全</div>
        </div>
      </aside>
      <main className="workspace-main">
        <header>
          <span>{title}</span>
          <span className="user-menu">
            {identity?.user.full_name}
            <Link className="refresh" href="/projects">
              机构工作空间 →
            </Link>
          </span>
        </header>
        {error ? (
          <p role="alert" className="error-message">
            {error}
          </p>
        ) : identity ? (
          children(identity)
        ) : (
          <p className="empty-state">正在验证账号…</p>
        )}
        <footer>
          <span>PEClaw · 公共产业情报</span>
          <span>档案记录不等于投资结论</span>
        </footer>
      </main>
    </div>
  );
}
