# T04.2 + T05 实现与有限 Smoke 报告

状态：**离线实现 PASS；限定真实链路 PASS / COMPLETED_WITH_GAPS；TEXT_FIRST 请求量降低未证明；研究质量门禁未通过。**

基线 T04.1：`d3645464bfb5a6921bbca137faf37cb27334f35e`。工作分支：`feature/xhs-research-loop`。

用户要求的首步正常 connect 已完成；用户确认“已登录”，本地状态 AUTHENTICATED。随后正常关闭浏览器，保留专用 profile。开发期间没有搜索或详情访问。

实现范围与用途边界见 [T05 设计说明](../docs/architecture/t05-research-loop.md)。全部离线门槛通过后，只进行了一轮真实实验：**1 search / 2 detail，无 fallback、无额外搜索、无自动登录重试**。结束后停止实站。

## 离线结果

实站前统一执行完整 tests（T01～T04 回归 + 本轮新增）：**580 passed / 0 failed / 0 skipped**，4.36 秒，2 条既有依赖弃用提示。首轮 534 passed / 37 failed，修复 Fake 初始化和语义 JSON 比较断言后 579 项通过；再补来源许可在搜索期间过期、排序前重新校验的回归后 580 项通过。类型检查与 Ruff 的初轮问题也已修正。实站后仅修缓存提示展示并增加回归，最终 **581 passed，4.35 秒**；没有重新访问小红书。

Ruff PASS；Mypy PASS（31 个模块）；契约测试包含在 pytest，`tools/export_sidecar_contract.py --check` 也 PASS；文档包 12 类检查 PASS，实站前 171 个链接、最终报告整理后 175 个链接有效；git diff --check PASS。默认 CLI 运行零浏览器、零网络。没有调用模型服务或真实搜索/详情来修复离线问题。

| 用户验收项 | 覆盖文件与结果 |
|---|---|
| R01 / R02 / R03 | research_service / research_planning：充分缓存零 connect/search/detail、部分缓存定向 gap、查询去重，PASS |
| R04 / R05 | 同 source 一次 detail、LLM 排序失败确定性降级，PASS |
| R06 / R07 / R08 | evidence_extractor：引语和 block 校验、图片缺口、发布日期不替代旅行时间，PASS |
| R09 / R10 / R11 | research_service：提前停止、搜索/详情预算，PASS |
| R12 / R15 | verification 停止、revision/generation 晚返回禁止提交，PASS |
| R13 / R14 | 5 天/不自驾追加条件，保留证据且 0 预算不联网，PASS |
| R16 / R17 | resource_policy / live_observability：图片 abort 仍计 event，document/xhr 等保留，PASS |
| R18 | 同 source 一次技术 fallback 消耗 detail budget，限制/身份错误不 fallback，PASS |
| R19 / R20 | 未测网络 null、敏感 sentinel 与摘要隔离，PASS |
| R21 / R22 | PARTIAL_TEXT 保留、报告列明确缺口、图片缺口缓存保留，PASS |

实现文件：research 下 models / planning / service / store / extractor / live / smoke；providers/llm 与 mock兼容层；v3 SQLite 迁移；显式 scripts/xhs_research_smoke.py。现有 EvidenceBundle / EvidenceClaim / SourcePolicy 及 claim 枚举复用，未新增重复证据契约，也未扩展公共 HTTP 路由。

## 环境和 Login

本轮最终实站摘要落盘时间：2026-09-24 00:51:22（Asia/Shanghai）。运行的功能提交为 `edd8a0c9e6ddc0a57cb26add93f649b997a0afe5`。

| 项目 | 实测 / 配置 |
|---|---|
| OS / Python | Windows 11 10.0.26200 / 3.14.7 |
| Playwright | 1.63.0 |
| 实际浏览器 | managed Chromium 153.0.8010.12，revision 1243 |
| 可执行文件 | `C:\Users\admin\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome.exe` |
| launch | persistent context，channel=None，headless=False，args=[]，no_viewport=True；沿用 T03 chromium_sandbox=True |
| profile | 使用原 TravelAgent 专用 profile；开始存在、结束仍存在 |
| 本轮 connect / BrowserSession | 1 / 1 |
| 登录状态 / AccountIdentity | AUTHENTICATED / KNOWN；不记录敏感账号值 |
| 重新扫码 / verification / 限制 | 没有要求重新登录；观测范围内未出现验证或访问限制 |

