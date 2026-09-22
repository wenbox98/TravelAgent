# XHS PoC 上游分析｜2026-09-22 设计审查

## T02后续实施记录

本审查已获用户接受。T02按新范围选择**独立Python只读sidecar**，upstream仅reference，没有复制或修改Go源码，也不运行其二进制。下文原审查结论保留；“必须patch”的控制目标改由自有服务实现或明确留待后续阶段，不能据此声称upstream原问题已经修复。

T02 建立 Fake 普通浏览器会话、路由白名单、源头日志排除、筛选状态、完整度分类、identity/locator 分离和未知网络指标；历史结果见 [T02 报告](../../reports/T02-implementation.md)。来源见 [provenance](xhs-upstream-provenance.md)，锁文件已同步至下文 SHA，approved_for_release 仍为 false。

## T03 登录生命周期实施边界

用户已授权 T03 离线实现：在自有 sidecar 的 BrowserManager 后接标准 Playwright 普通 Chrome/Chromium，持久 context 使用系统 appdata 内专用 profile，保留官方窗口供用户正常登录。没有复制 upstream 指纹浏览器或 Cookie 文件写入逻辑；本阶段不提取二维码图片、不实现真实 search/detail、研究或 GUI。

本地 `GET /v1/login/status` 只读缓存；显式 connect 才启动、导航一次，然后在同一页观察 DOM。profile 存在只表示 SESSION_PRESENT_UNVERIFIED。断开先增加 generation、取消任务、关闭自有浏览器，再清 profile；普通关闭保留 profile，重启不联网。challenge 暂停，显式 resume 才在原页继续观察，稳定账号 ID 未知不推断。

这解决 A01/A04～A09 的自有生命周期控制要求，但不代表 upstream 已被修复，也不代表当前网页选择器或真实会话恢复已验证。`login_status_external_requests=0` 只描述本地查询路径；connect 全浏览器流量仍为 NOT_MEASURED/null，A18 的真实网络节省结论继续待测。T03-01～T03-18 的实际离线执行结果以 [T03 实现报告](../../reports/T03-implementation.md) 为准，API 边界见 [sidecar README](../../integrations/xhs-sidecar/README.md)。

**本轮提交并汇报后停止。** 真实浏览器启动、扫码与重启复用 smoke 均为 NOT_RUN，须用户另行确认；真实研究仍属 T04 以后，不因登录代码存在提前执行。

## 目的
本文件把 `xpzouying/xiaohongshu-mcp` 视为候选上游能力，不视为官方内容 API，也不视为已经在线验证成功。原设计审查轮只修改两份架构文档，没有编写业务代码、启动 upstream、安装浏览器或访问真实小红书；后续T02范围见开头实施记录。

**结论：缓存优先、缺口驱动、先筛后读的方向成立；原样运行 upstream 再套 REST wrapper 不满足本项目约束。普通浏览器替换、生命周期、源头脱敏、只读裁剪和可观测性是必需改造。**

## 计划复用
- 正常官方页面的二维码、登录 DOM、当前用户同页读取逻辑，注入普通浏览器 page 后复用；不是直接复用原浏览器实现。
- 搜索筛选枚举、候选及 feed detail 的字段解析片段；外围导航、筛选完成判断与错误处理需要改造。
- feed_id/xsec_token 等仅在受控 adapter/session 内处理。

## 明确不复用/不暴露
- 发布、评论、点赞、私信等写能力。
- 原始 MCP 全工具面向 LLM 的自由调用。
- 任意 URL、任意浏览器控制端点。
- CAPTCHA 破解、代理/IP/账号轮换、stealth/anti-detect。

## 与 TravelAgent 的差异
1. 上游“能调用搜索/详情”不等于旅行研究调度；本项目需要 Evidence Gap、候选筛选、预算、去重、早停与复用。
2. UI/CLI 轮询必须只轮询本地状态，不能每次状态刷新都新建浏览器或访问站点。
3. 登录材料不得进入模型、普通日志或 Git。
4. source identity 与一次访问所需 locator/token 分离；后者不是长期知识库主键。
5. 上游错误必须映射为 `NEED_LOGIN / VERIFICATION_REQUIRED / RATE_LIMITED / CONTENT_UNAVAILABLE / PARSE_ERROR ...`，不能一律重试。

