import { getHealth } from "@/lib/health";
import { RefreshButton } from "@/components/refresh-button";
export const dynamic = "force-dynamic";
const modules = [
  {
    n: "01",
    title: "企业情报",
    text: "从产业链与技术路线出发，发现企业，追溯每一条关键事实。",
    tags: "企业档案 / 产业地图 / 来源管理",
    stage: "阶段三",
  },
  {
    n: "02",
    title: "私有知识库",
    text: "让历史项目与研究经验成为机构可检索、可复用的知识资产。",
    tags: "项目文档 / 混合检索 / 证据片段",
    stage: "阶段四",
  },
  {
    n: "03",
    title: "AI 投资工作台",
    text: "以显式工作流辅助项目匹配与 BP 初筛，让结论接受证据检验。",
    tags: "企业画像 / 项目匹配 / 人工审核",
    stage: "阶段五",
  },
];
export default async function Home() {
  const health = await getHealth(
    process.env.API_INTERNAL_URL || "http://localhost:8000",
  );
  const ready = health.status === "ready";
  const labels = {
    database: "PostgreSQL · pgvector",
    redis: "Redis · 任务队列基础",
    object_storage: "对象存储 · 私有文件",
  };
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/">
          <span className="brand-icon">P</span>PEClaw
          <span className="brand-dot">.</span>
        </a>
        <div className="workspace-label">INVESTMENT INTELLIGENCE</div>
        <nav aria-label="主导航">
          <a href="/companies">
            ◈ <span>企业情报</span>
          </a>
          <a href="/projects">
            ◇ <span>投资项目</span>
          </a>
          <a className="active" href="#overview">
            ▦ <span>工作台</span>
          </a>
          <a href="#modules">
            ◈ <span>功能规划</span>
          </a>
          <a href="#system">
            ◎ <span>运行状态</span>
          </a>
          <a href="#roadmap">
            ≡ <span>开发路线</span>
          </a>
        </nav>
        <div className="sidebar-note">
          <span className="tiny-dot" /> 开发环境<div>V1.0 · 公共企业数据库</div>
        </div>
      </aside>
      <main id="overview">
        <header>
          <div className="breadcrumb">
            工作空间 <span>/</span> 工作台
          </div>
          <span className="version">PHASE 07</span>
        </header>
        <section className="intro">
          <div>
            <div className="eyebrow">从产业洞察，到投资判断</div>
            <h1>
              让研究有据可循<span>。</span>
            </h1>
            <p>
              连接公共产业情报、机构私有知识与 AI 工作流。
              <br />
              为每一个投资判断，保留事实、证据与边界。
            </p>
          </div>
          <div className="intro-art" aria-hidden="true">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <div className="art-core">
              P<span>INTELLIGENCE</span>
            </div>
            <span className="art-point point-one" />
            <span className="art-point point-two" />
          </div>
        </section>
        <section className="scope-banner">
          <span className="scope-icon">↗</span>
          <div>
            <strong>从基础开始，逐步建立研究闭环</strong>
            <p>企业档案、来源与证据已接入。私有文档检索与 AI 任务尚未接入。</p>
          </div>
          <a href="/projects">
            进入项目空间 <span>→</span>
          </a>
        </section>
        <section id="modules">
          <div className="section-heading">
            <h2>研究工作空间</h2>
            <span>面向半导体设备与先进封装</span>
          </div>
          <div className="module-grid">
            {modules.map((m) => (
              <article className="module-card" key={m.n}>
                <div className="card-top">
                  <span className="module-number">{m.n}</span>
                  <span className="planned">已接入 · {m.stage}</span>
                </div>
                <h3>
                  <a
                    href={
                      m.n === "01"
                        ? "/companies"
                        : m.n === "02"
                          ? "/knowledge"
                          : "/agents"
                    }
                  >
                    {m.title} →
                  </a>
                </h3>
                <p>{m.text}</p>
                <div className="module-tags">{m.tags}</div>
              </article>
            ))}
          </div>
        </section>
        <section id="system" className="system-panel">
          <div className="section-heading">
            <div>
              <div className="eyebrow">SYSTEM STATUS</div>
              <h2>基础设施连接</h2>
            </div>
            <RefreshButton />
          </div>
          <div className="status-summary" role="status">
            <span className={`status-dot ${ready ? "ok" : "bad"}`} />
            {ready
              ? "前端已连接 API，所有依赖就绪"
              : health.status === "unreachable"
                ? "暂时无法连接 API，请检查服务配置"
                : "API 已连接，部分依赖尚未就绪"}
          </div>
          <div className="service-grid">
            {Object.entries(labels).map(([key, label]) => (
              <div className="service" key={key}>
                <span>{label}</span>
                <strong
                  className={
                    health.checks[key] === "ok" ? "healthy" : "unhealthy"
                  }
                >
                  {health.checks[key] === "ok"
                    ? "已就绪"
                    : health.checks[key] === "error"
                      ? "连接异常"
                      : "未连接"}
                </strong>
              </div>
            ))}
          </div>
        </section>
        <section id="roadmap" className="roadmap">
          <div className="section-heading">
            <h2>交付路线</h2>
            <span>每个阶段独立测试与验收</span>
          </div>
          <ol>
            {[
              "项目骨架",
              "身份与多租户",
              "公共企业数据库",
              "私有知识库",
              "AI Agent",
              "报告与审核",
              "试点与评测",
            ].map((s, i) => (
              <li key={s} className={i === 6 ? "current" : ""}>
                <span>{String(i + 1).padStart(2, "0")}</span>
                <div>
                  {s}
                  <small>
                    {i < 6
                      ? "已完成"
                      : i === 6
                        ? "工程评测 · 试点待验证"
                        : "待开发"}
                  </small>
                </div>
              </li>
            ))}
          </ol>
        </section>
        <footer>
          <span>PEClaw · Industry Intelligence + PE AI Workbench</span>
          <span>事实可追溯 · 判断有边界</span>
        </footer>
      </main>
    </div>
  );
}
