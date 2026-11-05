# 阶段一实际验证记录

日期：2026-11-05。位置：当前云环境 `/workspace/peclaw`。本记录不代表环境已重新发布，也不代表已验证新任务快照恢复。

| 检查 | 实际结果 |
| --- | --- |
| `uv sync --frozen --extra dev` | 成功，44 个已安装依赖；uv.lock 保留精确版本 |
| Ruff | 通过 |
| 后端 Pytest 全部现有测试 | 12 passed：单元 5、安全基础 3、真实依赖集成 4；无跳过 |
| 前端单元测试 | 3 passed，覆盖 API 请求、503 和无效/不可达响应 |
| TypeScript strict 类型检查 | 通过 |
| Prettier | 通过 |
| Next.js 生产构建 | 通过，页面按请求从 API 读取实时状态 |
| API/Web Docker 构建 | 通过，云 CA 由 BuildKit secret 挂载，TLS 校验保留 |
| Compose 全栈启动 | 通过；PostgreSQL、Redis、S3、API、Web 均 healthy；migrate/storage-init 成功退出 0 |
| Compose 重复启动 | 通过，迁移和 bucket 初始化可重复执行 |
| API readiness | HTTP 200，database/redis/object_storage 全为 ok |
| pgvector | 实际向量距离查询返回预期值 |
| Redis | 唯一临时 key 写入、读取、删除成功 |
| S3 | 临时文件上传、下载、内容校验、删除成功 |
| 隔离测试库迁移 | upgrade → 重复 upgrade → downgrade base → upgrade 全部成功；测试库已清理 |
| 数据库备份恢复 | pg_dump 自定义格式备份，恢复至临时空库，版本 0001_platform 正确；临时库已删除 |
| Chromium 浏览器 | 桌面 1440×1100、移动 390×844，共 4 passed；刷新、导航、无横向溢出、无浏览器脚本错误 |
| Git 差异检查 | 无意外现有文件覆盖；仅原 README 被扩展，其余为新增文件；.env/依赖/浏览器产物被忽略 |

## 已解决的问题

- MinIO Docker Hub 镜像返回访问拒绝，官方二进制域名不在允许范围。改用需求允许的 S3 兼容 RustFS，固定版本与镜像摘要；未新增网络域名，也未关闭 TLS 校验。
- 托管机的环境 AWS profile 不适用于本地 S3。客户端使用显式 S3 配置，隔离于 ambient profile，保持进程认证和平台变量不变；回归测试覆盖此项。
- 容器目录比仓库目录浅，原环境文件路径在导入时报错。改为可解析的相对 Path，不依赖祖先列表长度。
- Docker 同时注入大小写代理配置。为 NO_PROXY/no_proxy 分别追加内部服务，修复内部 S3 请求误经外部代理的 403。
- 首次浏览器测试在服务初始化失败时出现连接拒绝；修复上述配置并完成全栈就绪后，4 项测试重新执行全部通过。

## 尚未验证或实现

- GitHub Actions 工作流已配置（含浏览器任务），未推送或在 GitHub 实际运行。
- 尚无登录、多租户、企业数据库、文档解析检索、Agent、报告导出；未声称其测试通过。
- RustFS alpha 镜像仅为开发选择，生产稳定性、供应链与许可、备份保留和服务账户策略待评估。
- 当前后端 TestClient 依赖发出一条 httpx 弃用提示，不影响 12 项测试执行；后续升级应按 Starlette 推荐客户端迁移。
- 浏览器运行器有 NO_COLOR/FORCE_COLOR 配置提示，不影响测试结果。
- 前端/API 生产容器采用非 root 用户，但开发基础服务尚未具备生产认证、TLS、最小权限和租户隔离。

运行步骤与环境变量见 README；安全边界见 SECURITY.md；后续范围见 ACCEPTANCE.md。