## wrapper 优先策略
原审查采用 `XhsReadonlyAdapter + 必需 sidecar patch + 普通浏览器`，因为 wrapper 无法满足原实现的浏览器、源头日志、取消和筛选语义要求。T02/T03 选择自有 sidecar 落实控制，不运行或修改 upstream；因此没有 upstream patch hash，不能填造。后续若引入源码 patch，仍须记录原因、commit、真实 hash 与同步方式。

## 待真实验证
- Windows/中国大陆网络环境下扫码登录、重启后会话复用和失效恢复。
- 搜索结果/详情字段的当前稳定性和内容完整度。
- 真实页面访问时的 operation/page/http 三类计数差异。
- challenge/verification/rate limit 的实际错误表现。

这些项目在真实 smoke test 前保持 `NOT_RUN/BLOCKED`，不得用 mock 结果代替。

## 当前基线与证据

| 项目 | 本轮核实结果 |
|---|---|
| 远端 HEAD / main | `8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff`，`git ls-remote` 与本地干净 checkout 一致 |
| 提交时间 / 标题 | `2026-09-22T14:31:32+08:00`；`fix(publish): 发布前先建立创作者中心会话 (#855)` |
| 审查前候选 | [upstream-lock.json](../../contracts/upstream-lock.json) 原为 `aad2a3d249a347859975ce3b76d3442c4a027780`；T02已同步当前固定SHA，仍未获发布批准 |
| 新旧差异 | 仅 `creator_session.go`、`publish.go`、`publish_video.go`，增加78行；此次审查的 README、登录、搜索、详情、browser/session 文件未变 |
| 关键依赖 | `headless_browser v0.4.0`，tag 对应 `d28e37c7448672550580fca8ff26404aed09a21f`，额外阅读其源码 |
| 判定 | 发现的问题主要是原有假设和此前审查遗漏，不能归因于本次 upstream 更新 |

设计审查轮网络仅用于GitHub及依赖源码核对，当时未改锁文件；T02已按reference-only策略同步。已阅读的HEAD不是已构建/实机验证的发行基线，无patchset/产物时hash保持null。

### 实际阅读的文件

以下链接固定到审查 SHA。以实现为准，README 作为公开接口描述参照，不把其中经验性稳定/封禁说法当保证。

