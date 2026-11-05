# API（阶段七）

版本前缀 `/api/v1`。完整实时 Schema：FastAPI `/docs`、`/openapi.json`。浏览器通过 Next.js `/api/...` BFF 调用，BFF 不提供任意转发目的地或路径。

## 身份

| 方法与路径 | 行为 |
| --- | --- |
| POST /auth/login | email/password；受信 Origin；成功设置 HttpOnly Cookie，返回用户与 csrf_token |
| GET /auth/me | 当前用户、有效机构及角色、csrf_token；无会话 401 |
| POST /auth/logout | CSRF + Origin，撤销当前会话，清 Cookie，204 |
| POST /auth/password | current_password/new_password；CSRF + Origin；撤销所有会话，204 |

登录限流 429，Redis 故障 503，错误账号/密码/停用用户统一 401。浏览器同源请求自动携带 Origin；其他客户端需显式设置允许的 Origin 并维护 Cookie，写请求带 X-CSRF-Token。新密码长度 12–256；没有默认账户或公共注册。

## 机构与成员

以下路径均在 `/organizations/{organization_id}` 下。

| 方法与子路径 | 行为 |
| --- | --- |
| GET /members | 机构 owner/admin 读取成员（含成员状态与全局用户状态） |
| POST /members | email/role，将已开通账号加入当前机构；重复 409；不创建/重置全局密码 |
| PATCH /members/{user_id} | role/is_active，更新本机构资格；管理员不可操作 owner；最后 owner 不可降级/停用 |
| GET /audit?limit=50&offset=0 | 本机构最近审计，limit 1–100，仅 owner/admin |

## 项目

以下路径均在 `/organizations/{organization_id}/projects` 下。

| 方法与子路径 | 行为 |
| --- | --- |
| GET （根路径） | 仅当前机构内已分配给自己的项目 |
| POST （根路径） | name/description，当前用户为创建者与项目 manager；机构 viewer 不可创建 |
| GET /{project_id} | 同时检查机构成员和项目资格，无资格 404 |
| PATCH /{project_id} | name/description，要求机构非 viewer 且项目 manager/editor |
| GET /{project_id}/members | 项目 manager 或机构 owner/admin 管理 ACL 所需列表 |
| PUT /{project_id}/members | user_id/role：设置同机构有效用户的 manager/editor/viewer 项目角色 |
| DELETE /{project_id}/members/{user_id} | 撤销项目资格；保留至少一个项目 manager；成功 204 |

项目返回 id、organization_id、name、description、created_by、created_at、my_role、can_write、can_manage_members。前端据此显示控件，但真正授权仍在后端。输入拒绝多余字段，不能通过请求体注入机构或创建者。

## 健康与异常

GET `/health/live`：进程存活。GET `/health/ready`：数据库连接 + 当前 Alembic head + pgvector、Redis PING、S3 bucket HEAD。全就绪 200，有依赖故障 503；只返回 ok/error，不泄露配置。健康状态响应不使用错误信封。

其他错误结构：`{"error":{"code":"HTTP_404","message":"资源不存在","request_id":"uuid"}}`。401 登录失效/凭据错误，403 操作无权限/CSRF，404 私有资源不存在或不可读，409 角色不变量或成员重复，422 输入无效，429 限流。特定 code 包括 INVALID_ORIGIN / LAST_OWNER / LAST_MANAGER。私有响应 Cache-Control=no-store，API 附 X-Request-ID；不回显校验输入或底层异常。

文档、Agent 与报告接口仍未实现，不提供假占位成功响应。


## 公共企业库

以下均在 `/api/v1` 下。有效机构成员或全局公共数据维护员可读；所有写操作仅 data curator 且使用现有 Origin + CSRF。机构 owner/admin 不获得额外公共写权限。

