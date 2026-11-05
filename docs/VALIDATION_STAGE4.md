# 阶段四验证记录

本轮在 Codex 托管开发环境实际执行。没有发布环境快照、推送 GitHub、创建 Codespace 或公网部署。使用合成资料和随机测试身份，没有导入用户真实项目文档。

## 已通过

- Python 3.12 / uv 0.13.4 冻结依赖安装，官方 zh_core_web_md 3.8.0 模型 wheel 下载与锁定；300 维真实预训练向量、盈利/利润与天气负例相似度测试。
- `uv run pytest ../../tests/unit ../../tests/security ../../tests/integration -q`：101 passed，未跳过。新增知识库 13 项单元及 20 项集成测试，保留前面阶段 68 项。
- 六格式真实文件解析、UTF 文本/Markdown、定位与偏移、非法路径/二进制/XML 拒绝、扫描 PDF 明确失败。使用实际 PostgreSQL/pgvector 与 RustFS S3；没有以 mock 代替检索或对象存储。
- 完整上传/索引/查询/附件下载、幂等冲突、旧版保留但不进入当前检索、失败重试上限、执行者撤销/改由合法编辑者重试、过期租约恢复、原文 SHA-256 损坏拒绝索引/下载。
- 跨机构/项目拒绝、同一用户加入两机构时三种检索模式仍隔离、受限文档脱敏与明确授权、只读角色交集、ACL 撤销、公共维护员无私有旁路、提示注入内容仅作为原文、审计不含私有正文。
- 删除立即撤索引和拒绝原文下载，S3 HEAD 确认原对象由 worker 删除；解析与删除竞争不重建索引。
- `uv run ruff check app alembic ../../tests`、`uv run alembic check` 通过。独立临时库运行 upgrade head → 重复 upgrade → downgrade base → upgrade head，全部通过；实际运行 head 为 0004_knowledge。
- Web `npm test`：3 passed；`npm run typecheck`、`npm run format:check` 通过；前后端生产 Docker 镜像构建通过。
- Playwright 系统 Chromium 桌面与 390px 手机：全量 12 passed。知识库用实际 API、BFF、数据库、S3、独立 knowledge-worker，完成文件上传/等待索引、原文片段、原文件下载字节核对、语义检索、新版与历史版、旧版不混入检索、只读用户、文档限制/再次授权、删除/原文清理；无浏览器脚本错误或横向溢出。
- Compose 中 API/Web healthy，两个 worker 运行；readiness 的 database/redis/object_storage 均为 ok。浏览器测试完成后 users/private_documents/private_document_versions/private_document_chunks 与 private/ 对象数均为 0，测试资料未保留为产品数据。

复现：按 README 启动依赖，从 services/api 执行上面的 Python 命令；从 apps/web 执行 `CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm run test:e2e -- --workers=2`（无系统 Chromium 时先用 Playwright 安装）。本环境构建使用 docker-compose.cloud.yml 的临时 CA secret；没有关闭 TLS 检查。

## 发现并修复

首次新增集成测试使用了 TestClient 不支持的 delete(json=...) 便捷方法，改成 request("DELETE", ..., json=...) 后通过。首次浏览器执行早于容器启动完成，待服务就绪后重新执行。浏览器随后发现列表最后一次状态更新会取消预览详情请求，导致“列表已可检索、预览仍解析中”；改为先刷新详情再结束轮询，桌面/手机真实流程通过。引用定位采用完整页面导航，确保同一路由的版本链接重新加载目标授权上下文；最终镜像下新增点击定位版本与空结果等待断言，桌面/手机两项再次通过。

## 未交付或未验证

- 本地语义是中文静态词向量平均基线，未接句向量 Transformer、外部生成模型、Model Gateway 或 Agent。没有授权业务评测集，不宣称复杂财务语义的准确率/召回率。
- 没有扫描件 OCR、公式执行、旧 Office、加密文件或视觉版面识别；解析资源限制不是完整恶意文件安全沙箱。适用上限见 KNOWLEDGE.md。
- 未实现报告、投资结论生成、审核导出、通用任务框架；GitHub Actions 仅有配置，没有本轮远端执行记录。
- 未做生产压测、备份恢复、恶意文件隔离认证、存储自有版本清除或外部下载副本召回。生产 HTTPS/最小权限账户与存储选型沿用既有待验收项。
- TestClient 有一条 httpx 弃用提示，浏览器有 NO_COLOR 环境提示，不影响通过结果。

下一阶段按 CODEX_TASKS.md 实现 Gateway 与显式 Agent 工作流。
