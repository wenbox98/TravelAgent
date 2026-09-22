# XHS 旅行研究 PoC 设计｜2026-09-22 审查修订

## T02离线落地范围

用户已接受设计审查并授权T02。当前选择自有Python sidecar，upstream只作固定reference，不复制完整服务再动态禁用能力。`integrations/xhs-sidecar/xhs_sidecar`实现Fake普通浏览器会话及内部只读接口，见[边界/路由](../../integrations/xhs-sidecar/README.md)和[内部OpenAPI](../../contracts/xhs-sidecar.openapi.json)。

已实现start/get_session/close、会话复用/撤销、源头日志允许字段、筛选状态、保守完整度、私有locator、NOT_MEASURED/SIMULATED网络模型。没有真实Chrome启动器、登录Cookie/QR、页面读取；没有TravelResearchService、RAG或预算/早停循环。下文完整PoC流程继续作为后续设计，不因T02测试声称已经实现。当前无live配置开关或真实站点fallback。

T02独立内部契约v0.1.0不冒充T01 FetchResult/Evidence。未观测指标为NOT_MEASURED/null，Fake窗口为SIMULATED；未来COMPLETE/PARTIAL真实覆盖状态需显式扩展契约。T03才引入真实账号scope/generation，当前locator仅绑定Fake BrowserSession，TTL仍UNKNOWN。

以下保留设计审查的整体目标，源码基线为 `8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff`。事实依据见[上游分析](xhs-poc-analysis.md)，实际T02状态以上述范围和[T02报告](../../reports/T02-implementation.md)为准。

**整体目标为 wrapper + 自有只读sidecar + 普通浏览器。** 审查时的upstream patch方案在T02改为独立实现，内部控制要求仍有效。原upstream默认CloakBrowser指纹路径不满足约束，WithStealthJS(false)也未关闭该能力。禁止验证码绕过、指纹伪装、stealth、代理池和IP/账号轮换；遇验证、明确限流或拒绝访问停止。

## 验证目标
输入“国庆从成都去川西玩”，系统在条件不完整时先研究大方向；用户随后说“只有5天，而且不想自驾”，系统复用第一次资料，只补新增 Evidence Gap。

## 第一阶段形态
先做 CLI，不以 Electron 为前置。建议组件：

```text
CLI
 └─ TravelResearchService
     ├─ SourcePolicy + EvidenceStore(许可范围内的 SQLite / 内存)
     ├─ GapPlanner
     ├─ QueryPlanner
     ├─ CandidateSelector
     ├─ EvidenceExtractor
     ├─ BudgetLedger
     └─ XhsReadonlyAdapter
           ├─ SessionManager(本地状态 / account_scope / generation)
           └─ patched local sidecar / 普通浏览器专用会话
```

LLM 经 `LLMProvider` 抽象，至少提供 `MockLLMProvider`；真实模型通过 OpenAI-compatible adapter 读取 `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`，密钥不进仓库。

## 核心循环
1. 规范化当前 `research_question` 与已确认约束，未知保持 UNKNOWN。
2. 查询仍允许复用、账号范围和条件匹配的 SQLite/内存 Evidence；此时不启动 sidecar/browser，不调用登录 status。
3. 计算 `missing_slots/evidence_gaps`。若已足够，本次研究不派发外部读取；测量窗口HTTP为0还需排除活动QR/浏览器后台流量并有完整观测。
4. 先复用候选和有效内存locator；仍缺信息才生成少量 query，经来源许可、预算预留和账号串行通道，按需 EnsureSession 后读取候选。
5. CandidateSelector 根据相关性、地点、路线/时长信息潜力、增量、重复度和缺口选择下一篇。
6. 每次只选择一篇详情，合并同source在途需求；读取后提取 Evidence，更新覆盖，足够立即停止。不批量预取Top-10。
7. 达到 3 搜索/6 详情上限仍不足，返回 `insufficient_evidence=true`。

## Evidence 最低字段
`claim, claim_type, destination, applicable_conditions, source_type, source_id, source_title, source_locator, published_at, travel_time, retrieved_at, content_completeness, confidence`。