| 方法与路径 | 功能 |
| --- | --- |
| GET /catalog/sources | 来源与许可信息 |
| POST /catalog/sources | 登记允许共享的来源，public_confirmed 必须 true |
| GET /catalog/taxonomy | 行业/产业链节点与技术分类 |
| POST /catalog/taxonomy/{industries或technologies} | 创建分类，产业父子层级最多 6 层 |
| GET /companies | SearchFilters 查询参数与分页，输出 total/items/limit/offset |
| POST /companies/search | query + filters，返回应用条件与未执行条件提示 |
| POST /companies | 创建档案，来源与原因必填，未知不补齐 |
| GET /companies/{id} | 基础档案、来源、证据、冲突、产品、技术及合并关系 |
| PATCH /companies/{id} | canonical_name/source_id/reason/expected_version；未提交其他字段保留 |
| POST /companies/{id}/archive | archived true/false、source_id/reason/expected_version；归档/恢复 |
| GET /companies/{id}/history | 原值、新值、来源和原因 |
| GET /companies/{id}/duplicates | 维护员查看疑似重复，含截断提示 |
| POST /companies/{id}/evidence | 保存具体主张与原文，默认待核验 |
| PATCH /companies/{id}/evidence/{evidence_id} | 人工核验状态与原因 |
| POST /companies/{id}/products | 同企业/同来源证据支撑的产品 |
| POST /companies/{id}/technologies | 技术与企业关联，需同企业证据 |
| POST /companies/{id}/merge | duplicate_id、两侧版本、来源、原因、confirm=true |
| POST /catalog/merges/{merge_id}/undo | 原因、来源、两侧当前版本；撤销关联 |
| POST /catalog/imports | 异步导入，202 与任务状态 |
| GET /catalog/imports | 当前维护员最近 50 个导入任务 |
| GET /catalog/imports/{id} | 任务状态/行结果；不返回原始输入 |
| POST /catalog/imports/{id}/retry | 失败任务重试，最多三次执行 |
| GET /catalog/audit | 全局维护员读取仅 catalog.* 的公共维护审计，不混入机构私有操作 |

来源、企业、检索、导入任务输出有 Pydantic DTO，防止将 ORM 新字段意外暴露为 API。批量文件通过 base64 JSON 提交，BFF 对导入路径限制 2 MiB、其他业务 JSON 64 KiB，文件本身限制 1 MiB。具体字段、枚举与人工流程见 CATALOG.md / OpenAPI。

## 阶段四私有知识

`K=/organizations/{org}/projects/{project}`，`D=K/documents/{document}`。所有接口要求登录，写请求要求受信 Origin 与 CSRF；搜索虽用 POST 也需要 CSRF。具体字段与错误结构以 OpenAPI 为准。

| 方法与路径 | 行为 |
| --- | --- |
| GET K/documents | 项目与文档 ACL 过滤；offset/limit，编辑者可 include_deleted；管理者的未授权文档脱敏 |
| POST K/documents | title/filename/content_base64/idempotency_key/access_scope/reader_ids；202 后台解析 |
| GET K/knowledge-members | 当前项目有效授权候选，仅项目编辑者可用 |
| GET D | 允许读取者的文档与版本，不返回存储 key 或向量 |
| POST D/versions | 文件字段与 expected_revision；新版本，202 |
| GET D/download?version=n | 重新鉴权、哈希校验、附件响应，不缓存、不签发对象 URL |
| GET D/chunks?version=n&offset=0&limit=50 | 指定版本已索引片段与定位信息 |
| GET/PUT D/permissions | editor 或实际项目 manager；PUT expected_revision/access_scope/grants |
| DELETE D | JSON expected_revision；立即撤索引并排队清理全部原文，202 |
| POST D/retry | expected_revision；重试失败索引或已删除原文清理，202 |
| POST /organizations/{org}/knowledge/search | query/mode(keyword,semantic,hybrid)/project_id(可空)/limit；仅当前版本且授权 SQL 候选 |

并发修订冲突或执行次数耗尽返回 409；越权私有资源通常返回 404。原文不可用返回受控 503。上传校验上限 10 MiB；BFF 文件 JSON 请求限 15 MiB（base64 膨胀），其余私有请求 64 KiB。原文件名经 RFC 5987 编码，响应为附件与 nosniff，正文不直接当 HTML 打开。引用含文档/版本/项目、哈希、定位、偏移与 excerpt，不含概率式“置信度”。

## 阶段五 Agent

`T=/organizations/{org}/projects/{project}/agent-tasks`。需要登录；写请求仍要求受信 Origin 与 CSRF。任务只对发起人开放，同时要求有效项目及所有证据文档授权。

