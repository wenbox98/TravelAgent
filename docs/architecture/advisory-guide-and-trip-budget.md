# 建议攻略与旅行花费：v4契约变更

## 默认与兼容

日常新旅行使用 `PlanDraft.planning_mode=ADVISORY`，首项/结束属性默认FLEXIBLE，钟点为空。旧JSON缺失字段时仍按DETAILED/LOCKED读取，旧采用快照不重写。已有固定验收demo保留原义；新的GUIDE_MULTI_DAY只是明确自编测试入口，使用普通P07许可，不建立阶段预算常量。

模糊需求中的“十点左右开始”记录软偏好；明确返回时间记录硬截止。没有关联项目或上午下午不明确的预约保留hard_notes，在页面提示确认，不猜测时段。结构化预约由活动locked_start持有；模型无法改写首项钟点、交通、硬截止或锁定项。时间建议不是可行性保证。

## 复用生产路径

`suggestions.payload_for → advisory.payload → planning_advisory_v4 → advisory.validate → apply`复用原工作进程、120/180秒截止、耐久许可和调用账本。输入仍由private_payload/KnowledgeBinding过滤；知识路径不读正文。候选只来自当前提供且有效的活动/卡片。每方案独立结构、引用、上下文、城市范围和硬约束检查；一个被拒不丢弃其他合格项。UNKNOWN可以暂定，MISMATCH不会进入市区选择。

新 `GuideResponse/GuideProposal/GuideActivity/GuideContent` 分离建议内容；模型不能输出不可见的任意地点、商家、交通事实或报价。安全且有限的结构化响应沿用7天私人诊断，按v4规则本地回放；不保存推理、原始网络响应、模型输入到Git。

1.2规则补充：旧walking_allowed=false在新建议输入中解释为未选择，即null，不表达禁止步行；模型不得凭空声称步行不可用。已有明确人数/房间/天晚口径不能在预算条件中变为未知。版本或输入变动后，旧提议重新验输入与规则，历史计数保留但不代表当前可采用；详见P09两次实测失败记录。

## 组合、食宿与本地计算

组合使用持久activity_pool并逐次重验引用，preview_combination保存修改前草稿；取消恢复，采用前再验，修订失效/晚到任务不覆盖采用版。停留和日段可本地修改，AI停留一直保留建议性质。餐饮枚举只表示用餐策略，住宿枚举只表示取舍原则；区域名必须来自输入，人数、房间、晚数未知不补默认值。

复用初始契约的AmountRange/BudgetLine名字，显式增加basis、activity_ids、unit、paid_fen、locked、is_synthetic等字段。状态QUOTED/ESTIMATED/HISTORICAL/PAID/UNKNOWN与依据分别保留：AI_BUDGET_PROPOSAL/USER_BUDGET_TARGET是计划预留，OBSERVED_QUOTE必须有报价引用和查询时间，HISTORICAL_REFERENCE有历史引用；未知与不适用/自行安排分开。普通编辑不能制造外部报价，模型也不能写已付或实际报价。

TripBudget用整数分计算人数×天数、房间×晚数、一次性或每日项。备选活动未选不计，部分拆分不了的套餐变未知；被包含明细不双计，已付从预计剩余中扣一次。人数未知可单列每人项，房费不自动平摊。所有小计都称已计入部分；软目标只提醒，硬上限保留为用户约束，不自动删项。

这些结构存于原preview_sessions.state_json的PlanDraft；SQLite版本仍16，无数据回填、无budget_lines表删除或旧额度重置。旧SQL预算/报价表仍是早期草案，当前没有供应商接通。同步domain.schema.json与openapi.yaml，通过显式契约变更提交发布。

## 页面与导出

同一8768主入口加入AdvisoryGuide，现有研究、知识、地图能力保留。普通编辑只保存草稿；组合与模型替换预览后采用。额度耗尽、未配置仍可本地修改、算费用、折叠与导出。

`GET /api/v1/preview/planning/{session_id}/guide-export`沿用本机认证与同源防护，读取采用版，重验卡片/引用后生成转义Markdown。不导出全文、原模型输入、私址、诊断或临时地图值。刷新重启不派发外部请求，导出不是重新生成建议。

`GET /api/v1/preview/planning/{session_id}/guide-download`使用同一生成与鉴权路径，将相同Markdown作为`Content-Disposition: attachment`的UTF-8文件返回；旧JSON接口保留。普通页面使用原生下载链接，不依赖立即销毁的临时Blob，不把点击当作文件已保存。没有采用版时不提供链接；引用失效继续拒绝，不修改数据库、采用版与账本。OpenAPI同批增加此下载契约；domain和数据库不变。

