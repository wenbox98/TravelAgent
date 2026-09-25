# TravelAgent｜私人本地旅行研究助手
## Codex 设计、开发与测试文档包 v1.1（小红书研究 PoC 强化版）

**编制日期：2026-09-22。交付状态：开发规格，不是已经开发完成的应用。**

目标：用户给出模糊旅行需求后，工具自动研究小红书等来源，先提供几个大致路线和停留时间，再通过带建议的对话确定交通、项目、住宿和预算。研究成果在权限允许的范围内进入个人资料库；修改选择后进行局部重算。

目标仓库是 `wenbox98/TravelAgent`，与 `devagent-lab` 学习仓库独立。项目许可证尚未确定，不在本次文档导入中代选。此压缩包是待导入材料，不表示已经写入远端仓库。

## 当前定位：私人本地研究

T06.2 已完成安全错误分型、正文先保存和仅模型恢复入口。合成真实提取通过；有界真实复验在第一篇 grounding 拒绝后停止，**G1 仍 FAIL**。这次已保存正文并通过独立进程恢复，不再因模型失败丢失原文。详见 [T06.2 报告](reports/T06.2-llm-diagnostics-and-recovery.md) 和 [恢复契约](docs/architecture/t062-extraction-recovery.md)。真实账本不允许自动重跑；后续从本地已保存来源排查，不重新搜索。下方 T06.1 结果和入口是历史记录。

当前仅供当前用户本人私人使用，暂不考虑公开发布和多用户产品。默认数据模式为 `PRIVATE_LOCAL_RESEARCH`，正文保留默认 `PERSISTENT`；后续保留选择支持 `7_DAYS / 30_DAYS / PERSISTENT / EPHEMERAL`。

只缓存实际精读用于旅行研究的少量正文、规范文本、正文块与 Evidence，以减少下一次重复访问。搜索候选不自动缓存全文；不长期保存原始图片。研究数据仅在本机 SQLite，不建公共数据集、不跨用户共享、不上传自有服务端、不提交 Git。配置的外部模型只处理必要正文块，认证材料始终隔离在浏览器会话中。

私人用途模式不代表作者授权、平台授权或合规认证；权利依据仍记录 UNKNOWN。明确的本次用户用途决策覆盖旧的 UNKNOWN 一律禁止本地保存规则，但不取消只读、预算和验证暂停要求。设计与迁移见 [私人研究数据策略](docs/architecture/t06-private-local-research.md)。下方早期发布计划及阶段结果作为历史记录保留。

真实验收入口为 `scripts/private_research_smoke.py --live`，上限 1 次搜索、3 篇详情、OBSERVE_ONLY。正常关闭保留 profile 与 `.local/t06.1-private/research.sqlite3`；清研究缓存使用既有 `research_quality.py clear-cache`，不会 disconnect 或清理登录 profile。独立进程恢复验证使用 `tools/private_cache_probe.py`，禁止网络访问。模型已验证可用，不重跑合成连通性请求。

用户明确批准本次必要正文发送 DeepSeek 后，真实验收已完成一次搜索和一篇详情：登录复用、搜索和正文读取成功，首次模型抽取降级并触发停止，**G1 FAIL**，G0 保持此前 PASS。独立入口路径问题已修复；模型失败缺乏分型诊断，以及失败时正文尚未落库，是后续修复点。详见 [本轮验收记录](reports/T06.1-g1-live-validation.md)；[旅行研究示例文件](reports/T06.1-live-travel-research-example.md) 如实说明暂无合格 Evidence，没有虚构真实路线。

已确认的下一步架构方向是 Raw Source → Evidence → KnowledgeCard → Knowledge RAG，未来推荐原文 SESSION 保留，卡片成功落库且 grounding 完成后才允许清理原文。KnowledgeCard、SESSION 及“清原文缓存/清旅行知识”拆分目前只是设计待办，当前实现仍用 PERSISTENT；不因这项设计变更删除现有研究库。详见上方私人研究数据策略。