用户要求的首步登录与最终 Smoke 分开：首步确认认证后已关闭；实现和测试期间没有站点访问；最终 Smoke 正常复用保存的 profile。本轮没有安装系统 Chrome，没有读取或导出 Cookie，没有修改 UA/指纹/代理。

## T04.2 网络结果

测量是 BrowserContext 自 attach 以来的 request 事件，按请求发起窗口归属，晚到响应回写原窗口。不是 OS 抓包、服务端收包数、全部浏览器进程流量或传输字节。HTTP 重定向与网页自身资源请求也会产生事件。

| 窗口 | navigation | document | xhr_fetch | image | media | font | script | stylesheet | other | total events | blocked | continued |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LOGIN / OBSERVE_ONLY | 1 | 1 | 60 | 91 | 0 | 0 | 32 | 10 | 3 | 197 | 0 | 0 |
| SEARCH / TEXT_FIRST | 3 | 3 | 125 | 61 | 0 | 0 | 34 | 10 | 3 | **236** | **61** | 165 |
| DETAIL_1 / TEXT_FIRST | 1 | 1 | 142 | 82 | 0 | 0 | 36 | 11 | 4 | **276** | **82** | 194 |
| DETAIL_2 / TEXT_FIRST | 1 | 1 | 152 | 81 | 0 | 0 | 36 | 11 | 4 | **285** | **81** | 204 |
| OUTSIDE_WINDOW | 0 | 0 | 19 | 0 | 0 | 0 | 0 | 0 | 0 | 19 | 0 | 0 |
| TOTAL | **6** | 6 | 498 | 315 | 0 | 0 | 138 | 42 | 14 | **1013** | **224** | **563** |

blocked 全部为 image；document/script/stylesheet/xhr_fetch 未被策略阻止。没有观察到 media/font 类型，因此不能由 0 宣称所有视频或字体相关传输均不存在。OBSERVE_ONLY 的 continued=0 仅表示没有经过本策略 handler，绝不表示该阶段零请求。

route attempts：SEARCH 226、DETAIL_1 276、DETAIL_2 285，总计 787；route errors=0。route 和 request 的统计对象不同（包括重定向、已有请求、缓存/Service Worker 等边界），不要求严格一一对应。业务操作是 search=1/detail=2，不能把 SEARCH 的 3 个 navigation 当作三次业务搜索；搜索窗口观察到 2 个 301 响应，未保存每条完整跳转链。

窗口长度：SEARCH 2.427183 秒，DETAIL_1 2.917630 秒，DETAIL_2 2.931622 秒；TOTAL 21.724332 秒。全部窗口 bytes=null / NOT_MEASURED；association_losses=0、callback_errors=0。TOTAL finished=622、failed=391，failed 包括主动 abort，不能把 391 全部判成站点故障。

历史 OBSERVE_ONLY 参考为 [T04.1](T04.1-xhs-detail-smoke-test.md)：SEARCH=173、成功 DETAIL=181。旧 other 包含 script/stylesheet/font，未分别测量这些子类别，不填造假的旧分类 0。本次观测总量 **236 / 276 / 285 均高于历史参考**，所以没有证据证明“请求量明显下降”。不计算减少百分比，也不做更多 A/B。

**保留策略代码作为显式实验选项，默认继续 OBSERVE_ONLY。** 已确认 abort 224 次图片加载且文字读取未被破坏，但未测 bytes，不能量化传输收益。路由关闭缓存、图片失败后的页面处理、XHR/HEAD/错误上报增加都是待验证解释，尚不能确认为增量的原因；未屏蔽这些 XHR 或 analytics 来美化数字。

## T05：真实研究材料

输入为“国庆从成都去川西玩”；预算、人数、交通保持 UNKNOWN。固定 query=`成都 川西 国庆 攻略`；query 数 1，候选 20，确定性筛选后读取两个不同来源。没有按点赞直接选择，也没有把搜索元数据当正文。无模型服务配置，实际模式是 **LOCAL_EXTRACTIVE**，不是 Mock 或真实 LLM。