范围：关键词资料库继续可用，向量仍NOT_IMPLEMENTED；G1保持历史NOT PASS；不新增供应商、酒店抓取、自动预订或复杂求解器。

## P09.1 / 1.3 最小契约调整

PlanDraft.walking_allowed 改为 bool|null；walking_origin 记录 UNKNOWN/USER_EXPLICIT。新建议旅行默认 null。guide_context.walking 只将可证明的明确拒绝保留为 DECLINED；旧未勾选 false 不推断禁止，原快照不回填。柔性“不想多走路”不产生绝对限制。普通页面三态选择、保存及 worker 共用语义；交通选择与明确拒绝冲突时阻止保存或采用。

GuideProposal/GuideContent 增加 walking_requirement NONE/OPTIONAL/REQUIRED。UNKNOWN 只允许 NONE/OPTIONAL，采用不会把待选择的建议改为用户同意；DECLINED 不允许依赖步行。引用、范围、事实、预约与逐方案独立校验保持有效。

guide_context.budget_context 从当前旅行生成已知/待补条件，供 payload、计算、页面和 Markdown 共用。模型不重抄人数/天数/房晚；实际价格未知不能被误作人数未知。模型输出 schema 将 quantity 限定为 1，程序按 unit 乘 people/days/rooms/nights 一次；普通用户/历史 BudgetLine 数量契约保留。ONCE 表示整个条目的一次性总额，未选活动关联费用由现有计算器排除。

规则版本 advisory-guide-1.3，仍为协议 v4。旧回答与原判定不变；原输入回放、修正输入复核和新请求保持区分。SQLite 仍为 16，无迁移、无预算回填。


## P10 / 1.4 住宿范围与本地复核契约

住宿范围由 `lodging.context` 从当前草稿生成，独立于 BudgetLine 的 basis/status/金额。`TripBudget.lodging_scope=AUTO/INCLUDE/EXCLUDE` 为本次可修改选择；已付、锁定、用户费用和有效报价保留。确认正晚数优先于一日缺省，一日无住宿要求仅建议暂不纳入，不声称用户拒绝住宿。多日未知保持 UNDECIDED；往返自行安排不推断住宿安排。

`BudgetLine.inclusion` 与 `inclusion_origin` 是程序派生信息。仅对 OUT_OF_SCOPE 且无金额、报价、付款、锁定、包含引用或住宿服务断言的空住宿行，记录 EMPTY_LODGING_SCOPE / NORMALIZED；basis/status/金额原义保留。未知金额不写为零；非空住宿冲突、引用、语义、范围、硬约束继续逐方案完整校验。已有报价/历史参考也不得被模型采用覆盖。

原 v4 回复与原失败保持不变。普通 planning action `revalidate_guide` 读取仍有效的7天私人诊断，校验原输入、诊断哈希、当前引用和完整草稿，仅允许新增确定性 lodging_context；结果追加在原 session 的 guide_revalidations。`use_revalidated_guide` 开始可取消预览；采用再次核对 revision、输入、规则版本、结果与引用。结果标 LOCAL_REVALIDATION，活动仍 AI_PROPOSED；不是新模型审核或 Work 人工接纳。过期或失配拒绝采用，GET不会执行回放或网络派发。页面与导出保留派生标记。

领域 schema 显式追加上述字段、两个 action 和 `PlanView.local_guide_review`；HTTP路由和SQLite16表结构不变，无历史回填、无预算迁移。人数、房间和晚数只从本次明确数字短语解析，模型数量仍固定1，由程序乘一次。

显式排除住宿可保留已填晚数而不计入空住宿行；已付、锁定、用户费用和真实引用费用仍优先保留。未知费用即使曾标不适用，也不隐藏其已付记录。

普通资料库入口尚未选入知识且没有采用版时，显式研究/地点发现可切换到本旅行来源通路。安全检查区分公共地铁“号线”和门牌“号”，私址与危险上下文仍隔离；名称线索不提升为 Evidence。建议候选集合只纳入身份已检查且范围不冲突的线索，其他未检查候选不能拖垮独立合法项目的采用。改选组合后由程序给出中性的当前组合说明，标 USER_CONFIRMED；停留保持原来源，原模型标题、回复及旧采用版本不改写。

## 1.5 通用资料用途与多日覆盖

本次为通用生产规则修复，目的地、名称、来源/旅行 ID 和验收编号不参与规则分支。`guide_context.request_quantity/from_request` 解析当前明确的中文/数字天数（天/日）、人/间/晚和轻松节奏；日期、序数、范围、上限及冲突保持未知。`PlanDraft.pace=UNKNOWN/RELAXED` 为本次条件，不继承其他旅行。未知时刻/交通仍可生成。