## 现在怎么交给 Codex

1. 将此包导入 `wenbox98/TravelAgent` 根目录。导入前先检查远端和本地内容，不覆盖已有文件；成功导入后，在 Codex 中选择该仓库即可读取文档，无需再下载聊天附件。
2. 在 Codex 中打开该目录，把 [CODEX_START.md](CODEX_START.md) 的启动指令整段发给它。
3. 首次完成 T00、T01 后逐个执行任务，不要求一次生成全部系统。每个任务的产物和验收见 [任务总表](docs/12-task-plan.md)。
4. 原包历史上只执行过文档校验；T00/T01 离线实现见 [T00 报告](reports/T00-implementation.md)、[T01 报告](reports/T01-implementation.md)。后续本机登录专项已由 [T03.8 报告](reports/T03.8-implementation.md) 验收；真实读取、访问成本和 Windows 发行安装不能据此视为通过，T04 当前状态见下文。

没有真实账号、Windows 或 API 凭证时，Codex 应完成离线可验证部分，准确记录阻塞项，不得把 mock 结果写成实测。

## 首版边界

**首版 v0.1：Windows x64 本地单用户；支持本地正常登录小红书、有限自动研究、粗略攻略、多轮选择、个人资料复用、明确标记状态的预算，以及高德地图接入。**

发布包的体验目标是解压/安装后启动应用，点“连接小红书”，在官方页面或官方生成的二维码完成登录。不要求普通用户安装 Docker、Python、Go，或复制 Cookie。开发者构建可以使用开发工具。

首版不做云端托管多人账号、不承诺纯手机独立运行、不做无人值守验证码处理、不做账号/IP 轮换、不自动下单。真实票价必须有可用供应商才能显示为报价；未接通时标记未知，不构造“演示价”。

## 阅读导航

| 文档 | 解决什么问题 |
|---|---|
| [01 产品需求](docs/01-product.md) | 做成什么样、首轮怎么回答、哪些不做 |
| [02 总体架构](docs/02-architecture.md) | 模块边界、目录、进程和数据流 |
| [03 小红书接入与登录](docs/03-xhs-access-login.md) | 低操作成本登录、上游核实、只读适配、异常恢复 |
| [04 准确性与请求预算](docs/04-research-efficiency.md) | 先筛后读、去重、缺口搜索、计数与熔断 |
| [05 数据与 RAG](docs/05-data-rag.md) | 保存什么、权限、检索、时效与删除 |
| [06 Agent 与规划引擎](docs/06-agent-planning.md) | 多轮状态、修改、时间与预算计算 |
| [07 接口与领域契约](docs/07-api-contracts.md) | HTTP、事件、错误、并发和版本规则 |
| [08 页面与交互](docs/08-ui-ux.md) | 登录页、粗略攻略、取舍预览、资料库 |
| [09 安全与开源边界](docs/09-security-open-source.md) | 凭证、来源指令注入、数据用途、发布边界 |
| [10 测试设计](docs/10-test-strategy.md) | 离线、集成、人工实测、度量与门禁 |
| [11 开发部署运行手册](docs/11-dev-deploy.md) | 命令、配置、桌面打包、排错 |
| [12 开发任务总表](docs/12-task-plan.md) | 任务顺序和 Codex 每次改什么 |
| [13 设计质询](docs/13-design-review.md) | 十二项反例检查与调整 |
| [14 来源与事实状态](docs/14-sources.md) | 哪些已读源码、哪些待验证 |
| [15 发布验收](docs/15-release-acceptance.md) | 什么程度才能说“可用” |
| [16 小红书筛选实施细则](docs/16-xhs-screening-spec.md) | 未知值、正文验证、停止语义及筛选审计 |

`contracts/` 是机器可读的领域/API/数据库草案；`fixtures/` 全部是合成测试数据；`prompts/` 为 Agent 提示词规范；`docs/tasks/` 是具体施工单；`tools/validate_pack.py` 可校验本包；`00-阅读导航.html` 是目录导航，完整内容以 Markdown 与契约源文件为准。

