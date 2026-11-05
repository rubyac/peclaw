# 数据库设计

阶段二 Alembic revision：`0002_identity`，继承 `0001_platform` 的 pgvector 扩展。阶段二创建以下七张业务表；实际约束见 app/models/identity.py 与显式迁移。

| 表 | 关键字段与约束 |
| --- | --- |
| users | UUID、唯一规范化 email、full_name、Argon2 password_hash、is_active、created_at |
| organizations | UUID、name、created_at |
| organization_memberships | organization_id/user_id 复合主键，role CHECK owner/admin/member/viewer，is_active |
| auth_sessions | token_digest 主键、user_id、expires_at、created_at、revoked_at；不保存原始令牌 |
| projects | UUID、organization_id、name、description、created_by；id/org 复合 UNIQUE |
| project_memberships | project_id/user_id 主键，role CHECK manager/editor/viewer；项目/org 与机构/user 双重复合 FK |
| audit_logs | organization_id 可空（安全域）、actor_id、action、resource_id、result、request_id、受控 JSON 元数据、时间 |

私有授权必须匹配有效账号、有效机构成员和相应项目角色。Organization delete cascade 仅为数据一致性/测试清理；本阶段没有 HTTP 删除机构功能。审计无修改/删除 HTTP 接口，数据库管理员仍有物理权限。

`alembic check` 可比较模型与库结构。schema 不在应用启动时自动创建；Compose 的一次性 migrate 服务运行 upgrade head。**本阶段 downgrade 会删除身份、项目与审计数据，只能对独立测试库执行。** 生产迁移应由专用高权限角色执行，运行账户采用最小权限；当前开发配置尚未实施分角色。

后续模型按 PRD 第六、七、九、十部分逐阶段扩展：Company/别名、Product、Technology、IndustryNode、DataSource、Evidence；Document/Version/Chunk；TaskRun/AgentRun/Report/Review/KeyMetric/Export。关键事实分类 fact / inference / unverified / unknown / conflicting。未知字段允许 NULL/unknown，不静默补全财务数字或上市状态。后续所有私有记录、索引、缓存与任务需带机构及项目上下文。


## 阶段三（历史 head：0003_catalog）

新增 12 张公共数据域表：data_sources、companies、company_aliases、industry_nodes、technologies、company_industries、evidence_records、company_technologies、products、company_changes、company_merges、catalog_imports。users 增加 is_data_curator，server default false，已有机构成员不会自动升级权限。

Company 的 version + 行锁控制修改与合并并发；归档与 merged_into_id 都不物理删除。CompanyChange 保留快照与来源/原因；CompanyMerge 保留两侧原始快照和撤销记录。别名用 NFKC/casefold/空白归一化派生键，实际名称保留原文；名称不做全局唯一约束，更不能凭同名自动合并。

DataSource 记录许可、允许用途、共享确认与原始定位。Evidence 绑定企业、具体主张、摘录、页/节、分类与核验状态。产品与技术关联引用同企业证据，由服务层校验企业和来源归属；拒绝状态会反映在查询中。公共域没有 organization_id，不作为机构私有文档的存储表。

CatalogImport 的 (requested_by, idempotency_key) 唯一，原始输入仅持久在数据库中供内部 worker 使用，不由状态 API 返回；输入摘要辅助复现。worker 使用 SKIP LOCKED + 事务/savepoint；成功数据与任务结果原子提交。CompanyChange.import_fingerprint 对来源+行内容唯一，重复导入不覆盖手工更新。

本轮迁移不修改既有私有项目数据；downgrade 将删除公共目录数据和权限标记，只能对临时测试库进行。正式库升级前应备份，数据版本和回滚仍由运维流程控制。

## 阶段四（历史 head：0004_knowledge）

新增 private_documents、private_document_versions、private_document_grants、private_document_chunks。文档与项目、版本与文档、片段与版本采用含 organization_id/project_id 的复合外键；授权还绑定项目成员。版本按文档顺序唯一，幂等键按原上传用户唯一；requested_by 可在重试时改为当前合法编辑者。删除文档级联清除数据库子记录，应用逻辑删除则保留元数据并清索引/原对象。

chunk 同时保存 text、TSVECTOR GIN、pgvector Vector(300)、embedding_model、SHA-256 与定位；没有跨租户近似向量索引。S3 key 只保存在版本表，API 不返回。任务租约、token、次数和错误码持久化在版本表中。升级/回退须遵守既有仅独立测试库 downgrade 的规则，正式回退会丢失知识库数据。

## 阶段五（历史 head：0005_agents）

新增 agent_tasks / model_calls。Task 带 org/project 复合外键、发起人、输入 JSON、输入摘要/幂等键、kind、提示词版本与摘要、证据引用/摘要、结构化结果、状态/次数/租约/token 与时间。幂等按发起人唯一，组织/项目级索引支持私有查询。证据引用不保存整份原文副本，读取重新授权；模型草案仍属私有数据。

ModelCall 带 task/org、attempt 唯一约束、提供方/模型、预留 token、服务商实际 token、耗时、受控错误、可空的微美元估算。没有凭据或原始响应正文。每日预算按组织行锁序列化预留，失败/中断 reservation 不自动返还；取消的在途请求仍占并发位，避免取消绕过上游限制。迁移回退会删除任务/用量数据，仅在独立测试库执行。

## 阶段六（当前 head：0007_review_snapshots）

0006_reports 新增 reports、key_metrics、report_reviews、report_exports，0007_review_snapshots 为审核记录添加私有不可覆盖内容快照，并为既有行安全填充空 JSON 后移除服务器默认。没有快照的历史行明确不可用，不伪造历史内容。

Report 带 org/project 复合 FK、参与人/来源任务、模板版本、私有正文与引用、revision、批准修订/指纹。KeyMetric 带 report/org/project 复合 FK，十进制字符串、单位/币种/期间、精确引文、核验人/时间/备注；不通过 float 舍入。Review 是追加记录，保存修订/决定/确认项/摘要和当时内容/数字/来源快照。Export 保存报告作用域、修订、用途/格式、报告/文件摘要、发起人及幂等，不保存公开对象 URL 或导出文件本体。

编辑与审核锁定 Report 行并验证 expected_revision；变更撤销批准，导出锁定当前快照、复核来源与审核人后提交记录并返回字节。报表历史按当前参与人/原文权限授权，不等于 DB 层独立 RLS。回退会删除报告数据或审核快照，仅对独立测试库执行。

## 阶段七迁移

`0008_evaluation` 新增 evaluation_datasets、evaluation_runs、evaluation_feedback，保存不可覆盖的定义/来源摘要、执行租约与结果摘要、带身份和结果绑定的反馈。数据集版本唯一范围为机构、项目、创建者、名称和版本；`0009_eval_scope` 修正该范围。创建幂等键仍按创建者唯一，跨项目复用返回冲突。当前迁移头为 `0009_eval_scope`。

撤销评审改变当前访问资格，保留定义中原始声明与历史反馈。降级 0009 前若存在旧约束不能容纳的跨项目同名版本，会拒绝降级，避免损失数据；先在隔离库演练。
