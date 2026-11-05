# PEClaw

产业情报与 PE AI 投资工作台。产品需求见 [docs/PRD.md](docs/PRD.md)。

当前交付：**阶段七，评测与反馈**。新增 `/evaluation`：版本化授权样本、企业搜索/知识检索指标、既有事实/BP 输出对照、报告质量闸检查、独立反馈和 JSON 证据导出。[评测指南](docs/EVALUATION.md)。

保留 `/reports` 报告与独立审核、`/agents` 五类研究工作流、`/knowledge` 私有知识库、`/companies` 企业搜索、`/companies/<id>` 企业档案、`/industry` 产业地图、`/catalog` 公共维护，以及账号、机构、项目与审计页面。

人工报告流程无需模型。**生成模型仍默认未配置**，不生成占位分析；真实模型效果、财务真实性及授权数据试点评测尚未完成。没有默认账号或真实企业资料，样例和自动化测试均明确标记为合成材料。正式导出要求当前修订、数字、独立审核与来源权限均有效，不等同投资保证或财务审计结论。

## 浏览器试用

没有服务器时可使用 [GitHub Codespaces 试用指南](docs/CODESPACES.md)。需要先将当前代码推送到 GitHub，再由账号持有人创建实例；当前 Codex 环境尚无公网访问地址。自有服务器的 HTTPS 配置见 [外部访问](docs/EXTERNAL_ACCESS.md)。

## 运行要求

- Node.js 22+（开发/CI 使用 24）、npm、Python 3.12+、uv 0.13.4、Docker Engine 与 Compose v2。
- 端口：3000 Web、8000 API、5432 PostgreSQL、6379 Redis、9000 S3、9001 RustFS（S3 兼容） 控制台。
- 所有 Compose 暴露端口仅绑定本机。生产需 HTTPS、安全 Cookie、正确 Origin、最小权限服务账户及受控反向代理；当前默认配置用于本地开发。

## 启动：全容器

在仓库根目录执行：

```sh
python3 scripts/init_env.py
# 创建随机的本地开发凭据；已有 .env 会被保留。也可手动复制 .env.example 并替换占位符。
docker compose up -d --build --wait
curl --fail http://localhost:8000/api/v1/health/ready
```

打开本机 3000 端口的页面。Next.js 服务端访问 API，并显示 PostgreSQL、Redis、对象存储的真实连接状态。修改代码后 `docker compose up -d --build --wait` 重新构建。

托管云的代理 CA 构建方式（保持平台 Docker 代理配置）：

```sh
docker compose -f docker-compose.yml -f docker-compose.cloud.yml build api web
docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d --wait
```

CA 在构建时通过 BuildKit secret 临时挂载；cloud 覆盖文件也为 API 与 Agent worker 只读挂载运行时 CA，以供受控模型连接验证。不写入镜像。普通本机不需要 cloud 覆盖文件。
`migrate` 和 `storage-init` 是一次性初始化服务，成功退出是预期行为，不是服务故障。

## 启动：本机热更新开发

根目录启动基础服务：

```sh
python3 scripts/init_env.py
docker compose up -d --wait postgres redis object-storage
cd services/api
uv sync --frozen --extra dev
uv run alembic upgrade head
uv run python -m app.storage_init
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

另开终端：

```sh
cd apps/web
npm ci
npm run dev
```

第三个终端启动公共企业导入 worker：

```sh
cd services/api
uv run python -m app.catalog_worker
```

Agent 工作流需另开终端：`cd services/api && uv run python -m app.agent_worker`。

私有知识解析需另开终端：`cd services/api && uv run python -m app.knowledge_worker`。

全容器模式已自动启动 `catalog-worker`、`knowledge-worker` 与 `agent-worker`。本阶段使用 PostgreSQL 持久队列和 SKIP LOCKED 行锁，不需要安装 Celery；Redis 继续用于登录限流。生产/外部访问覆盖配置已同步 worker 的 HTTPS Origin 设置。

后端自动读取仓库根目录 `.env`；前端本地默认连接 8000 端口。自定义地址可用 `API_INTERNAL_URL=http://... npm run dev`。全容器模式自动改用容器内服务地址。不要同时启动占用相同端口的两个模式。

## 迁移、停止和恢复

```sh
# 全容器：每次部署显式应用迁移；应用进程本身不自动创建表
# 修改迁移后需先重建 API 镜像
docker compose run --rm migrate
# 本机：cd services/api && uv run alembic upgrade head
# 检查版本：uv run alembic current
# 仅开发测试库可回退：uv run alembic downgrade base
docker compose stop
# 启动现有服务：docker compose up -d --wait
# 移除容器但保留数据：docker compose down
```