`content_completeness` 仅允许：`FULL_TEXT / PARTIAL_TEXT / SUMMARY_ONLY / METADATA_ONLY`。摘要、标题不能被输出成“阅读全文”。detail返回成功或desc非空也不直接证明全文完整；缺失/截断/未知时保守降级并记录原因。FULL_TEXT限定已验证正文文本范围，不表示图片文字/视频全部已读，未读图片中的关键条件仍是缺口。正文和图片来源分别定位。

### T01 契约映射

上述最低字段是概念名称，实际 API 使用 `EvidenceBundle` + `EvidenceClaim`：`claim→claims[].text`、`claim_type→claims[].kind`、`source_locator→claims[].locator`、`published_at→source_published_at`、`travel_time→travel_occurred_at`、`retrieved_at→fetched_at`、`content_completeness→completeness`、`confidence→claims[].confidence`。`source_type/source_title/destination/applicable_conditions` 在 bundle 上。未知置信度为 null；不把模型自评分当完成条件。元信息不得生成正文结论。

统计概念 `research_id→research_session_id`、`search_operations→search_ops`、`detail_operations→detail_ops`；报告序列化时显式映射。`stop_reason/insufficient_evidence` 和候选筛选审计仍由 T04 增加严格契约与测试，T01 未实现研究循环，不能宣称 XPOC 场景通过。

首轮 3/6、补查 2/4、会话累计 5/10，均取自 defaults；第二轮复用 Evidence，不自动重置会话。SQLite v1 通过显式 v2 迁移升级，保留既有旅行与预算记录。

## 登录状态
`DISCONNECTED → CONNECTING → QR_READY/WAITING_CONFIRMATION → VERIFYING → CONNECTED`；任何步骤可进入 `ACTION_REQUIRED/EXPIRED/ERROR/CANCELED`，断开经 `DISCONNECTING → DISCONNECTED`。状态查询走本地缓存。CONNECTED表示某时点已验证，不保证后续每次可访问。过期时保留预算、revision和政策允许保留的Evidence；纯内存内容进程退出后可能丢失，不能承诺全部恢复。

## 访问预算与并发
- `max_search_operations=3`、`max_feed_details=6`：PoC 应用护栏，不是平台阈值。
- 同一账号 XHS 外部读取串行。分析已取得资料可并行。
- 同 source 的并发需求合并；同run最多一次详情派发，失败也计入，PoC默认不自动重发详情。
- challenge/verification/明确限流/拒绝访问后停止，不换账号/IP继续。

## revision
每次研究带 `research_id + revision`。晚到结果仅能写入自己的 revision；如果当前计划已更新，旧结果标 obsolete，不覆盖新状态。

## 观测
每次报告至少输出：`research_id, revision, search_operations, detail_operations, cache_hits, cache_misses, candidate_count, selected_candidate_count, evidence_count, insufficient_evidence, stop_reason`，并按下文单独统计auth/导航/网络覆盖。Cookie/token/xsec_token/二维码和敏感 URL 不进日志、错误详情、数据库或模型。

## 必过测试
1. 缓存足够 → search=0/detail=0/auth=0/browser_starts=0；离线禁止外网，不触发会话恢复。
2. 首次研究不超过 3/6。
3. 前几篇已足够 → 提前停止。
4. 同 source 重复候选/并发/失败 → 默认最多一次详情派发，不隐式重试。
5. 第二轮“不自驾” → 保留旧 Evidence，只补缺口。
6. 登录失效 → NEED_LOGIN，无无限重试，任务不丢。
7. verification required → 停止，不绕过。
8. SUMMARY_ONLY → 不声称全文。
9. 旧 revision 晚返回 → 不覆盖新 revision。
10. 预算耗尽 → insufficient_evidence，不继续访问。

## Smoke test
真实测试仅在普通浏览器、只读边界、取消/脱敏及离线契约验收通过，且用户本机明确开启 live 模式后进行。输入“国庆从成都去川西玩”，严格遵守预算，并在 `reports/xhs-poc-smoke-test.md` 记录实际搜索/详情次数、导航/网络覆盖、Evidence 数量、正文/摘要完整度、登录或验证问题、失败点和下一步；禁止记录登录材料、账号截图和真实原文数据集。不为测基线额外抓取真实Top-10，也不主动触发风控采集失败样本。

## 必需 sidecar 内部控制与 wrapper 边界

