# 阶段五验证记录

本轮在已有托管开发环境继续开发 Gateway 与显式研究工作流。未推送 GitHub、发布环境快照、创建公网部署或发送真实客户资料。

## 实际已执行

- `uv sync --frozen --extra dev` / uv.lock：运行依赖增加 httpx，保留原本地中文模型；模型凭据不入仓库。
- `uv run pytest ../../tests/unit ../../tests/security ../../tests/integration -q`：135 passed，未跳过。新增 13 项 Gateway/结构化单元与 21 项工作流集成测试，保留之前 101 项。
- 五种工作流均使用实际 PostgreSQL 任务、公共资料与 S3 私有文档，通过 httpx.MockTransport 提供明确标记的合成服务商响应验证 HTTPS 请求协议、结构化草案、引用和用量。没有把它描述为真实外部模型调用或分析质量测试。
- Gateway 验证鉴权头、用户/系统角色分离、JSON object 请求与无自由 tools，401/403、429、5xx、重定向拒绝、超时、不合法 JSON、未配置零调用、虚构引用/未核验来源冒充事实拒绝。
- 任务验证幂等、五工作流章节、三次上限、过期租约恢复、取消前零调用/取消中不发布迟到结果、日预算在外发前拒绝、取消仍占用在途并发位、明确费率与实际 token 的费用计算、无费率时 unknown。
- 隔离验证其他机构/其他发起人/只读用户拒绝，受限文件无管理旁路，账号/资格与私有原文在排队后撤销不会进入模型上下文，完成后撤销不能读取旧草案，调用期间删除文档不能提交结果，证据改变拒绝静默替换。
- `uv run ruff check app alembic ../../tests`、`uv run alembic check` 通过，head 为 0005_agents。独立临时库 upgrade → 重复 upgrade → downgrade base → upgrade，全部通过。
- 前端 `npm test` 3 passed；TypeScript 与格式检查通过；API/Web 的 TLS 校验开启的 Docker 生产构建通过，Compose 已启动 agent-worker。
- 新工作台 Playwright 桌面/390px 手机两项通过：模型未配置明确禁用提交，五类表单选择，实际后台任务失败/零模型调用，查看详情、三次重试上限、只读与机构切换隔离，无脚本错误或横向溢出。

API/Web 健康检查通过，三个专用 worker 运行；浏览器测试结束后 agent_tasks/model_calls/users/私有文档及 private/ 原对象均为0，合成身份与材料已清理。

完整 Playwright 回归 **14 passed**，包含此前企业目录、知识库、账号/项目和新增研究工作台的桌面/手机流程。新页面截图保存在本轮 /workspace/artifacts/stage5/，全部来自未配置真实模型的实际页面。

## 发现并修复

- 浏览器发现对当前选中机构重复 select 会先清空 project 而不触发重新加载，已加入同值保护并保持切换机构时同步清空旧内容；桌面/手机复测通过。
- 补充的并发用例初次缺少测试 ModelCall import，修正测试后 21 项集成用例通过。
- 取消任务不能立即释放仍在执行的上游请求额度，改以持久 ModelCall reservation 约束并发，测试确认在途取消后不另发请求。

## 未验证或未交付

- 环境运行时没有模型身份或 secret，受控网络仅放行开发依赖站点，没有真实 DeepSeek/OpenAI 连接或结果质量验收。默认 provider disabled，不使用合成服务商作为运行时降级，UI 不展示伪造分析。
- 当前私有材料取明确选中本项目文件前8片段，不是完整长文/BP财务提取或跨项目历史RAG。公共候选有界，不是互联网发现/采集。限制在页面及工作流文档公开。
- 引用存在/来源状态校验不是语义蕴含、数字准确性、投资结论或抗所有提示注入攻击的证明；模型无执行工具是主要执行边界，草案仍待人工审核。
- 没有阶段六关键数字、正式报告模板/审核动作/导出；没有业务效果数据集、生产并发/成本压测、服务商保留政策验收或可用性保证。配置有值不等于连接测试成功。
- GitHub Actions 仅保留配置，未执行本轮远端 CI。TestClient 有 httpx 弃用提示，Playwright 有 NO_COLOR 配置提示，不影响通过结果。

配置与边界见 AGENTS_WORKFLOWS.md；下一阶段见 CODEX_TASKS.md。
