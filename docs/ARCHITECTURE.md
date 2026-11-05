# 架构

采用模块化单体：Next.js 服务端页面 → FastAPI → PostgreSQL + pgvector / Redis / S3 兼容存储。仅为未来后台任务预留独立执行进程，不拆分业务微服务。

阶段一实现：前端真实健康状态界面；API 统一异常与请求标识；区分 liveness 与 readiness；迁移启用 pgvector；初始化私有 bucket。Redis 为任务队列提供基础设施，目前没有伪装已实现的 worker。

模块依赖方向：api → services → models/repositories；schemas 定义接口契约；core 管理配置和数据库。公共企业信息、机构私有知识、投资工作流是后续三个业务域。所有模型调用必须经未来统一 Model Gateway，不能在业务接口直接调用服务商。

后续文档解析、批量导入、研究和初筛由后台任务执行，携带机构、用户和项目上下文；状态、检查点、失败原因和重试计数持久化，幂等输出避免重复报告。当前尚未实现该状态机。

API 不配置宽泛 CORS：浏览器不跨域直连 API，Next.js 服务器调用 API。当前阶段没有私有数据和业务接口。


## 阶段二身份与私有空间

浏览器 → Next.js 固定路由 BFF → FastAPI 认证与资源权限 → SQLAlchemy。随机会话令牌只放 HttpOnly Cookie；后端存摘要、每次重新验证账号与资格。BFF 只转发固定业务路径，限制请求体 32 KiB，保留 Set-Cookie、request-id 并禁止缓存；没有用户控制的任意代理地址。

新增 security（passwords/dependencies/rate_limit/tasks）、identity 模型、auth/organizations/projects API、audit 服务与操作员 provision CLI。角色与项目 ACL 是后端权限的交集。所有机构私有查询限定机构；项目还检查项目成员关系，组织管理员管理 ACL 的能力单独审计。

Next.js 新增 /login、/projects、/members、/audit、/account。机构切换取消旧查询，并清除上一机构视图状态。页面权限控件使用后端返回能力；后端拒绝请求不依赖隐藏按钮。

TaskContext 和授权 guard 已具备，验证后台独立数据库 session 的租户上下文与权限撤销；任务队列与工作流状态机仍待阶段五实现，不声称已有后台执行服务。


## 阶段三公共目录与导入执行进程

新增 catalog 模块：权限、档案服务、规则检索、去重、文件导入；统一通过现有 FastAPI、SQLAlchemy、审计和配置。只增加 catalog-worker 执行进程，不拆分业务微服务。数据在 PostgreSQL；本阶段采用持久数据库队列（同等异步方案），Redis 仍用于登录限流。Compose 启动 worker，本机开发需单独运行 app.catalog_worker。

导入先创建任务，再由独立进程认领、重新检查维护员资格、解析/验证、逐行 savepoint、记录证据与结果、原子提交。租期过期可恢复崩溃任务，最多三次尝试。名称相似不自动合并；人工合并只是关联，撤销不恢复整个旧快照去覆盖新数据。

前端增加企业列表/详情、只读产业地图、维护员来源/分类/导入页面。API DTO 列出公共字段，机构私有项目不参与公共搜索。自然语言仅为可解释规则，未知与未执行条件显式展示；没有外部模型、供应商采集或伪造的企业样本。

## 阶段四私有知识与独立解析进程

Next.js /knowledge → 受限 BFF → FastAPI 知识库路由 → 多层 ACL → 私有 PostgreSQL 表与 S3。knowledge-worker 从数据库领取租约，读取并校验原文件，在资源受限子进程中解析，以本地 spaCy 中文词向量建立 pgvector 与 FTS 索引，最终持锁重验资格和删除 token 后原子提交。检索只读当前已完成版本，授权 SQL 过滤后关键词/精确向量候选以 RRF 融合。完整能力及边界见 KNOWLEDGE.md；此文前面阶段一/二的“尚未实现”描述是历史状态，当前已有目录和知识库两个专用 worker，仍没有通用 Agent。

## 阶段五统一 Gateway 与显式工作流

Next.js /agents → 固定 BFF 路由 → TaskInput/权限/幂等 → PostgreSQL 任务 → agent-worker。工作流按授权→有界证据→机构预算/并发预留→Gateway chat completion→Pydantic Schema/引用校验→重验权限→review_required 执行，不允许模型自主调用工具。Gateway 同时封装现有本地 embedding，不改变其模型或索引。提供方失败为明确错误码，未配置时不会虚构结果。持久记录提示词版本/哈希、模型、token、耗时和未知/可计算费用。详细限制见 AGENTS_WORKFLOWS.md；阶段六人工审核动作与正式报告导出尚未实现。

## 阶段六报告与守卫导出

/reports 页面经固定 BFF 请求 FastAPI reports 模块，以 Report 行锁和 revision 统一正文/数字/审核/导出操作。输入可为人工模板或已完成 Agent 草案，不要求模型。数字用精确十进制字符串登记、逐项复核，再由不同参与人确认完整性。审核记录追加当时快照，批准绑定内容指纹；来源解析在该模块额外要求私有引用仍为当前文档版本。

导出在内存中生成 Markdown 或 DOCX，正式版本通过质量闸并重验审批资格/引用权限，返回附件和摘要，仅落导出元数据。没有无需权限检查的对象链接。阶段六工程流程不是业务质量验收，阶段七仍需授权数据和真实评估。

## 评测执行边界

`app.evaluation` 分离定义绑定、纯指标、执行与本地演示工具；`evaluation-worker` 从 PostgreSQL SKIP LOCKED 领取运行，300 秒租约、至多三次领取、逐案例及提交前重新授权。调用既有企业/知识检索，读取已完成 Agent 输出，使用报告机械质量闸；不会直接访问模型提供方。结果记录实际过滤条件、检索模型、来源摘要、执行人及结构化输出。反馈在读取时聚合，明确区分作者与独立判断。参见 EVALUATION.md。