| 项目 | 详情 1 | 详情 2 |
|---|---|---|
| identity | 后端及 parser 的同 ID 门禁通过 | IDENTITY_MATCH，安全诊断快照确认 |
| 主响应 | 200 | 200 |
| 正文字符 / 非空行 | 560 / 14 | 672 / 22 |
| completeness | PARTIAL_TEXT | PARTIAL_TEXT |
| 图片元数据 | 2，未分析 | 5，未分析 |
| Evidence | 3 条 | 3 条 |
| network / blocked | 276 / 82 | 285 / 81 |

两篇都取得 title、body、author、note type、publication time、topics/tags、interaction metadata；没有把 IP location 当目的地。DOM/state 文本不完全一致，展开/截断状态未知，因此保留 PARTIAL_TEXT；没有为了升级完整度增加滚动或展开。

内存 ResearchReport 形成 **2 条路线/区域线索、2 条体验、1 条时长、1 条交通线索**，合计 6 条，来自两个真实来源。每条都有 SourceIdentity 关联、正文 hash/字符偏移 locator、直接短引语；kind=AUTHOR_OPINION、support=PARTIAL、confidence≤0.25。applicable_conditions 未知保持空；实际旅行时间全部 null，不取发布日期替代。

这些数量是程序派生计数，不能视为 6 条已经交叉核实的旅行事实。本轮未配置模型，且当前 SourcePolicy UNKNOWN 不允许向外部模型发送材料或持久化第三方衍生内容。**实际引文、路线名称和标题仅进入临时内存材料视图，未导出到本 Git 报告；因此本交付不含可长期回查的真实路线清单。** 不用合成路线填补这个限制，也不称“最终攻略”。有许可资料的持久 SQLite 数据路径已离线验证，真实跨进程持久缓存仍 BLOCKED_SOURCE_POLICY。

首轮 stop_reason=**BUDGET_EXHAUSTED**。尽管四类都有线索，保守摘取不足以达到 0.5 的充分性阈值，仍有路线组合、体验差异、时长、交通可靠性缺口；另外有 IMAGE_NOT_ANALYZED、CONTENT_INCOMPLETE、TRAVEL_TIME_UNKNOWN、LOCAL_EXTRACTIVE_ONLY。没有为凑完整答案突破预算。未运行 OCR/视觉模型或评论抽取。

## Cache / Incremental

第一轮结束后先正常关闭浏览器，再在同进程、同内存 EvidenceStore 执行两次请求，排除后台页面流量。

| 请求 | revision | connect 增量 | search | detail | Evidence 复用 | 结果 |
|---|---:|---:|---:|---:|---|---|
| 相同问题，0/0 预算 | 0 | 0 | **0** | **0** | 2 来源 / 6 条 | BUDGET_EXHAUSTED，保留已有材料 |
| 追加 5 天 + 不自驾，0/0 预算 | 1 | 0 | **0** | **0** | 2 来源 / 6 条 | 新增 DAYS_FIT / NON_SELF_DRIVE |

两次调用期间 observer 的 context request event 差值 **0**，没有活跃浏览器，也没有 connect。临时 cache hit 与增量证据复用均 **YES**。不把部分缓存命中写成 EVIDENCE_SUFFICIENT；原四类质量缺口仍保留，新条件只追加 5 天适配性和不自驾交通研究需求，没有清空资料或编造适配结论。

实测发现一个展示缺陷：旧版本缓存 Report.gaps 漏列 IMAGE_NOT_ANALYZED / CONTENT_INCOMPLETE / TRAVEL_TIME_UNKNOWN / LOCAL_EXTRACTIVE_ONLY；EvidenceBundle.missing_fields、完整度、置信度和旅行时间并未丢失。随后仅离线修复从 Bundle 恢复这些提示，提交 `0210eb40b3c35339b23f7db9bb5e075b2cea2e0c`，新增合成回归，全套 581 PASS。原实测账本保留原结果，**没有为此再读真实站点**。IMAGE_INFORMATION_REQUIRED 的缓存防护在实站前已通过测试。