- [README](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/README.md)、[API 文档](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/docs/api.md)、[go.mod](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/go.mod)。
- [main.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/main.go)、[routes.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/routes.go)、[middleware.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/middleware.go)、[app_server.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/app_server.go)。
- [service.go 登录/search/detail](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/service.go)、[handlers_api.go 对应 handlers](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/handlers_api.go)、[types.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/types.go)。
- [login_session.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/login_session.go) 及其测试、[xiaohongshu/login.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/xiaohongshu/login.go)、[cmd/login/main.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/cmd/login/main.go)。
- [browser/browser.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/browser/browser.go)、[browser/browser_download.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/browser/browser_download.go)、`browser/browser_version.txt`、[cookies/cookies.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/cookies/cookies.go)、[configs/seed.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/configs/seed.go)。
- [xiaohongshu/search.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/xiaohongshu/search.go)、[xiaohongshu/types.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/xiaohongshu/types.go)、[feed_detail.go 配置/读取/可访问性/提取/URL 路径](https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/xiaohongshu/feed_detail.go)、相关测试声明。未运行真实 integration 测试。
- [headless_browser v0.4.0](https://github.com/xpzouying/headless_browser/blob/d28e37c7448672550580fca8ff26404aed09a21f/headless_browser.go)。

## 发现的问题

P0 是接入真实站点前的阻断项；P1 是正确性/低请求验收前必须解决；P2 是文档/构建一致性。均为静态结论，未声称在线复现。

| 编号 | 级别 | 源码事实 / 错误假设 | 修正与归属 |
|---|---|---|---|
| A01 | P0 | `browser.go:68` 的 WithFingerprint 空参数启用 CloakBrowser 指纹；WithStealthJS(false) 只关 JS，依赖仍设置 fingerprint 及 UA/Client Hints | 替换工厂、内置启动和 seed 路径；不复用指纹/stealth/humanize 模块，必须 sidecar 改造 |
| A02 | P0 | 默认监听 `:18060`；Bearer 为空关闭鉴权；CORS 为 `*`；写路由和 MCP 全工具仍注册 | 强制 loopback/非空凭证/Host与Origin限制；源头删除非白名单路由和 MCP，不能仅外层代理过滤 |
| A03 | P0 | `feed_detail.go:104` 输出完整含 token URL；handler/recovery 透传原始错误或 panic | 源头日志、错误和崩溃路径使用允许字段；wrapper 事后脱敏无法收回日志 |
| A04 | P1 | status/search/detail 每次新 browser，完成后关闭；通过 Cookie 文件传递登录材料 | Cookie 复用不等于常驻 browser/profile；SessionManager 生命周期要自己实现 |
| A05 | P1 | QR 每次先建浏览器/导航，之后才 start 取消旧 waiter；取消不等待退出 | 创建前幂等；“只有一个登记 waiter”不保证任意时刻只有一个浏览器 |
| A06 | P0 | finish(seq) 只保护登记清理；saveCookies 不检查 generation；DeleteCookies 只删文件 | 注销先让旧 generation 失效，取消并确认关闭；Cookie 原子提交需校验 generation，防晚到回写 |
| A07 | P1 | QR 后台 context 脱离 HTTP；无事件/查询/取消 API；建页或 Must 异常可能绕过正常清理 | 自有任务、结构化事件、全退出路径清理；HTTP 断开不等于浏览器关闭 |
| A08 | P1 | 启动 SaveSeed 可写空 Cookie 文件；SaveCookies 直接 WriteFile；普通读取不保存更新后 Cookie | 文件存在/mtime 不是登录证明；专用存储、原子更新、权限和持久化时点要补齐；不沿用 seed |
| A09 | P1 | 登录元素不存在返回 false；已登录也可能读不到账号 ID；status 会导航 explore | UI只轮询本地状态；身份未知不凭昵称/布尔值合并历史账号缓存 |
| A10 | P1 | search 逐项点击筛选；waitFeedsChanged 超时只 warn 并返回可能旧的结果；ID变化不证明全部筛选完成 | sidecar 报告可验证筛选状态；未知不能按已生效缓存，不无预算重搜 |
| A11 | P1 | 候选无正文摘要、发布日期、旅行日期；只有标题、作者、类型、热度、封面等 | 未知标 UNKNOWN；可选视频时长不是行程天数；mock 丰富字段不代表实接字段 |
| A12 | P1 | location 是不限/同城/附近；无任意日期、目的地、游标/page_size；count 是本批长度 | 地点用 query/证据核验，不承诺全量、页数或平台总量 |
| A13 | P1 | detail typed struct 无完整度证明，Go 零值掩盖字段缺失；data.feed_id 只是请求回显 | 校验 data.data.note.noteId；记录字段存在性；成功不自动标 FULL_TEXT |
| A14 | P1 | false 跳过评论展开，仍提取首屏 comments；无 README 所称固定前10条截断 | 固定 false 并丢弃 comments；不声称页面没有评论/媒体请求 |
| A15 | P1 | URL 固定 xsec_source=pc_feed；无 token TTL、账号绑定或永久有效契约 | source identity 与 locator 分离；内存保留期是应用策略，不是平台寿命；不轮换参数试探 |
| A16 | P1 | handlers 多为通用500；详情错误容器不存在/读取失败就当可访问 | 500不能推断失效、封号、限流；需要已观察原因，未知保留，不盲重试 |
| A17 | P1 | detail retry.Attempts(3) 闭包调用 MustNavigate/MustWait 后返回nil；另有 DOM Eval 重试 | Must panic 不是普通error；配置不证明实际重试3次。改受控错误、单一重试所有者，DOM重读与导航分计 |
| A18 | P1 | 3/6只限业务操作，auth、筛选刷新、二维码后台、资源/媒体另有流量 | 缓存判定早于 EnsureSession；补网络观测，否则只证明逻辑操作减少 |
| A19 | P2 | main 启动先下载/准备内置浏览器；缓存命中不复核hash，checksum来自同CDN；锁无产物hash | 独立设计普通浏览器供应与校验；不能当作已批准发行包 |

`browser_download.go` 还按归档名称拼接 tar/zip 路径、支持 tar 符号链接，并在 macOS 移除 quarantine。本次未执行或构造归档验证漏洞；这些代码不随替换浏览器盲目继承。当前内置包仅有 Windows amd64、Linux amd64、macOS arm64 分支，不能推导全平台可用。

## browser/session 实际行为

```text
status / search / detail
 → 新browser → 导入Cookie → 新page → 导航/读取 → 关闭page和browser
qrcode
 → 新browser/page → 导航、取官方二维码 → 后台保留page等待
 → 检测登录、保存Cookie → 关闭
```

依赖 Close 执行 browser.MustClose 与 launcher.Cleanup，未见应用配置完整持久 profile 的契约。不能承诺 localStorage、其他站点存储或刷新后 Cookie 全部跨进程恢复；Cookie 恢复是否足够仍需授权实机验证。

WaitForLogin 每500ms读取当前 DOM，不主动反复导航；既不是每次DOM查询等于一个站点请求，也不保证扫码等待零网络，页面自身可能轮询。cmd/login 的前检查、Login、后检查可能分别导航，不能直接复用为低请求状态查询。REST 没有“将当前无头二维码页转换成可见窗口”的接口，需自己管理；无法延续上下文时先取消并等旧上下文退出，再开新官方流程。

## REST 与数据契约

成功是 `{success:true,data:...,message:...}`；错误是 `{error,code,details}`，不是本应用 FetchResult。原始响应不得直接进模型。

| 路径 | 实际实现 | 适配要求 |
|---|---|---|
| GET login/status | data.is_logged_in，可选 username/user_id；新浏览器并导航 | 只作远端核实，不给UI轮询；脱敏账号 |
| GET login/qrcode | timeout为Go duration `4m0s`，已登录`0s`；img为DOM src | 转换应用等待期限，不假定平台TTL或始终PNG base64；二维码仅内存 |
| DELETE login/cookies | 只删文件，返回 cookie_path | 不是完整注销，不暴露本地路径 |
| POST feeds/search | `{keyword,filters:{...}}`；GET仅keyword；data.feeds/data.count | 单对象filters，拒绝未知字段，浏览器创建前验证 |
| POST feeds/detail | `{feed_id,xsec_token,load_all_comments:false}`；配置嵌套comment_config | 不传comment_config；正文是 data.data.note.desc，不是 data.desc |

以上路径均带 `/api/v1/` 前缀。枚举：sort_by=综合/最新/最多点赞/最多评论/最多收藏；note_type=不限/视频/图文；publish_time=不限/一天内/一周内/半年内；search_scope=不限/已看过/未看过/已关注；location=不限/同城/附近。

非空筛选值包括显式“综合/不限”也触发点击。减少无必要筛选并验证目标状态，不能假定一次搜索只有一个搜索请求。onlyNotes 的 modelType=note 同时包含图文和视频。缺日期/摘要不能通过预读所有详情补齐，否则先筛后读失效。热度字符串解析失败保留未知。

detail.time 为int64，结构未声明单位；文档示例像毫秒，应按待验证毫秒候选做范围校验，不能当旅行日。图片/视频/字幕 URL 可能带签名，不直接存入数据库/模型，不启动视频下载或转录。

### source identity 与 xsec_token

- 稳定身份是 provider + note ID；账号/来源政策单独控制缓存隔离，token不进入source_id。
- 搜索id/xsecToken形成内存 `note_handle → {note_id,token,account_scope,generation,observed_at}`；模型只有安全handle与元信息，无任意URL能力。
- detail URL当前直接fmt拼接，需ID校验和正确URL编码；结果noteId须匹配请求，外层feed_id回显不算验证。
- detail的xsec_source=pc_feed与search的source=web_explore_feed是不同参数，都不是证据来源身份，不允许模型选择/切换它们试探访问。
- token真实TTL、跨账号特性未验证。内存限期、不跨账号和注销清理是本应用策略，不能表述成已知平台保证。
- 脱敏引用可用 `https://www.xiaohongshu.com/explore/{note_id}`，但不保证无token/登录可打开。合法保留的Evidence可独立复用；locator丢失后若确需重读，重新定位占搜索预算，不能后台无限补token。

### upstream 文档与实现不一致

| 描述 | 当前源码 |
|---|---|
| README FAQ：用户名写死 | CurrentUser从已加载页面读真实信息，但可能缺失 |
| API：timeout=`"300"`、单位秒 | 返回`"4m0s"`/`"0s"`，为应用等待时限 |
| API/注释：max_comment_items=0加载全部 | normalize将非正值回填默认20；回复阈值默认10 |
| README：false仅前10条一级评论 | 跳过额外加载，没有固定10条裁剪 |

## 复用决策

“直接复用”指裁剪后的片段，不表示可以直接运行原二进制。

| 分类 | 能力与边界 |
|---|---|
| 可直接复用片段 | 官方页面二维码/登录DOM与同页账号读取；筛选枚举；initial state value/_value解析、onlyNotes、详情字段解码；非空Bearer比较逻辑。页面稳定性待验证，注入普通page、剔除指纹/humanize依赖 |
| wrapper处理 | 参数/响应解包、规范化、handle/token隔离、source与账号隔离、完整度降级、预算/缓存/去重/串行、已知错误翻译。不能凭500重建上游没提供的原因 |
| 必须sidecar改造 | 普通浏览器与生命周期、写路由/MCP裁剪、源头脱敏、generation Cookie提交、登录事件/取消、筛选状态、访问错误、导航/网络计数 |
| 必须本项目实现 | SessionManager、恢复与账本、来源政策/EvidenceStore、Gap/Query/Candidate/Extraction流程、时效/来源支持、早停与质量评测。骨架/mock不等于这些已完成 |
| 不复用 | 写工具、用户主页/推荐流/通知等非PoC功能、MCP全工具、指纹/stealth/轮换、验证码处理、视频和批量评论 |

## 低请求判断

缓存足够即返回、查询合并、同note合并、逐篇重算缺口后停止、第二轮只补新条件，确实能减少逻辑操作，前提是这些判定早于浏览器启动与站点访问。目前没有真实HTTP节省率证据。

实际流量涉及认证导航、搜索导航、筛选刷新、详情导航/重试、资源/媒体和QR后台请求；这些分类可能重叠，不能与业务次数简单相加。DOM Eval重试也不等于再次导航。

必须落实：

1. Reuse/Gap早于EnsureSession，缓存命中不status/qrcode/保活。已有QR页/后台浏览器联网时，只能称本次研究无新增读取，不能称测量窗口HTTP=0。
2. 3/6、2/4、累计5/10仍是逻辑护栏；auth/导航/筛选/后台另观测。缺测为null和PARTIAL/UNAVAILABLE，不能填0。
3. 不预取Top-10、不为评分字段补读全部正文、不因筛选失败隐式重搜。
4. 同run同source最多一次详情派发，失败也计入；当前PoC禁止自动详情重发，避免与“一次外层重试”规则自相矛盾。
5. 缓存命中必须满足来源权限、账号、用途、时效；权利未知不能为命中率保存原文/衍生数据。纯内存证据退出后可能丢失，不承诺重启零搜索。
6. 固定合成池离线比较相同质量下操作量；30%只是离线目标。以后授权的极小smoke也不为了对照而真实抓Top-10。

## 设计审查时的待同步点

T02 已同步来源登记与锁文件并新增独立 sidecar 契约；T03 同步 03、登录状态/内部 API、任务/矩阵与验收。研究仍为后续要求。内部 API 不修改 T01 Evidence/SQLite/业务 OpenAPI 语义。

- [03 登录设计](../03-xhs-access-login.md)：T03 已改为普通可见窗口和浏览器原生 profile 持久化；status 无网络，generation 先失效再关闭/清理。短生命期 token 仍是应用策略，真实搜索未实现。
- [04 低请求策略](../04-research-efficiency.md)：一般网络最多一次重试是上限，PoC详情采用更严格的无自动重发；不能同时无条件承诺“一source一次”与自动重试。
- [锁文件](../../contracts/upstream-lock.json)：显式更新候选/审查路径/补丁，构建后再记录产物hash，验收前保持approved_for_release=false。
- [领域契约](../../contracts/domain.schema.json)、[OpenAPI](../../contracts/openapi.yaml)、[数据库契约](../../contracts/database.sql)：新筛选状态、会话事件、错误/观测字段需同步契约、实现和测试；本设计字段未自动加入API。

## 原设计审查时的状态与下一阶段

| 状态 | 本轮结论 |
|---|---|
| PASS（静态） | 远端SHA、源码阅读、新旧差异与复用边界核对，不代表运行通过 |
| FAIL（原样接入门禁） | 默认指纹、全工具面、token日志和不完整取消违反项目要求 |
| SKIPPED（范围外） | 业务实现、upstream构建、浏览器安装、应用和实站测试 |
| BLOCKED（真实接入） | 必需patch与授权实机验收未完成；登录/重启复用、search/detail稳定性、完整度、HTTP节省均未验证 |

以上表格保留原设计审查时的结论。T02 已完成；当前 T03 仅实施登录生命周期与离线验收。完成提交后等待用户确认，再单独进行人工登录 smoke；不继续 T04 或真实研究。