| 工作 | 设计要求 |
|---|---|
| 浏览器工厂 | 替换默认内置浏览器、下载入口及seed初始化；普通受支持浏览器，应用专用存储；不导入指纹/stealth/humanize模块，不接管用户日常profile |
| 所有权和取消 | 明确进程/page所有者，管理启动、借页、关闭、登录waiter及读取任务；建页失败、panic/error与退出均清理 |
| 只读工具面 | 仅health、受控登录、POST search/detail；不初始化/注册MCP、写工具及其他非PoC路由；不开放任意URL/CDP |
| 本机隔离 | loopback、强制非空随机Bearer；凭证走受保护环境/内部通道，不经URL/命令行；限制Host/Origin，空token拒绝启动 |
| 源头脱敏 | 删除detail完整URL日志；访问日志、handler错误、recovery只输出允许字段；wrapper事后清洗不构成验收 |
| 可验证读取 | 提供筛选状态、已观察访问错误、字段存在性/完整度线索和source ID，wrapper不能凭空恢复这些事实 |
| 成本控制 | 导航/网络观测；裁剪隐式导航重试；受控错误和单一预算所有者，不叠加SDK/worker自动重试 |

浏览器供应、平台支持、完整性校验与自有路径在T02实际核对后锁定。当前不选未经验证的安装包、不填假hash、不运行upstream自动CDN下载。health本身不得触发浏览器安装/页面访问。原REST wrapper只能做参数校验、映射、隔离与调度，不能替代上表内部改造。

## 登录生命周期细化

1. 以 `session_id + generation` 在创建browser/page之前原子检查已有登录。重复连接返回当前有效会话与二维码，不重调upstream qrcode。UI/CLI GET/SSE只读本地快照，禁止周期性远端探活。
2. 普通浏览器加载官方登录页，复用DOM读取片段。img是页面src，由可信边界核实形式并仅在本地登录UI展示；异常形式退回可见官方页面，不提供任意URL代理下载。二维码只保留内存。
3. timeout解析Go duration（当前4m0s/0s）并转换本应用expires_at，不当作平台二维码TTL。等待观察当前DOM，页面自身后台网络也计数。
4. 优先在同一已加载页确认登录/账号，提交会话快照后发结构化事件；不为成功回调再导航一次。确需远端核实时最多一次，网络不确定时至多一次单独计费的恢复核实，不能循环调用status。
5. Cookie提交在同一同步边界核对有效generation，采用原子替换和用户专用存储权限；文件存在、saved_at、mtime、seed写入均不证明登录成功。
6. 登录完成关闭登录页；可以保留自有普通浏览器进程供当前活动研究借页，空闲关闭。此为新实现，非upstream已有能力；少启动进程不等于已测得HTTP减少，留驻后台流量要观测。
7. 重启恢复受控登录材料，旧CONNECTED标待核实，仅实际读取需要时确认。刷新Cookie及持久化时点由SessionManager管理，不能假定upstream search会保存更新后的Cookie。

账号采用本地匿名account_scope。is_logged_in=true但user_id缺失时，只建临时隔离范围，不凭昵称/布尔值合并历史账号缓存。确认同一账号后，仍须来源政策许可才复用持久Evidence。作者ID用于独立性判断时也在受控边界匿名化。

官方要求人工验证时进入ACTION_REQUIRED并暂停研究。REST没有无头页切换可见窗口的接口；如无法延续上下文，先取消、等待旧上下文结束，再开启明确的新官方流程。用户无需复制Cookie、提供密码/SMS验证码或日常profile路径。

### 断开顺序与竞态

1. 原子关闭新任务入口，立即使旧generation失效，拒绝旧Cookie/状态提交。
2. 取消登录与读取，等待page/browser清理；超时仅终止PID+启动时间/进程树已确认归属本应用的进程。
3. 确认没有写入者后，删除自有会话材料、内存token/二维码，标记DISCONNECTED。
4. 保留已消耗账本、缺口及政策允许保留的结果；不能用重新连接清空预算。

DELETE cookies不等于该流程。revision防旧计划覆盖，generation防撤销登录复活，两者不能混用。晚到结果也不退回已发生的访问额度。

## 适配协议与定位能力

仅允许 [03](../03-xhs-access-login.md) 的路径白名单；登录路径只由SessionManager调用，模型只接触本应用业务工具。