`guide_assessment.materials` 按已绑定且当前可用的引用区分 NAME_ONLY、ROUTE_CONTEXT、CONTENT_REFERENCE、UNVERIFIED、SYNTHETIC。名称、采用模式和地图身份不能升级成活动体验；EXPERIENCE 标签还须具有超出名称/路线串的内容，才标有内容参考。该分类只是保守结构判断，不是新的作者审核或语义质量证明；历史角色/条件不变。页面片段只来自本地已审核引用/知识，不读原文表，不调用模型。素材不足不阻止有限建议，不能按数量声称充分。

建议输入增加 `material_support` 最小用途元数据及 `planning_context`（当前目标日序、节奏、允许部分结果、不要求精确钟点）。已过滤引用仍只发送一次，不重复添加原文/地图数据。提示明确来源的一日动线不是用户目标天数，轻松多日需求应重新分配已有活动或提出具体休闲取舍，不能用空白填满。

`GuideProposal/GuideContent.day_choices` 是可选的显式日安排：day、kind=REST/SELF_ARRANGED/GAP、reason。它只表达该方案的可修改建议或本次页面选择，不证明现实事实或用户曾经同意。缺失字段默认空，旧记录不迁移。非活动日必须有具体取舍说明；“自由活动/待定/根据情况”等空占位仍判 GAP。该文本检查保守且非完备，不能声称程序能证明任意自然语言理由。

`day_coverage/assess` 从当前项目和有效 day_choices 重新计算每一天。缺日、超范围、未知总天数与内容不足分开，COVERED 只表示日序已有项目或明确取舍，不等于排满/来源充分/交通已通。轻松多日项目集中在一日且其他日缺失时提醒；已知停留下限超过六小时只作节奏提醒，未知交通不当零，不作为硬时限。饭店/酒店预算和用餐占位不计作游玩覆盖。

`advisory.validate` 仍逐方案完整验证引用、事实、范围、锁定项与硬截止；额外检查 day_choices 的边界、重复、与项目日冲突及理由中的事实/交通断言。局部合法方案保留并附派生 assessment，不把 accepted_count 当完整场景成功。只有无锁定首项时，建议可先休息再于后一天安排项目；详细排程原限制不变。`check_transition/verify_current` 在本地保存/采用/导出继续检查日序，不能仅在首次模型返回时验证。

`combine` 改选后再次通过日序约束；新增项目所在日不沿用旧空日选择，删除项目不自动填第二天。页面/导出实时重算覆盖和资料用途，不复用旧的“完整”状态。`current_dining` 清理已无项目且无明确休闲取舍的日期；不足两个项目时不继续显示“两个项目之间”的餐饮说法。取消仍恢复原草稿，采用版/历史模型回复不回写。

同一 AdvisoryGuide 页面显示逐日缺口、资料用途、必要原引用片段和可编辑的休闲/自行安排理由；Markdown 经原鉴权出口从采用版计算相同评估，不修改已导出的历史文件。新评估的规则版本为 advisory-assessment-1；模型规则 advisory-guide-1.5，协议仍 v4。新增 DTO、domain schema、前后端和离线回归同批提交；OpenAPI 路由不变，SQLite16 不迁移，无旧预算修改。本轮无真实外部请求，新模型效果未宣称实测通过。

## 研究入口的材料用途匹配

普通 ADVISORY 研究任务将内部 ResearchRequest 的问题设为玩法、体验差异与取舍，FocusedPlanner 据此补充体验内容；历史详细研究保留路线问题及明确交通条件。没有把私人自由文本直接拼入站点查询，也没有另一次模型分类调用。

`research.material_eligibility.skip_reason` 复用当前问题和 ResearchGap.topics，在既有过滤与长度上限之后检查路线或具体体验描述。没有路线词不再必然跳过展陈、手作、观赏等描述；纯标签、名称列表、无正文、只有图片指针与明显无关文字仍跳过。混合图片指针和独立文字只评估可用文字，不改原文、不替代严格引用与上下文审核、不新增 OCR。

这些词和描述信号只决定是否在已授权额度内尝试提取，不证明相关性或真实性，也不保证理解任意自然语言。地点名、目的地、来源或旅行标识不用于特殊放行。旧提取、待审和拒绝保持原判；可提取的片段未通过后续审核不能进入 Evidence。现有协议、公开 DTO 与 SQLite16 不变。

## 已审核背景的作用范围关联

