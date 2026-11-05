# 第三阶段验收记录

日期：2026-11-05。位置 `/workspace/peclaw`。范围：PRD 17.4 公共企业数据库。历史阶段记录见 VALIDATION.md / VALIDATION_STAGE2.md。

## 已交付

- 12 张公共目录表与用户全局维护权限标记，Alembic head 0003_catalog。
- 企业、别名、产品、技术、产业链分类、来源许可、具体主张证据与人工核验。
- 企业创建/详情/更新/归档恢复、乐观版本与变更历史；省略字段不被默认值静默清除。
- 结构化搜索、名称/别名检索、规则自然语言条件提示、分页、日期与来源筛选、父产业包含后代、只读基础产业地图。
- 不同证据说法和合并原始档案的关键状态差异展示，不自动选定事实。
- 人工去重候选、明确确认后的可撤销合并，原始身份与证据保留。
- UTF-8 CSV/单表 XLSX 异步导入、独立 catalog-worker、逐行状态、幂等、失败重试与崩溃恢复。
- 维护员来源/分类/导入界面，以及桌面和移动企业列表/详情/地图；公共库写权限独立于机构 owner/admin。

## 实际执行结果

| 检查 | 结果 |
| --- | --- |
| uv 锁定依赖安装 | openpyxl/defusedxml 等已安装，uv.lock 固定版本并用于 Docker 构建 |
| Python Ruff 检查、格式检查 | 通过 |
| Pytest | **68 passed，无跳过**：公共目录集成 16、公共目录安全 6、身份集成 7、基础设施集成 4、私有项目隔离 9、错误安全 3、目录规则单元 10、健康单元 5、身份规则单元 8 |
| 迁移一致性 | Alembic check：No new upgrade operations detected |
| 临时库迁移 | upgrade → 重复 upgrade → downgrade base → upgrade 成功，临时库已清理 |
| TypeScript strict | 通过 |
| Prettier | 通过 |
| 前端单元 | **3 passed** |
| Next.js 本机构建与 Docker Web 构建 | 通过，含 companies/detail/industry/catalog 新页面 |
| API Docker 构建 | 通过，使用 TLS 验证与 BuildKit CA 临时挂载 |
| Compose 启动 | API、Web、PostgreSQL、Redis、S3 healthy；迁移和初始化退出 0；catalog-worker 独立进程运行 |
| 浏览器端到端 | **10 passed**，桌面与移动各 5；包含原阶段流程与实际后台文件导入 |
| 视觉与宽度 | 实际 Chromium 检查 1440 与 390 像素企业列表，scrollWidth 分别为 1440/390，无横向溢出；含日期筛选表单 |
| HTTPS 部署覆盖配置 | 在示例域名下验证 API/迁移/初始化/worker 的 Secure Cookie、Origin 与 production 设置一致；未执行外部部署 |
| 数据清理 | 实际运行库 users/companies/data_sources/catalog_imports 均为 0，测试夹具没有留下默认账号或演示档案 |
| Git/配置 | diff --check、Compose config 检查通过；.env、虚拟环境与浏览器产物被忽略 |

后台进程能力不是凭 PID 判断：浏览器真实上传 CSV，等待任务从 queued 到 completed，校验创建 2 行，再读取档案和技术证据。集成测试另验证 XLSX、坏文件、重复输入、行错误、别名/已归档身份待核实、执行权限撤销、120 秒过期任务恢复、第三次崩溃失败和重试上限。

完整浏览器目录流程：维护员登录 → 登记共享许可来源 → 上传合成 CSV → 独立 worker 完成 → 按产业/技术地图浏览 → 未上市筛选不会命中未知状态 → 别名检索 → 编辑并保留历史 → 登记原文证据 → 人工确认合并 → 撤销并保留证据 → 普通成员可读且不可维护。浏览器未报告脚本错误。

## 保留的限制

- 目录目前为空，不含真实 500 家企业样本、供应商 API、商业授权或实时新闻采集。examples/companies.csv 明确为虚构演示。
- 自然语言入口为规则匹配，显示执行条件和未执行财务/客户条件；不是 LLM 语义解析或完整市场扫描。模糊去重扫描有上限并返回 truncated，不表示完整重复集合。
- 产品/技术当前提供登记、证据关联和查看；分类以新增为主。更复杂的版本编辑、事件流、观察清单和新闻采集尚未交付。
- 来源许可是人工核查声明，不代表自动法律验证或支持任意网站采集。
- 公共导入 worker 使用 PostgreSQL 持久队列，不是通用 Agent 或私有文档执行器；阶段四仍需私有文件、切片、向量、下载/检索权限与删除测试。
- 尚无模型调用、私有知识库或报告质量闸/导出，不宣称这些后续功能通过验收。
- GitHub Actions 已更新配置，但未推送/在远端运行；未发布环境快照、未创建 Codespace、未取得公网网址。
- 生产 HTTPS、最小权限数据库/S3 角色、备份保留/恢复与 RustFS alpha 选型仍需单独验收。
- 当前 TestClient 有一条 httpx 弃用提示，浏览器有 NO_COLOR 配置提示，均未导致测试失败或跳过。

使用与开通维护员见 README / CATALOG.md。下一阶段按 CODEX_TASKS.md 实现机构私有知识库。