**不要随意使用 `down -v`，它会删除数据库与文件。** 数据保留在三个命名卷中，进程不随环境快照保留；新任务需重启服务。备份与恢复见 [docs/OPERATIONS.md](docs/OPERATIONS.md)。

## 测试与检查

```sh
cd services/api
uv sync --frozen --extra dev
uv run ruff check app alembic ../../tests
uv run pytest ../../tests/unit ../../tests/security
# 基础服务已启动、迁移已执行、bucket 已初始化后：
uv run pytest ../../tests/integration
cd ../../apps/web
npm ci
npm test
npm run typecheck
npm run build
# 全栈已启动后运行浏览器测试；首次下载浏览器：npx playwright install chromium
npm run test:e2e
# 云环境可复用系统浏览器：CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm run test:e2e
```

集成测试实际执行 pgvector 距离计算、Redis 写读删除、S3 上传下载删除与 API 就绪检查；使用唯一临时 key 清理。新增身份和隔离测试使用独立临时 PostgreSQL 数据库，覆盖跨租户、跨项目、CSRF、撤销、并发所有者变更和任务上下文。运行测试的数据库角色需能 CREATE DATABASE，测试结束会清理该临时库。私有知识新增六格式解析、原文下载、文档 ACL、版本/引用、当前版本混合检索、恢复/删除竞争与原对象清理测试。报告导出仍未实现。公共库新增来源/证据、合并撤销与后台导入测试；浏览器会实际提交文件并等待独立 worker 完成。AI 评测尚未实施。GitHub Actions 配置上述测试，尚需在远端首次执行。

## 环境变量

完整模板见 `.env.example`，不要提交 `.env`。`scripts/init_env.py` 会生成随机数据库与本地 RustFS（S3 兼容） 密码，不覆盖现有设置。

| 变量 | 用途 |
| --- | --- |
| APP_ENV | development / production；production 会拒绝非 Secure Cookie 与 HTTP Origin |
| POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD | Compose 数据库初始化；修改已有卷的密码需在数据库内同步修改 |
| DATABASE_URL | 本机后端/Alembic 连接地址；密码需 URL 编码；Compose 内自动拼接容器地址，因此 Compose 密码请用 URL 安全字符 |
| REDIS_URL | 本机 Redis 连接；Compose 内自动使用 redis 服务 |
| S3_ENDPOINT_URL | 本机 S3 兼容地址；Compose 内使用 object-storage 服务 |
| S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY | 本地 RustFS（S3 兼容） 开发账户；生产使用最小权限专用服务账户 |
| S3_BUCKET / S3_REGION | 文件 bucket 与区域，默认 peclaw-documents / us-east-1 |
| API_INTERNAL_URL | Next.js 服务端调用 API 的地址；非 NEXT_PUBLIC 变量，不暴露给浏览器 |

本阶段不需要模型 API key，不调用外部模型。

## 故障排查

- 页面显示未连接：确认 API 运行，检查 `API_INTERNAL_URL`；容器内 localhost 不指向 API 容器。
- `/health/live` 成功而 `/health/ready` 返回 503：查看具体失败项。数据库需运行迁移并启用 pgvector；对象存储需初始化 bucket。
- Compose 服务故障：`docker compose ps -a` 与 `docker compose logs --tail=100 <服务名>`。不要公开含敏感数据的日志。
- 认证失败：确认 `.env` 与已初始化卷一致，不要删除卷规避问题。
- 构建 TLS 失败：云环境使用 CA override；禁止关闭证书验证。
- 端口冲突：停止自己启动的冲突进程或调整 Compose 主机端口和本机配置。

## 首个账号与机构

服务启动并完成迁移后，在交互终端执行（密码由 getpass 读取，不在参数或日志中传递）：

```sh
cd services/api
uv run python -m app.provision --email you@example.com --name "你的姓名" --organization "你的机构"
# Docker 全容器模式：根目录执行 docker compose exec api python -m app.provision ...
```

CLI 输出用户和机构 ID。创建新机构时，该账号自动成为 owner；同一账号可加入多个机构。创建第二名账号并加入现有机构：

```sh
uv run python -m app.provision --email colleague@example.com --name "同事" --organization-id <机构UUID> --role member
# 已开通的其他账号，也可由机构管理员在“机构成员”页面加入本机构。
# 全局停用/恢复由部署操作员执行；机构管理员只能管理本机构成员状态：
uv run python -m app.provision --email colleague@example.com --disable
uv run python -m app.provision --email colleague@example.com --enable
```