| 操作 | upstream协议 | 应用处理 |
|---|---|---|
| Search | POST `{keyword,filters:{...}}`；`data.feeds/data.count` | 单对象filters，拒绝未知字段、cursor/page_size/start_date；count仅本批数量 |
| Detail | POST `{feed_id,xsec_token,load_all_comments:false}`；`data.data.note` | 固定false、不传comment_config；核对note.noteId；剥离comments/token/签名资源 |
| Login | status布尔与可选账号；qrcode duration字符串 | 转本地事件；upstream401是sidecar鉴权失败，不能当小红书NEED_LOGIN |

成功/错误封装也不同于本应用FetchResult，必须显式解包。上述是内部协议，不是供模型提交的参数。Go struct把缺失压成零值时，sidecar要补提取元信息；wrapper不自动填日期、作者或正文。

- source identity为provider+note ID；账号/用途/政策另外限定缓存范围，无可靠ID的候选保持不可读，不猜token。
- 内部随机handle指向内存 `{note_id,xsec_token,account_scope,generation,observed_at}`；映射值及token不进入数据库/RAG/模型/分享，模型最多取得不含凭证的handle。token真实TTL未知，应用可采用更短保留期限。
- URL只能由合法ID与正确编码token在sidecar构造；xsec_source=pc_feed不是source_id，不允许失败后轮换该参数。
- 脱敏链接只标识来源，不保证无登录/token能打开；正文定位使用允许的段落/图片索引，避开敏感URL。
- locator丢失不影响合法Evidence引用；确需再次读原文才占显式搜索预算重新定位。未知失败不自动归因token过期，认证失败先暂停。

## 搜索结果与完整度约束

首轮目标仍是综合/图文；默认状态要验证，不因“默认综合/不限”重复点击所有筛选。只发送对缺口必要的非默认筛选；图文状态未确认时依据noteCard.type本地保守排除视频，不把视频时长当旅行天数。

publish_time只有不限/一天内/一周内/半年内；location只是同城/附近等距离。目的地与旅行季节通过query/证据判定，不虚构API参数。

sidecar需给出requested_filters与filter_outcome（概念字段，待契约变更）；点击完成、ID改变都不足以证明所有筛选完成，超时标UNKNOWN/失败。未知结果不能写成“符合目标filters”的缓存，也不补发无预算搜索。

候选默认没有摘要、发布日期、旅行时间；只有标题、ID、类型、作者、热度、封面和可选视频信息。标题含天数/地点只供预期增益排序，不能直接生成证实结论。缺日期保持temporal_unknown，不自动淘汰或标最新；缺作者则独立性UNKNOWN。字段不足时降低可判断程度，不预读全部正文来填评分表。

detail.time需核对单位与范围后映射发布时间；旅行发生时间从明确内容取得，未知null。图片/视频/字幕URL可能带签名，不能直接进入持久化/模型；必要图片补读遵守政策和预算，网络/Vision分计，不下载视频/字幕或全图集。未读图像承载的关键事实继续列为缺口。

至少两个独立来源簇只能支持粗略经验建议；开放、预约、价格、道路安全等硬事实仍需权威核验。查不到标待确认，不能让多篇转述代替独立来源。

SQLite只存来源政策允许的数据；登录同意、TTL都不是内容存储/推理许可。权利未知默认不持久化/外发未经许可的原文或衍生数据，内存处理也服从政策。崩溃/退出后纯内存证据可能丢失，恢复时重新计算缺口，不保证第二轮/重启一定零访问。

## 预算与去重的精确定义

首轮3/6、补查2/4、累计5/10继续取自 [defaults](../../config/defaults.json)；图像补读首轮/补查各≤2、累计≤4，主动评论展开0。revision、job、重连、消息变化均不重置累计账本。不能由模型拆任务或追加额度。

先校验/去重，再原子预留permit，最后派发。派发后的失败、超时、取消均计费；只有证明确未发生上游访问的预留可释放。结果未知要保留派发记录，重启不得变成“未读”。

本文run指同一次研究会话（research_session_id），跨消息、job、revision、重连保持不变，不能通过新建worker/job重置去重记录。详情去重键至少为账号隔离范围+research_session_id+source_id；成功、在途、已派发失败都参与。

