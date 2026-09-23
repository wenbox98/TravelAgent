# T04.2 / T05：有预算、可追溯的研究材料循环

本阶段是用户在 T04.1 后新授权的 CLI / 内部 Python 数据通道。默认 Web 演示、sidecar HTTP 路由与 OBSERVE_ONLY 默认值不变；不实现酒店、地图、报价、完整行程或 GUI。执行结果见 [T05 报告](../../reports/T05-xhs-research-loop-smoke.md)。

## 请求和停止边界

`ResearchRequest` 记录出发地、目的地区域、时间提示、研究问题，以及用户已确认的天数和不自驾条件。预算、人数、交通方式可以是 null。它承接现有 TripIntent 的语义，暂不新增公共 HTTP 契约。

`ResearchService.run` 先查 `EvidenceStore`，再评估缺口。证据足够或访问预算为零时，不调用 connect/search/detail。需要访问时，程序在 SQLite 事务中先校验 revision、预留操作额度和去重指纹，随后派发读取。模型只返回结构化材料或候选排序，不能控制浏览器或改变预算。默认每轮上限为 3 次搜索、6 次详情，真实 Smoke 固定 1/2；这些是应用护栏，不代表平台安全阈值。

缺口包括路线/区域、体验、时长、交通；后续搜索附上具体缺口目的并去重。候选按已观测标题相关性、图文类型、来源与近似标题去重，允许在来源策略许可时调用模型排序，失败退回确定性排序。当前实现不把搜索页没有的 summary、travel_time、destination evidence 填给模型。候选推测的关联性是 DERIVED，不是正文 Evidence。

追加“只有 5 天、不想自驾”使用同 research_id 的新 revision，保留已有来源，新增 DAYS_FIT / NON_SELF_DRIVE。T05 只形成材料，不能仅凭正文出现“5 天”“班车”认定整条路线可行；约束适配缺口暂保守保留。旧 revision 的晚到结果不能写回 Evidence、gap 或 run summary。

停止原因沿用有限枚举：EVIDENCE_SUFFICIENT、BUDGET_EXHAUSTED、NEED_LOGIN、VERIFICATION_REQUIRED、NO_USEFUL_CANDIDATES、SOURCE_UNAVAILABLE、ERROR。基本覆盖要求有 locator、受支持的正文摘取、置信度至少 0.5。本地低置信摘取不会误报材料充分。图片依赖缺口随缓存保留。

## 复用的 Evidence 契约

不另造同义 Evidence 表或 claim_type 枚举。结构化模型输出先经过严格 schema，再检查引语确实位于指定 BodyBlock。当前第一版只接受 claim 与短引语一致，暂不接受自由改写；程序生成 source/date/locator，模型不能自造出处。正文块保留原始字符串字符偏移和正文 hash；locator 是 `note-body:v1:<hash>:chars:<start>-<end>`，不是可联网访问的 URL。

| 研究需求字段 | 现有 EvidenceBundle / EvidenceClaim |
|---|---|
| claim / claim_type | claims[].text / topic |
| PLACE、AREA、ROUTE | ROUTE；不能确认时 OTHER |
| ACTIVITY、FOOD、LODGING_AREA | EXPERIENCE 或 OTHER，保留正文原意 |
| TRANSPORT_EXPERIENCE / COST_HINT | TRANSPORT / PRICE |
| CROWD_HINT、WARNING / SEASON_HINT | TRADEOFF / SEASON |
| destination、applicable_conditions | 同名 Bundle 字段；用户约束不能冒充来源适用条件 |
| source_type、source_id、source_title | 同名 Bundle 字段 |
| source_locator | claims[].locator + claims[].source_id |
| published_at / travel_time / retrieved_at | source_published_at / travel_occurred_at / fetched_at |
| content_completeness / confidence | completeness / claims[].confidence |

实际旅行时间始终独立；本阶段无法可靠抽取时 null，绝不复制发布日期。FULL_TEXT / PARTIAL_TEXT / SUMMARY_ONLY / METADATA_ONLY 保留。摘要、标题不能代替正文抽取。小红书摘取默认为 AUTHOR_OPINION，不能伪装 OFFICIAL_FACT。图片保持 IMAGE_NOT_ANALYZED；“见图”等引用产生 IMAGE_INFORMATION_REQUIRED，拒绝以图片内容生成 claim。