## 三类文字的意义

- **用户要求/设计决策**：本项目应实现的行为，并非外部平台承诺。
- **源码或官方文档已核实**：带来源编号；仅证明所观察到的版本或文档内容，不等于线上成功。
- **待实测/设计目标**：必须用真实报告验证，不能当成已达到的指标。

所有测试中的地点代号、时间、票价、笔记和账号标识均为合成示例；“国庆成都去川西”只是需求输入样例，不包含真实旅行建议。

## v1.0.1 变更

补充第 16 章与 T04 的筛选验收，修正“连续两篇没有新信息”不等于研究完成的语义；加入 Git 忽略规则与文本换行规则。原 76 项应用测试继续保持 NOT_RUN；新增 SEL01～SEL12 为待实现测试设计。外部事实沿用原包来源记录，本次整理未重新运行真实平台验证。


## v1.1 变更

本版不推翻原产品设计，重点把“小红书攻略获取”收敛成可实施、可验收的 PoC：

- 首次连接通过本地正常网页会话完成，不要求普通用户复制 Cookie、开 DevTools 或配置 profile；会话失效时保留研究任务，重新连接后续跑。
- 不通过验证码破解、代理/IP/账号轮换、stealth/anti-detect 等方式规避平台安全机制；优化目标是**提高命中率与资料复用率，从源头减少无意义访问**。
- 研究改为 Evidence Gap 驱动：先查个人资料库，再少量搜索候选，先筛后读，逐篇更新缺口，证据足够即停止。
- PoC 默认护栏调整为每轮最多 3 次搜索、6 篇详情；它是应用成本上限，不是平台安全阈值。
- 统一正文完整度为 `FULL_TEXT / PARTIAL_TEXT / SUMMARY_ONLY / METADATA_ONLY`，避免标题或摘要被误报成“已阅读全文”。
- 新增 [XHS PoC 上游分析](docs/architecture/xhs-poc-analysis.md) 与 [XHS PoC 设计](docs/architecture/xhs-poc-design.md)。
- 第一阶段以 CLI 验证登录→搜索→筛选→精读→Evidence→SQLite 复用→增量补搜；Electron/完整工作台继续保留在后续阶段。
- 新增 XPOC01～XPOC10 验收设计：缓存 0 请求、预算上限、提前停止、去重、增量补搜、登录失效、验证暂停、摘要边界、revision 防覆盖、预算耗尽。

**上述 v1.1 变更说明是历史开发规格，不能单独作为实测证据；后续各阶段的真实状态以对应报告为准。**

## T02只读sidecar离线基础

T02 增加独立[只读 sidecar 基础](integrations/xhs-sidecar/README.md)：Fake 普通浏览器会话、路由白名单、源头日志脱敏、筛选/完整度/来源定位/网络模型。历史验证见 [T02 报告](reports/T02-implementation.md)，来源见 [provenance](docs/architecture/xhs-upstream-provenance.md)。没有复制或运行完整 upstream。

## T03 登录生命周期

在 T02 基础上新增标准 Playwright 普通 Chrome/Chromium、系统应用数据目录中的 TravelAgent 专用 profile，以及本地登录状态机。默认仍为 offline Fake；显式 login 模式启动服务也不打开浏览器，只有 connect 才启动可见官方窗口并导航一次。用户在官方窗口正常登录，无 Cookie 复制或二维码提取；等待复用同页，不反复刷新。

`GET /v1/login/status` 只读本地快照；profile 存在只标 SESSION_PRESENT_UNVERIFIED。generation 拒绝取消/断开后的晚到结果；cancel 和关闭保留 profile，disconnect 关闭后清理。验证要求暂停，手工处理后显式 resume 同页继续。login 模式拒绝 search/detail 和旧浏览器 POST 入口。

