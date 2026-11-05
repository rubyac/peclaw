# 公共企业数据库使用说明（阶段三）

## 数据与权限边界

公共目录与机构私有项目是独立的数据域。有效机构成员可读公开档案；只有部署操作员授予 is_data_curator 的用户可写。owner/admin 的机构管理权限不隐含公共数据发布权，也不能通过成员 API 给自己加此标志。维护员权限由 `app.provision --data-curator grant/revoke` 单独管理，每次请求重新检查，不放在前端或会话权限缓存中。

来源必须声明 source_type、license_type、permitted_use、public_confirmed。真实资料需 HTTP(S) 来源定位地址；synthetic_demo 是唯一允许无外部地址的演示类型。确认框明确针对平台所有有效机构共享。系统记录人工许可声明，不替代法律授权核查，没有自动抓取或授权 API 供应商接入，也没有把机构私有项目转换成公共数据的接口。

## 档案、来源与核验

企业保存标准名、登记名、别名、信用代码、国家地域、官网、成立日期、上市/发展/融资阶段及简介。上市状态默认 unknown，发展/融资/国家也默认 unknown；未找到信息不等于未上市或未商业化。

创建/编辑需要 source_id 与 reason；更新还需 expected_version。PATCH 必须提供 canonical_name，但其他未提交字段保留；明确 null/[] 表示清空可空字段/列表。版本不一致返回 409，不能覆盖新的变更。前后值、来源、时间、原因、操作者都写入 CompanyChange；每次编辑不自动将档案认定为已核验。

Evidence 关联具体企业、主张、摘录、来源和页码/章节，区分 fact / inference / unverified / unknown / conflicting；核验状态单独记录人工审核人和时间。推断不能直接标为已核验事实。相同字段的不同说法及合并档案的关键状态差异会展示，不静默择一。核验作用于具体证据，不代表整家企业全部资料都已核验。

产品必须引用同企业、同来源且未被拒绝的证据；技术关联必须引用该企业证据。技术产品参数、量产、客户和财务不由标签自动推断。产品/技术关联当前支持登记与查看，错误引用可通过证据拒绝记录提醒，完整产品版本维护后续扩展。

## 搜索与产业地图

结构化筛选支持名称/别名/文本、国家、地域、上市/发展/融资阶段、产业、技术、来源、成立日期范围、更新时间、归档与分页。产业节点筛选包含后代节点，技术筛选按明确关联。合并组以主档案的基本状态筛选，名称/别名、产业/技术关联可检索其关联原始档案；不会擅自将子档案的已知状态覆盖主档案的未知值。

自然语言是可解释规则匹配，当前支持已维护产业/技术名称与技术别名、中国、部分省市、上市及发展阶段词。返回 matched_intent、applied_filters、unparsed_criteria 和限制说明。仅执行列出的条件；营收、利润、客户等描述不作为已满足条件；排除等未支持的组合表达返回 422，不能误当正向筛选。它不是模型语义搜索或完整市场发现。

`/industry` 提供真实维护的产业节点和技术路线，可点击查看关联企业，最多展示 50 家并标明总数。没有企业关联不代表市场中没有该类企业。

## CSV / XLSX 导入

模板：`examples/companies.csv`，全部为虚构企业。英文表头，UTF-8（可带 BOM），XLSX 单表，最多 200 数据行/1 MiB。空单元格采用 unknown/null，不用 0 代替未知财务数据。

字段包括 canonical_name（必需）、registration_name、aliases（用 | 分隔）、unified_social_credit_code、country、province、city、website、description、founded_on、listing_status、company_stage、financing_stage、industries、technologies、technology_excerpt。列表行业/技术以 | 分隔；存在技术时必须有 technology_excerpt。分类会在必要时创建，技术证据标为待核验，并登记任务 ID 与行位置。

枚举：listing_status=unknown/listed/unlisted/delisted；company_stage=unknown/research/prototype/pilot/commercial/scaled；financing_stage=unknown/seed/angel/A/B/C/pre_ipo/other。CSV 中明确的 code 值必须符合这些枚举。公司身份疑似重复的行输出 review_required，可查看候选后人工判断是否确属同一企业；不同企业可用手工新建表单登记，不能依名称自动合并。

任务 JSON 输入为 source_id、reason、format、content_base64、idempotency_key、public_confirmed。相同用户+幂等键+同内容返回同任务；同键不同内容 409。任务中保留原始受限输入与摘要，HTTP 状态接口不返回原始文件；仅任务发起维护员可查看自己的任务。独立 worker 通过 PostgreSQL 行锁认领，在执行前重新查账号与维护权限。输出和档案在同一事务提交，每行使用 savepoint；重复来源/行指纹跳过，不覆盖后续手工修改。

状态 queued/running/completed/failed，attempts 上限 3；失败有受控错误码，行结果区分 created/skipped/review_required/error。completed 只代表处理结束，不代表每行成功，必须看计数。挂起进程 120 秒租期到期可恢复，第三次崩溃会标为 failed 而不是永久 running。格式错误需修正文件后新建任务，反复重试相同错误文件不会使其有效。

## 人工去重

候选依据信用代码、登记名称、官网域名、标准名称/历史别名和名称相似度。名称相似不自动合并，不输出伪精确的企业身份概率。模糊扫描最近 1000 条，强匹配也有限制，返回 scanned/truncated；达到限制时界面说明候选不是完整集合。

合并需人工确认、原因、来源和两侧版本；仅关联，不搬移/覆盖企业或证据，子档案原 ID 仍可读取，编辑需先撤销合并。目标可累积多个子档案；作为被合并方的档案不能已经拥有子档案，需先撤销旧关系。撤销同样检查版本、记录历史，保留合并后在主档案新增的内容。归档不物理删除，已归档身份仍被导入去重识别，不被自动重建。

本轮没有真实企业数据供应商、500 家已核验数据集、公开新闻事件采集、观察清单通知、Agent 画像或投研报告。这里的“企业画像”是来源支撑的基础档案展示，不是生成式投资结论。