`ResearchReport.material_view()` 是内存中的材料视图，列路线/区域、体验、时长和交通线索、来源、缺口、预算和停止原因，标记 EXTRACTED_FROM_SOURCE / OBSERVED / DERIVED / UNKNOWN；不是最终旅行攻略。`safe_summary()` 只用于匿名计数报告，不含实际正文、标题或来源 ID。

## SQLite 和来源用途策略

新增 [v3 迁移](../../contracts/migrations/003_research.sql)，保留 v1/v2 数据。Source 与 Evidence 继续使用现有 sources / claims 和 EvidenceRepository；新增研究问题、run/revision、gap、SourceSnapshot 元数据、run-source 关联、query 去重和操作预留表。真实完整正文不进入数据库，SourceSnapshot 不存正文或访问 URL。

长期保存仍必须通过已有 SourcePolicy：登录/用户授权实验不等于第三方内容长期许可。UNKNOWN 不能持久化 raw、derived、向量或导出；许可资料可以落 SQLite 并跨进程复用，检索时重新检查有效期、当前策略版本和账号范围。

本轮未获核实的真实内容使用显式 `temporary=True`，只允许 `Database(Path(':memory:'))`：证据在 RAM，研究元数据在内存 SQLite，关闭后消失；allow_read 和 allow_inference 仍须为 true，不能覆盖显式 deny。因此本轮真实“缓存 0 访问”指同一进程的临时资料复用，不冒充跨进程持久化成功。授权合成资料的持久化、重启、策略撤回与账号隔离由离线测试验证。

## 模型边界

`LLMProvider.structured(task,payload,schema)` 支持 MockLLMProvider 与 OpenAICompatibleProvider。Mock 只接受合成材料；真实正文没有模型配置时用本地短原文摘取，mode=LOCAL_EXTRACTIVE、confidence≤0.25，不声称调用了模型。模型错误也采用这个保守降级。

配置使用 `TRAVEL_LLM_API_KEY / TRAVEL_LLM_BASE_URL / TRAVEL_LLM_MODEL`（兼容 OPENAI 同名配置）；可选 TRAVEL_LLM_TIMEOUT_SECONDS。只有 SourcePolicy 独立允许 inference / external_model 才能传出材料。兼容 Chat Completions JSON Schema 接口，单次调用、有限响应长度、不跟随重定向、不读取环境代理、不记录 prompt/response/API key。

## TEXT_FIRST 与测量限制

ResourcePolicy 默认 OBSERVE_ONLY。TEXT_FIRST 在 SEARCH/DETAIL 的现有 context 内临时安装一个自有 route handler，仅 abort image/media/font，允许 document/script/stylesheet/xhr/fetch/other；LOGIN 与空闲阶段不安装过滤。退出恢复，错误锁存禁用，不自动重导航。没有 analytics 域名黑名单，不修改 Service Worker、UA、代理或指纹。

详情技术性 BROWSER_ERROR / PARSE_ERROR / UNKNOWN / EMPTY_BODY 才能由 ResearchService 进行一次同来源 OBSERVE_ONLY fallback，而且先消耗详情额度。登录失效、verification、身份不符、访问拒绝、无效 locator、404/410 不允许 fallback。所有访问仍经过原 generation / BrowserSession 校验。

网络表分离 business operations、context request events、route attempts、blocked 和 continued。abort 仍可能产生 request event，不能从 total 减去 blocked 冒充实际网络数。bytes 始终 null / NOT_MEASURED。Playwright routing 会影响 HTTP cache，Service Worker 拦截流量不保证经过 route；这限制了与历史 OBSERVE_ONLY SEARCH≈173 / DETAIL≈181 的可比性，未经相同口径验证不算“节省百分比”。

## CLI 与清理

`.venv/Scripts/python.exe scripts/xhs_research_smoke.py` 默认不访问网络。离线全部门槛通过后，用户明确授权的 `--live` 才运行固定一轮实验；`.local/t05-smoke/summary.json` 在首次 connect 前写入，已有记录拒绝重启重新获得额度。持久账本只有匿名元数据。

第一轮读完正常关闭浏览器并保留 profile，再在同进程对相同请求与新增约束执行 0/0 预算调用。关闭浏览器后验证缓存，避免把后台网页流量漏算成零。任何 NEED_LOGIN / verification / 访问限制停止真实推进。退出不执行 disconnect，也不遗留自有 sidecar。