`scoped_context`（scoped-context-1）从原审核对象定位、正文定位版本和明确路线成员生成派生关系。PreviewEvidence 保留 route_association 与 source_version；后者使用已经校验的 canonical locator 前缀（规范化版本、正文类型和正文哈希），不把原始缓存哈希与规范化文本哈希混用。不是新 Evidence，也不升级来源角色、范围或地点内容标签。

`derive` 将直接地点内容、整体背景与未关联补充分开。同源/同名/城市/地名子串不足以建立关系；整体背景需同一已审核对象与版本，以及原文明确的路线成员。直接内容限明确主体。保留原条件、否定、季节和作者性质。关系 ID 含规则、来源版本、定位和依据，目标随选择重算；单一来源用于多个项目仍只计一个来源。未关联补充不发送模型。

`private_payload.payload` 对普通引用及混合地点线索先推导关系，再选取直接引用和必要背景/路线依据，通过原 SourcePolicy、外发过滤及每来源6000字限制；重复背景文本也计入限额。地点提及本身始终 NAME_ONLY。P07 新许可绑定当前 context IDs，旧许可不会获得额外材料授权。worker 派发前、返回后及采用时仍重校验 payload/版本/许可。

知识整理仅保存本卡片已审核对象对应的必要背景元信息，卡片版本/来源/删除验证与 no_raw 保留。旧卡片缺元信息就未知；不补读正文猜关系。背景 claim 撤销或卡片版本更新使该绑定失效。普通展示校验本机地点线索，知识展示仅读保留的元信息，无外部调用。

advisory-guide-1.6 沿用协议 v4，新增可缺省的 GuideContextUse：受控 context_id、activity_ids、用途和简短取舍理由。模型不重复抄写源文，程序负责投影全文必要片段、角色和条件。逐方案验证引用、目标与事实边界，拒绝虚构关系或向每站传播特色的方案，保留独立合法方案。确定性自然语言检查仍不完备，不声称等同外部事实核实。

原页面/导出加入可折叠的“这组玩法的背景与取舍”，与地点直接特色分开。背景可用性不替代逐日覆盖、地域适配或现实可行性。活动删除、改选、撤销/更新资料后重算，旧采用内容及历史导出不重写。domain/OpenAPI DTO 同批更新，SQLite16 不变，无旧数据迁移或预算重置。

范围用途检查 scoped-use-1.1 / advisory-guide-1.6.1 对明确否定关系的受限句型按分句判断：“不能推断每站特色”不是肯定断言。只识别有限的否定谓语和范围对象；转折后重新检查，不因包含“不”就放过整句。原事实检查与逐方案隔离保留，历史 1.6 判定不回写；可经既有 LOCAL_REVALIDATION 页面对原输入/保存回复显式复核。

## 当前输出契约与有界选材（advisory-guide-1.7）

`arrangements.required_citation_ids` 同时供输入提示和本地审核使用：选择一个活动就须列全其 evidence/discovery/knowledge 引用的并集，不是从允许列表任选一个。供应商序列化时增加仅含活动 ID 和必需引用 ID 的 `citation_requirements`；冻结的原 payload 不改写。`suggestions.run_worker` 根据本次实际 payload 生成输出 schema，限定活动、引用、背景和住宿片区 ID。必要引用依赖仍由逐方案语义检查执行，不能从模型缺失引用中自动补签、替换或推断事实。

当前 DeepSeek 配置实际使用 `json_object`，不是服务端 JSON Schema 强制模式。程序把同一个完整 schema 放入受信任系统提示，并在返回后先检查信封，再逐方案检查结构、引用、条件和事实。合法的独立提议仍保留；提示和枚举不能保证未来模型必然合格。协议仍 v4，旧输入、回复、审核、采用与失败不迁移或回写。

`advisory.schema_errors/reference_diagnostic/shape_diagnostic` 仅保存预定义字段路径、错误码、结构和引用数量，不保存错误值、未知字段名或验证器自由消息。`revision_diagnostics.retain` 即使原回复不可安全回放也保留该结构摘要；原回复仍为 null，不把摘要当原文或可回放依据。历史丢失回复不能凭新诊断恢复。

`materials.activities` 在十二项页面上限之前优先考虑具有明确命名动作的已审核体验；这是选材排序，不升级身份、范围、事实或内容标签。自动选材先枚举全部本地候选、保护当前有效锁定项，再执行原十二活动/六来源上限；路线成员关联也不因展示上限漏掉明确成员。没有增加抓取或调用额度。未采信的体验、无证明的住宿片区和未核实的非自驾衔接继续保留缺口。