命令、launch 参数与 profile 边界见 [sidecar README](integrations/xhs-sidecar/README.md)。初次离线交付见 [T03 实现报告](reports/T03-implementation.md)；后续经用户授权完成登录识别修复、200 项离线测试及本机真实登录/重启复用/断开清理，执行证据见 [T03.8 验收报告](reports/T03.8-implementation.md)。**T03 登录专项已通过，最终提交为 `ccd329056794d3f29549ff0383f6236ce6373f36`。** 当时停止于 T03；本轮经用户新授权进入下面的 T04，G0 整体仍未通过。

## 历史 T04 首次读取 Smoke（PARTIAL）

T04 仅增加独立人工 CLI `.venv/Scripts/python.exe scripts/xhs_read_smoke.py --live`。启动不打开浏览器，输入 `connect` 后才用 T03 相同的普通 Chromium、专用 profile 和同一个 BrowserSession 正常登录。命令为 `connect/status/search/detail 0/detail 1/snapshot/quit`；`quit` 正常关闭并保留 profile。

一次固定搜索 `成都 川西 国庆 攻略`，最多两篇确定性选择的图文详情；第一篇足够技术验证时不读第二篇。不自动换词、翻页、滚动、展开评论、分析图片、下载视频或执行平台写操作，不实现完整研究服务、RAG 或最终攻略。预算在读取派发前记录，已有非零读取记录时拒绝通过重启重置预算。

输出和 Git 忽略目录中的 `.local/t04-smoke/summary.json` 仅保存匿名字段存在性、数量、完整度与网络统计。网络 scope 为 `context_events_since_attach`，保留窗口外流量和晚到响应，未知字节数为 null；业务 search/detail 次数与真实请求数分列。现有 sidecar HTTP 契约仍是 0.3.0 的 offline/login，`live_smoke` 仅是内部摘要类型。边界和命令见 [sidecar README](integrations/xhs-sidecar/README.md)，结果见 [T04 Smoke 报告](reports/T04-xhs-read-smoke-test.md)。

本次同一 BrowserSession 正常登录为 AUTHENTICATED，1 次上述搜索得到 20 个去重候选，搜索技术验证 PASS。1 次详情已消耗预算，但返回 UNEXPECTED_PAGE，未解析出正文；用户确认浏览器显示正常图文页，不能据此把自动 detail 判为成功。详情验证 FAIL，总体 PARTIAL；路由别名校验不一致仅完成离线修复，实际失败原因未确证，未进行真实复测。CLI 已正常退出并保留 profile。

搜索窗口观测 173 个 context 请求，详情失败前窗口为 86 个（不代表完整详情成本），TOTAL 为 725 个、主 frame 导航请求 5 个；字节数未测。默认评论相关请求有 1 个，分类为 DERIVED，不代表主动展开评论。G0 仍未通过，本轮停止，不进入 T05。

## T04.1 详情补验（有限技术 Smoke 通过）

[T04.1 报告](reports/T04.1-xhs-detail-smoke-test.md) 记录 423 项离线测试及真实补验：复用 profile，无需重新登录，使用 1 个 BrowserSession；旧 locator 仅在内存，因此使用另行授权的 1 次 fallback 搜索取得 20 个候选，再读取上一轮未访问的备用候选，本轮 detail 仅 1 次。入口为 `scripts/xhs_read_smoke.py --live --detail-smoke`，使用独立 `.local/t04.1-smoke/summary.json` 账本，未重置历史 T04 额度。

该详情 IDENTITY_MATCH、主响应 200，取得正文 672 字符、22 个非空行（计数 DERIVED），完整度 PARTIAL_TEXT：DOM 不完全一致，展开/截断状态未知；5 张图片未做 OCR。详情窗口 3.150135 秒观测 181 个请求，TOTAL 587，字节数未测；正常 quit 保留 profile，自有浏览器剩余 0。历史失败根因仅 LIKELY 与路由别名有关，原失败分支仍 UNKNOWN，不能确证。