| 方法与路径 | 行为 |
| --- | --- |
| GET /agents/config | 安全模型状态、五工作流定义、固定提示词版本/摘要、输入/输出 JSON Schema；不返回 key 或端点 |
| POST T | kind/question/idempotency_key，加 company_id/document_ids/thesis/filters/allow_private_to_model；202 |
| GET T?offset=0&limit=50 | 当前项目本人任务的有限状态元数据；没有输入、证据或生成内容 |
| GET T/{id} | 当前授权重新校验后返回输入、结构化草案、定位证据及调用用量 |
| POST T/{id}/retry | expected_attempts；仅 failed 且次数<3，202 |
| POST T/{id}/cancel | expected_attempts；queued/执行中取消，token 作废，202 |

kind 为 company_discovery/company_profile/project_match/bp_screening/due_diligence。company_profile/project_match 必须 company_id，project_match 必须 thesis，bp_screening 必须 document_ids；私有材料必须 allow_private_to_model=true。所有 scope/actor 身份由路径和会话确定，输入额外字段拒绝。详情引用过期返回 EVIDENCE_CHANGED 或受控不可用状态，越权通常404；修订/状态冲突409。

每个模型 HTTP 请求均有独立调用记录，无隐藏重试。错误代码涵盖未配置、鉴权、限流、网络、超时、服务不可用、响应截断、Schema/引用不合法、事实来源未核验、预算/权限/证据变更。错误不带服务商原始 body。review_required 仅表示草案待人工审核，不是已审核。取消不能保证上游停止计费。

## 阶段六报告

`R=/organizations/{org}/projects/{project}/reports`。所有详情/写入/导出检查作者或明确审核人、有效机构/项目资格，以及全部引用的当前来源版本与文档 ACL。写接口继续要求受信 Origin 与 CSRF，变更使用 expected_revision。

| 方法与路径 | 行为 |
| --- | --- |
| GET /reports/templates | 五模板、章节、strict@1.0.0 与草稿导出开关 |
| POST R | title/template/idempotency_key；人工 company_id/document_ids 或本人的 source_task_id，201 |
| GET R | 本人创建/获明确审核授权的有限状态元数据，offset/limit，无标题/正文 |
| GET/PUT R/{id} | 重新授权后的正文/质量闸/数字/审核/导出记录；PUT title/content/expected_revision |
| PUT R/{id}/reviewer | reviewer_id；另一位有效项目编辑者，重置旧批准/数字核验 |
| POST R/{id}/metrics | 关键数字、精确引文、单位/币种/期间，201 |
| PUT/DELETE R/{id}/metrics/{metric} | 作者修改/移除登记，修订递增并撤销批准 |
| POST R/{id}/metrics/{metric}/review | 指定审核人 verified/conflicting/rejected/not_applicable，加 notes |
| POST R/{id}/submit | 作者提交当前 draft，要求有效独立审核人 |
| POST R/{id}/review | 指定审核人 approve/request_changes、notes；批准须全部五项明确确认且质量闸通过 |
| GET R/{id}/reviews/{review} | 当前授权与来源重验后的不可覆盖审核快照 |
| POST R/{id}/export | expected_revision/mode(draft,formal)/format(md,docx)/idempotency_key，返回附件字节 |

导出没有长期公开链接或附件缓存；X-Export-ID、X-Content-SHA256 与附件文件名由服务端生成。相同键/输入可重建同一字节文件，但重放必须通过当前授权。BFF 的报告请求限1MiB，响应不缓存。质量问题、批准失效/来源变化或修订冲突返回受控409，越权通常404；具体字段以 OpenAPI 为准。

## 阶段七评测接口

`GET /api/v1/evaluations/definitions` 返回案例契约。项目内 `/api/v1/organizations/{org}/projects/{project}/evaluations` 支持 GET 列表、POST 创建；`/{dataset}` 读取定义，`/{dataset}/runs` 创建运行，`/{dataset}/reviewer` DELETE 撤销评审访问。运行入口为上述项目入口下的 `/runs/{run}` 支持 GET 结果，子路径 `/export` GET 下载 JSON、`/retry` 和 `/cancel` POST、`/feedback` POST。

创建绑定当前来源版本并验证项目/原文/报告参与权限。写请求需要 Origin、会话和 CSRF；使用 UUID 幂等键，跨项目复用创建键返回 409。反馈绑定结果摘要及已测量案例，独立身份由服务端计算。下载、旧结果读取和重试持续检查当前授权。完整语义见 EVALUATION.md 与 OpenAPI。
