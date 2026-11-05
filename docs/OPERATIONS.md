# 开发运维

Compose 命名卷保存 PostgreSQL、Redis 与 RustFS（S3 兼容） 文件。停止服务不会删除卷。当前运行 catalog-worker、knowledge-worker、agent-worker、evaluation-worker；任务与租约保存在 PostgreSQL。

## 备份和恢复基础

仅限开发环境维护窗口；应用停写。备份含机构敏感数据时需要加密与访问控制，不能提交仓库。当前阶段未接入业务数据。数据库示例：

```sh
mkdir -p .data/backups
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > .data/backups/database.dump
# 恢复到专用空库；不要无确认覆盖现有库。
# docker compose exec -T postgres createdb -U peclaw peclaw_restore
# docker compose exec -T postgres pg_restore -U peclaw -d peclaw_restore < .data/backups/database.dump
```

RustFS（S3 兼容）/Redis 使用卷快照前需停写并停止对应服务；恢复使用相同服务版本与卷路径。生产备份必须建立数据库与对象存储的一致性窗口、加密、保留周期与定期恢复演练；这些生产能力当前未完成。Redis 后续仅存队列与临时状态，任务最终记录仍应落 PostgreSQL。

云环境快照不保留进程；进入新任务先执行 `docker compose up -d --wait` 并检查 API readiness。无需创建 Git worktree。不要为了恢复服务删除数据卷或更改既有凭据。

托管 Docker 代理同时可能注入 NO_PROXY 和 no_proxy；Compose 为两者分别追加内部服务名，防止内部 S3 请求经外部代理。外部代理变量与既有绕过项均保留。


## 身份运维（阶段二）

首次账号、增员、账号停用/启用使用 README 的交互 CLI；不得在参数、环境模板或聊天中写真实密码。CLI 输出机构 UUID，可复用于其他成员开通。机构管理员只操作本机构资格，操作员才可控制全局账号。所有者必须保留至少一名；转移所有权后再通过 UI 降级原所有者。

发布升级前备份数据库；迁移 `0002_identity` 创建七张表，不修改既有阶段一业务数据。不要对有真实身份数据的库执行 downgrade base，回退会删除会话、项目和审计。实际生产迁移、恢复、保留周期和高权限运维需单独验收。

默认登录每个邮箱 10 次/15 分钟，API 对端 500 次/15 分钟，包括成功尝试；Redis 故障返回 503。频率限制触发应等待 TTL，不能以关闭校验作为排错方式。若页面拒绝来源，确认 AUTH_ALLOWED_ORIGINS 包含真实浏览器 Origin，保留精确校验与 TLS。

浏览器测试从操作员进程在当前开发库创建独立随机 BrowserTest 机构与账号，finally 清理；集成身份测试则使用独立临时库。请勿在真实客户生产库运行浏览器 fixture。故障中断时可按 fixture key 审查并清理测试数据，不得批量删除无关机构。


## 阶段三导入运维

新增 catalog-worker，和 API/迁移使用同一镜像。全容器启动会自动运行；本机开发需 `cd services/api && uv run python -m app.catalog_worker`。停止 worker 保留 queued 任务：`docker compose stop catalog-worker`；恢复 `docker compose up -d catalog-worker`。不要删除数据库任务表或数据卷来恢复导入。

查看日志使用 `docker compose logs --tail=100 catalog-worker`，任务具体结果在维护界面。worker 进程存在不等于导入可用；验收使用真实文件任务确认。任务运行崩溃后等待 120 秒租期，再由 worker 恢复；第三次崩溃会标失败，错误文件应修复后新建导入。原始输入保存在数据库，备份/容量/保留期要按实际运营数据管理，不能作为无限文件存储。

public curator 由部署操作员授予，机构管理员不能自行升级；撤销后新请求拒绝写操作，排队任务在执行前也重新检查。别用真实客户私有数据作为公共导入测试；测试夹具按独立 key 清理自身公司、来源、任务、分类和账号。

## 私有知识库 worker

全容器运行 `knowledge-worker`（与 API 同镜像）；本机运行 `uv run python -m app.knowledge_worker`。可用 `docker compose logs --tail 100 knowledge-worker` 检查受控异常类别。上传停留 uploading/processing 超过 120 秒后可由 worker 回收；三次失败需有权限编辑者检查文件并添加新版本。删除显示清理失败时由管理者在页面重试，不能以数据库元数据 deleted 代替存储策略审计。模型安装在镜像构建时完成，不需要 HF 或生成模型凭据；不应放开私有文档外发。

数据库与原文备份必须同步规划，恢复后复核文档 ACL/删除记录，避免已删除原文被重新公开。模型变更需另行迁移/重建索引；不得混用不同向量模型的 embedding_model。具体限制见 KNOWLEDGE.md。

## Agent worker 与模型

全容器增加 agent-worker，本机 `uv run python -m app.agent_worker`。默认 MODEL_PROVIDER=disabled；正确配置端点/模型/secret、网络允许和 CA 信任后才能使用外部生成模型。`docker compose logs --tail 100 agent-worker` 仅输出受控异常类别。cloud 覆盖文件为 API/Agent worker 挂载只读 CA，不关闭 TLS；托管环境需用 cloud 覆盖启动以保留该运行时信任设置。

预算与并发是每机构、UTC 日、保守预留，失败/未知计费不自动返还。调用记录实际用量和估算价格不等同账单；价格未配置显示未知。手工重试仅到三次，崩溃恢复亦计数。执行模型时租约300秒，检索租约120秒；取消无法保证服务商停止计费。排查按错误码和 task ID，切勿粘贴凭据或完整模型上下文。配置与边界详见 AGENTS_WORKFLOWS.md。

## 报告与审核

升级至0007_review_snapshots 后可使用 /reports，无新增模型凭据或独立 worker。REPORT_ALLOW_DRAFT_EXPORT 可关闭草稿附件；正式 strict 策略不能关闭数字/独立审核要求。报告/数字/审核快照/导出记录须与私有原文及其保留策略一起备份。文件即时生成，不存在可从 S3 直接恢复的导出附件；保存的外部副本不受应用撤权控制。

来源更新/删除或审核人资格失效时，新建报告或重新分派并复核，不手动修改数据库批准标志。遇到数值单位/期间不匹配，要补充有完整语境的授权来源，不用0或估计值替代未知。行为及边界见 REPORTS.md，执行记录见 VALIDATION_STAGE6.md。