真实缓存仅在这一进程内有效；内存数据库和 Evidence 已随进程退出销毁。跨重启真实 Evidence 复用 **NOT_TESTED / 来源策略阻塞**，不能用本次 0/0 结果代替；保留的浏览器 profile 仅支持后续正常会话复用。

## Safety / 清理

- 主动平台内容写操作=0，评论展开=0，自动翻页/滚动=0；没有 stealth、fingerprint、proxy、CAPTCHA bypass。页面自身 POST 不是用户点赞/发帖等业务写行为，不把网络 POST 统计强写为 0。
- 默认页面请求中 comment 类规则命中 4，属于 DERIVED host/path 分类，未读取评论内容，不是展开评论。
- 详情 fallback/retry=0；业务预算最终严格 1/2；应用没有自动重登。
- 应用安全审计 3 条，非白名单 0，SECRET_ sentinel 命中 0；合成敏感字段/异常注入测试 PASS。报告和 Git 未发现 Cookie、token、真实 AccessLocator、账号标识或正文泄漏。检查范围不包括穷尽浏览器原生日志或读取 profile 内容。
- 进程退出码 0，closed=true，observer detach。进程枚举确认专用 Chromium **0**、XHS sidecar **0**；profile 保留。没有 disconnect，后续启动应先为 SESSION_PRESENT_UNVERIFIED，实际认证仍要显式 connect 检查。
- 真实摘要只位于 Git 忽略的 `.local/t05-smoke/summary.json`；未提交真实 SQLite、图片、profile、trace 或完整正文。前三份既有未跟踪 T03 报告保留原状，未误提交。

## 结论与下一步

1. **TEXT_FIRST 值得作为可选实验保留，尚不值得全局开启。** 它成功阻止图片加载并保持文字读取，但请求事件总量高于历史参考，未证明总体请求成本改善。
2. **ResearchService 真实有界链路已跑通**：搜索→筛选→两篇详情→本地来源摘取→临时资料库→材料报告；模型抽取与真实持久资料库不能标 PASS。
3. **cache 0 访问复用、增量保留证据已实测成立**，限同进程临时证据；约束可行性尚未验证。
4. **Evidence 质量为低置信、部分正文的作者经验材料**；有定位，但不具备官方事实、全文、旅行时间或完整行程含义。下一步先解决可用且用途获准的结构化模型配置/证据核验，再核实持久化权限和撤销策略；不要扩大抓取来掩盖质量缺口。
5. 下一次经授权的资源实验应先解释 routing/cache 和额外 XHR/HEAD/失败事件来源，保持默认 OBSERVE_ONLY；本轮不再追加访问或 A/B。
6. 对照现有 [门禁定义](../docs/15-release-acceptance.md)，**G0 本机受控只读数据通道可以通过**：T03 正常登录/复用/断开历史已通过，本轮登录复用、有限搜索正文、只读边界和用途限制均有记录。此结论不扩大到所有笔记或持续可用性。**G1 研究质量仍 NOT PASS**，也不满足 D1/D2 或产品发布门槛；未验证酒店、地图、报价或完整行程。

## Git 交付

- 分支：`feature/xhs-research-loop`，包含 T04.1 指定基线，未改写历史，没有 push/PR。
- `3b743d1f04a32636c45cac9291920bd460f45a16`：`feat(xhs): add text-first resource policy`，7 files，730 insertions / 16 deletions。
- `edd8a0c9e6ddc0a57cb26add93f649b997a0afe5`：`feat(research): add evidence-driven xhs research loop`，27 files，3150 insertions / 15 deletions；这是唯一实站运行的功能版本。
- `0210eb40b3c35339b23f7db9bb5e075b2cea2e0c`：`fix(research): preserve material gaps on cache reuse`，2 files，32 insertions / 5 deletions；仅离线验证。
- 最后以单独报告提交记录本次实测，不包含真实内容。最终报告提交 SHA 和累计 diff stat 见交付回复，避免在文件中循环引用自身 commit。

完成后停止，不进入酒店、地图、交通报价或完整行程开发。