停用或恢复不会复活旧会话，用户需重新登录。CLI 不重置已有账号密码。机构管理员不会自动读取全部私有项目，但可以审计留痕地管理本机构项目 ACL，明确授权后才可读取。角色矩阵见 docs/SECURITY.md。

## 维护公共企业数据库

公共企业可由有效机构成员读取；**机构 owner/admin 不自动具有公共库写权限**。部署操作员先开通普通账号，再单独授予维护员权限：

```sh
# 仓库根目录，全容器模式；只传账号邮箱，不传密码
docker compose exec api python -m app.provision --email you@example.com --data-curator grant
# 撤销写权限：
docker compose exec api python -m app.provision --email you@example.com --data-curator revoke
# 本机开发：cd services/api && uv run python -m app.provision ...
```

刷新页面后进入 `/catalog`：先登记允许向平台所有有效机构共享的来源与许可，再登记分类或上传 CSV/XLSX。可使用 `examples/companies.csv` 做合成演示，来源许可选 synthetic_demo，并明确说明用途。不把样例当成真实企业资料。

导入支持 UTF-8 CSV 或单工作表 XLSX，每批最多 200 行、1 MiB，不接受 Excel 公式、宏、外链或超限压缩内容。返回任务 ID，后台完成后显示逐行结果。疑似重复（含历史别名与已归档身份）进入人工核实，不静默覆盖；相同来源的相同行重复导入会跳过。任务最多执行三次，运行进程崩溃后可在 120 秒租期过期后恢复。

企业更新必须带资料来源、原因与版本号；未提交字段保留，显式空值才会清除对应可空字段。归档和恢复保留历史。人工合并只建立可撤销关联，原始企业、证据与身份标识不迁移或删除；合并前后数据都保留。

自然语言入口是规则解析：只执行返回的明确条件，不联网，也不调用模型补齐数据；无法应用的财务/客户等描述会提示。未知上市状态不会被视为未上市，未知国家不默认为中国。详细格式与工作流见 [公共企业库指南](docs/CATALOG.md)。

## 身份环境变量

| 变量 | 默认值与用途 |
| --- | --- |
| AUTH_ALLOWED_ORIGINS | JSON 字符串数组；默认仅 localhost:3000 / 127.0.0.1:3000；自定义 Web 域名须配置完全匹配的 scheme、host、port，不能带路径或通配符 |
| AUTH_COOKIE_SECURE | 默认 false，仅本地 HTTP；生产必须 true 且由 HTTPS 提供服务 |
| AUTH_SESSION_SECONDS | 默认 28800 秒（8 小时），会话绝对期限，范围 300–604800 |
| AUTH_LOGIN_ATTEMPTS | 默认每个邮箱每 15 分钟 10 次尝试（成功与失败都计数） |
| AUTH_PEER_LOGIN_ATTEMPTS | 默认每个 API 对端每 15 分钟 500 次尝试；BFF 多用户共享对端限制，不信任任意 X-Forwarded-For |

新增变量缺省时会使用安全的本地开发默认值，已有 `.env` 无需覆盖；可对照 `.env.example` 追加。生产配置不是一键生产认证：仍需完成 HTTPS、运维与部署验收。

浏览器请求经 Next.js 的固定路径 BFF 访问 API，HttpOnly Cookie 不在浏览器脚本内读取。修改请求需要受信 Origin 与服务端会话派生的 CSRF token。CLI/API 客户端需携带 Origin、Cookie，后续写请求增加登录或 /auth/me 返回的 X-CSRF-Token。

## 目录

```text
apps/web/                 Next.js + TypeScript + Tailwind
services/api/app/          FastAPI：api / core / models / schemas / services / security
services/api/alembic/      数据迁移
scripts/                  本地环境初始化工具
packages/                 后续共享类型与版本化提示词的预留边界
tests/                    unit / integration / security / evaluation
docs/                     PRD、架构、模型、接口、安全、评测、验收、运维
.github/workflows/         CI
docker-compose*.yml       本机部署与云 CA 覆盖
```

阶段验收和后续范围见 [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)。

对象存储使用 RustFS 的固定镜像摘要：MinIO 公共镜像在本次环境中拉取被拒绝，因此选择 PRD 允许的 S3 兼容替代。当前 RustFS 为 alpha 版本，仅用于开发验证；生产选型、许可证与稳定性需单独评估，可通过统一 S3 配置迁移。