T04 有限技术 Smoke 可以结束；这不自动通过 G0 完整发布门禁，也不进入 T05。下一步建议另行授权 T04.2 基线请求优化，当前未实施请求阻断。

## T04.2 / T05 新授权阶段

在 T04.1 基线后增加阶段限定的 TEXT_FIRST、BodyBlock 证据摘取、SQLite 研究元数据、缓存优先的有预算 ResearchService 与增量缺口。默认仍 OBSERVE_ONLY；真实入口为 `scripts/xhs_research_smoke.py --live`，上限固定 1 次搜索、2 次详情，只生成研究材料，不生成完整行程。

详见 [实现设计与来源用途边界](docs/architecture/t05-research-loop.md) 和 [T05 执行报告](reports/T05-xhs-research-loop-smoke.md)。UNKNOWN 来源内容只在内存临时研究；没有模型配置时明确使用本地保守摘取，不冒充模型抽取或持久化缓存。历史阶段的停止要求不代表本次新授权阶段已经通过，实际状态以报告为准。

T05 最终离线测试 581 PASS；真实 1 次 search、2 次 detail 取得 6 条低置信 PARTIAL_TEXT 证据，缓存和 5 天/不自驾增量复用均 0 访问。TEXT_FIRST 阻止 224 次图片加载，请求事件 SEARCH 236、DETAIL 276/285 包含被阻断的尝试，不能代表实际出网数量。它尚未证明减少实际网络成本，默认继续 OBSERVE_ONLY。G0 本机受控只读数据通道通过，G1 研究质量未通过；T05 真实 Evidence 只在内存，profile 保留，自有浏览器/sidecar 均已关闭。

## T06 研究质量与持久缓存

新增 SQLite v4 研究约束、证据质量与报告元数据；缓存判断在登录前，跨进程复用和清除研究缓存均有离线验收。正文先 canonicalize，再做有块定位的严格抽取，按来源/条件去重、时效、冲突与 Q1–Q4 coverage 形成可追溯的候选方向。只处理研究材料，不生成最终详细行程。

T06 交付时没有真实 LLM 配置，当时为 **G1_LIVE_LLM_BLOCKED，G1 未通过**。后续 T06.1 已通过合成正文的真实模型检查，见 [模型接入阶段报告](reports/T06.1-g1-live-llm-validation.md)。当时的来源策略门槛已由用户明确的私人用途决策更新；当前真实验收状态见上方本轮记录。合成 benchmark 与示例是离线验收，不是真实川西攻略。用法和数据边界见 [T06 设计](docs/architecture/t06-research-quality.md)，历史结果见 [T06 报告](reports/T06-g1-research-quality.md)；G0 保留此前 PASS。

## 真实模型配置（T06.1）

沿用 `OpenAICompatibleProvider`，使用 OpenAI 兼容的 Chat Completions 接口。默认使用 `json_schema`，也支持显式选择 `json_object`；两种模式都保留严格的本地 schema 和正文定位校验。模型配置只从进程环境变量读取；[.env.example](.env.example) 仅为名称与默认值参考，程序不会自动加载 `.env`，复制文件不会使配置生效。

| 环境变量 | 在本机填写的内容 |
|---|---|
| `LLM_BASE_URL` | 服务商提供的 API 根地址，通常包含版本路径；程序会追加 `/chat/completions`，不要填写完整请求地址 |
| `LLM_API_KEY` | 该服务的 API key |
| `LLM_MODEL` | 服务商提供的准确模型 ID，需要支持所选 JSON 输出模式 |
| `LLM_RESPONSE_FORMAT`（可选） | 默认 `json_schema`；仅支持 JSON Object 的服务显式填写 `json_object`，不支持其他值或自动切换 |

Windows 可在开始菜单搜索“编辑账户的环境变量”，在“用户变量”中新建这三个变量并填写自己的值。保存后重新打开运行项目的终端；如果从 Codex 启动验收，应重启 Codex，使新进程继承环境变量。真实 key 只配置在本机，不写入 `.env.example`、源码、报告或聊天。