PoC默认禁止自动重发详情，比 [04](../04-research-efficiency.md) 的一般网络重试上限更严格。以后用户明确批准的单次恢复须标为额外访问、消费剩余额度并留审计，不能仍算“同source只读一次”的样本；验证/拒绝访问不靠恢复重试绕过。

query键采用account_scope、normalized_query、filters、purpose、temporal_scope、policy_version；只有筛选状态已确认且仍适用的结果能满足该缓存。明确不可见可短期负缓存，认证失败不能缓存为笔记不存在。适用且允许保存的旧revision结果可待新revision显式选择复用，不覆盖新计划。

无新信息触发重新评估或PARTIAL，不等于缺口解决；取消保持取消，认证/验证保持暂停，不能用HTTP成功代替研究完成。预算、权限和早停由确定性代码控制，外部正文不是工具调用指令。

## 新增观测口径（待契约同步）

| 指标 | 口径 |
|---|---|
| search_ops/detail_ops | 已派发业务调用，含失败，不能代替HTTP量 |
| auth_probes/login_starts | 触达平台的身份核实/官方登录启动，本地状态轮询不计 |
| browser_starts/page_navigations | 进程启动/实际导航尝试，含失败，两者分开 |
| filter_actions | 实际筛选操作，产生多少请求由观测确定，不假定一对一 |
| site_http_requests | 可观察到的站点/资源请求，声明域名分类、时间窗口、子页/worker/后台覆盖；缺测null |
| network_measurement | COMPLETE/PARTIAL/UNAVAILABLE概念状态；覆盖不全不能填0或推算总数 |
| image_fetches/model_calls | 图片网络读取/模型调用分计；浏览器自动媒体计入资源流量 |
| unique_notes_read/duplicate_fetches_avoided | 成功取得正文的去重来源/派发前避免的重复详情 |

以上维度不可相加为HTTP总数。DOM轮询/Eval重读也不冒充网络。网络事件只存分类与计数，不记录敏感完整URL/请求头/正文，不为降计数阻断平台安全组件。

通用500/超时不证明NEED_LOGIN、封号或token过期；访问错误必须来自可观测证据。认证、verification、明确限流/拒绝访问暂停账号；网络、解析、内容不可见、sidecar鉴权分别处理，未知保留受限原因，不盲重试。

stop_reason、insufficient_evidence、筛选结果、事件、附加错误/指标等需在后续任务显式同步严格契约、实现和测试。本轮没有暗中扩展schema。现有应用状态/错误枚举不因设计中的概念名称而自动改变。

## 补充离线验收设计（本轮未执行）

1. 本地状态高频查询、重复连接、过期、取消再连接：只有当前generation一次有效启动和提交，无额外status导航。
2. 注销后晚到扫码、建页失败、进程关闭：不复活状态或Cookie，清理仅触及自有资源。
3. 普通浏览器依赖/启动参数无指纹、stealth、humanize；MCP/写路由未注册，Host/Origin/凭证严格验证，health不下载浏览器。
4. 合成REST响应覆盖duration、双层data、缺字段、ID不符、同ID新token、混合图文视频、无日期/摘要；token不进入模型和持久化。
5. 筛选超时、部分完成、相同ID结果不能冒充筛选成功或污染缓存，不能隐式再搜索。
6. 正常/异常/panic路径日志与响应均不泄漏Cookie、token、二维码、签名URL或原文。
7. 成功/失败/在途/重启均遵守预算和一次详情派发；旧revision不覆盖新结果。
8. FULL_TEXT需证明文本范围，图片未读缺口保留；来源政策禁止复用时不为命中率绕过。
9. 模拟QR后台/筛选/媒体流量，证明search=0仍可能有HTTP；缺测为null，不能误报0。
10. 固定合成池对照评测，在相同质量下比较逻辑操作节省，来源支持逐条审查，不由生成模型自评满分。

这些是待实现行为测试，不能记为当前PASS。文档/schema检查不替代应用或实机验收；真实节省率未测得，30%仍仅为离线目标。

## 下一阶段与停止边界

确认本审查后，建议只做T02普通浏览器与只读sidecar离线最小改造，显式同步上游锁、必需patch和契约，然后依次T03登录生命周期、T04研究循环。未满足门禁时实机测试保持SKIPPED/BLOCKED，不用mock代替。

**T02离线基础完成提交后停止，等待用户确认，不自行进入T03或真实站点工作。**