目前也兼容旧 `TRAVEL_LLM_*`、`OPENAI_*` 名称，`LLM_*` 优先；T06.1 使用上述三个统一名称。以下本地预检不会调用模型，也不会连接小红书：

```text
.venv\Scripts\python.exe scripts/research_quality.py live-preflight
```

`G1_LIVE_LLM_BLOCKED` 表示模型未配置或配置格式不完整。当前私人模式配置通过时返回 `PRIVATE_LOCAL_CONFIG_READY`，只表示本地配置可用，不表示刚刚调用了模型或 G1 已通过；旧 SOURCE_POLICY 模式仍可返回来源策略阻塞。阻塞退出码为 2。

T06.1 的顺序是：环境配置 → 全部离线测试 → 完全合成 BodyBlock 的极少真实模型调用 → 来源用途检查 → 真实小红书受控验收。真实验收采用 OBSERVE_ONLY，首次最多 1 次搜索、3 次详情；模型连通失败或出现访问验证要求时停止。未配置模型时暂停，不把 Mock 验收作为 G1 PASS。

T06.1 合成正文的单次真实模型检查工具是 `.venv\Scripts\python.exe tools/llm_connectivity_smoke.py --live-llm`。不加 `--live-llm` 不调用模型；工具不导入浏览器，只记录脱敏错误、请求次数及合成引文。尝试前写入 `.local/t06.1-llm/connectivity.json`，已有记录就拒绝自动重跑，失败不会把本地摘取记为模型通过。人工修正配置、明确安排新检查后可加 `--attempt <新名称>`，保存独立账本；同名尝试仍拒绝重复，不删除历史记录，也不用于重置真实小红书预算。

本机首次模型检查返回 HTTP 404：配置使用 DeepSeek 的 `/anthropic` 地址，与项目 Chat Completions 协议不匹配。DeepSeek 的 OpenAI 兼容根地址是 `https://api.deepseek.com`，`/anthropic` 对应另一种接口。[官方协议说明](https://api-docs.deepseek.com/guides/anthropic_api/)；[OpenAI 兼容调用示例](https://api-docs.deepseek.com/guides/json_mode/)。此外，官方当前文档的 `response_format` 声明 `text/json_object`，因此该服务需要显式选择 `LLM_RESPONSE_FORMAT=json_object`。[Chat Completions 参数](https://api-docs.deepseek.com/api/create-chat-completion/)

地址修正后，本机以 `deepseek-v4-flash`、`json_object` 完成一次 HTTP 200 的合成正文检查，5 条证据的 schema 与正文定位全部通过。本次只在验收子进程中设置输出模式，没有修改 Windows 用户环境变量；之后使用该服务的进程仍需选择同一模式。当时真实资料仍为 **G1_LIVE_SOURCE_POLICY_BLOCKED**；后续用户已明确私人本地用途策略，当前按上方私人模式执行。模型检查通过仍不能替代真实 G1。

## 离线开发启动（T00/T01）

使用 Python 3.14 和 Node 22.12+，先运行 `uv sync --locked`，再在 `apps/web` 运行 `pnpm install --frozen-lockfile` 和 `pnpm build`。返回项目根目录运行：

```text
python scripts/doctor.py
python scripts/dev.py --mode mock
```

打开 `http://127.0.0.1:8765` 查看合成演示；Ctrl+C 停止。此演示不提供研究聊天或 T03 登录 UI；登录使用上面的独立 sidecar CLI。

测试：`python scripts/check.py --suite unit|contract|integration|security`（分别执行，竖线表示选项）；`e2e` 暂无测试时返回 5/SKIPPED。文档检查使用 `.venv\Scripts\python.exe tools/validate_pack.py` 或激活虚拟环境后运行原命令。合成演示资料在 Git 忽略的 `.local/`；T03 真实 profile 位于仓库外系统应用数据目录。真实浏览器默认关闭，所有自动测试离线。
