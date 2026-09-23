# T04：真实搜索与详情读取 Smoke Test

状态：**PARTIAL；搜索本次实测 PASS，详情适配器实测 FAIL，正文能力未验证。** 用户完成正常登录，并确认失败时浏览器显示正常图文笔记详情；程序返回 `UNEXPECTED_PAGE`，没有接受详情正文。已正常退出浏览器，保留专用 profile。本轮停止，不进入 T05；离线修复不能替代真实详情验收。

## 基线、环境与范围

- 分支：`feature/xhs-live-read-smoke`。T03 基线：`ccd329056794d3f29549ff0383f6236ce6373f36`；实际 `git merge-base --is-ancestor` 返回 0，未改写 T03 提交。本报告所属提交 SHA 由最终交付列出，不嵌入自身 SHA。
- 开始工作区只有三份既有未跟踪报告：`T03-login-smoke-test.md`、`T03.6-windows-chromium-diagnosis.md`、`T03.7-implementation.md`；保留原样，不混入 T04 提交。没有 push 或 PR。
- T03 已通过，依据用户确认及 [T03.8 报告](T03.8-implementation.md)；早期 14001 和旧 selector 失败不是当前环境结论。
- Windows 11 x64，build 26200；Python 3.14.7；Playwright 1.63.0；managed Chromium 153.0.8010.12、revision 1243、browser type `chromium`、channel `None`。版本来自对应已安装浏览器清单，运行使用该固定引擎。
- 可执行文件：`C:\Users\admin\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome.exe`；profile：`%LOCALAPPDATA%/TravelAgent/xhs/browser-profile`。
- 沿用 T03 `launch_persistent_context` 配置：`headless=False, args=[], no_viewport=True, chromium_sandbox=True, timeout=15000`。没有 UA/device/proxy/stealth 参数；args=[] 不表示 Playwright 自身默认参数为空。
- 用户授权一次搜索、最多两篇详情；实际一次搜索、一次详情尝试。失败占预算，不自动重试、换词或重开同篇。未实现 TravelResearchService、RAG、正式 CandidateSelector、Evidence 生成或最终攻略。

## 实站前审查

原 `FakeXhsBackend` 只有合成 search/detail，结果契约固定 offline/synthetic；login HTTP 路由拒绝 search/detail。原实现不能证明真实通道可用。因此新增独立 CLI 与内部 `live_smoke` 结果，复用 T03 BrowserManager/LoginLifecycle 与同一资源；不扩展现有 HTTP 路由、mode 或契约，HTTP 仍为 0.3.0。

实际阅读的 upstream 本地 checkout 干净，HEAD 为锁定参考 `8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff`。这是本次本地源码基线，不宣称重新核实远端最新 HEAD。参考 search.go、types.go 及详情实现的字段形状；未复制 Go 源码、运行其服务或调用其 HTTP 接口。

搜索读取 `__INITIAL_STATE__.search.feeds`（value/_value/直接数组），locator 来自 DOM `a[href]`。详情读取 `note.noteDetailMap[expected_id].note`，正文 DOM 参考 `#detail-desc, .note-content .desc, .note-scroller .desc`。这些路径仍可能随改版失效；只提取白名单字段，不序列化完整页面状态，不点击、滚动或额外 fetch。缺状态与明确空数组分开。

搜索校验官方 origin、路径和 keyword；详情校验官方 origin、相同 note ID 路径及内部 noteId。AccessLocator 使用当前 DOM 实际提供的官方 href，保留观察到的访问参数，不猜固定 xsec_source；token 不进入 SourceIdentity，TTL=UNKNOWN。真实 ID、定位材料和标题只留私有内存；输出匿名 hash、字段存在性和数量。

## Login

- 启动与首次本地 status：DISCONNECTED、BrowserSession=0、browser start=0，无导航。observer 未附加时网络数为 NOT_MEASURED，不把缺测写成 0。
- 初始 profile 不存在。显式 connect 进入 WAITING_USER；用户在官方页面正常登录并回复“已登录”，同一会话随后观察到 AUTHENTICATED、AccountIdentity=KNOWN，未输出账号标识。
- 是否重新扫码：**具体人工登录方式未采集（NOT_OBSERVED）**。确定需要重新认证并已正常完成，不能据此断言扫描了二维码。
- 全程 BrowserSession **1**、浏览器启动 **1**、LOGIN navigation **1**。未为确认登录重开浏览器或追加导航。
- 未观察到 verification、401/403/429 或访问限制信号。最后正常 quit，退出码 0、closed=true、observer detach；关闭后 SESSION_PRESENT_UNVERIFIED、身份 UNKNOWN，历史 authenticated_seen=true。这是保留 profile 的关闭状态。
- 退出后本地检查：匹配本专用 profile 的浏览器进程 **0**，profile 仍存在。T04 没有再执行 disconnect、重启复用或删除 profile。

## Search

实际 query：**`成都 川西 国庆 攻略`**；search_operations=1。未操作站内筛选，filter_status=NOT_REQUESTED，requested/applied 均空。没有翻页、滚动或补搜。

初始数组 22 项，2 项未满足有效笔记解析条件，得到 **20 个候选**；具体丢弃原因未单独记录。重复 ID=0，batch_capped=false。图文 normal=14、video=6；未打开视频。初始提取上限 80 项，不宣称覆盖全部搜索结果。

| 字段 | 本次可得性 | 限制 |
|---|---|---|
| note/feed ID | 20/20 OBSERVED | feed.id，报告不保留原值 |
| SourceIdentity | 20/20 DERIVED | provider + 稳定 note ID，与 token 分离 |
| title | 19/20 OBSERVED；1/20 NOT_AVAILABLE | noteCard.displayTitle，不伪造缺失值 |
| author/display info | 20/20 OBSERVED | 只报告存在性 |
| note type | 20/20 OBSERVED | 图文 14、视频 6 |
| cover | 20/20 OBSERVED | 元数据存在，不代表读懂图片 |
| interaction metadata | 20/20 OBSERVED | likedCount/commentCount/collectedCount/sharedCount |
| access locator / xsec 可用性 | 20/20 OBSERVED | 经校验的 DOM href，不记录 token 值 |
| publish time | 20/20 NOT_AVAILABLE | 本批没有可接受时间值 |
| summary/snippet | 20/20 NOT_AVAILABLE | 不把标题充当摘要 |
| destination/location | 20/20 NOT_AVAILABLE | 不把标题词或 IP 属地当目的地证据 |
| travel time | 20/20 NOT_AVAILABLE | 不把发布日期当旅行发生时间 |

缺失只说明本次白名单解析所得，不断言整个平台永远不提供。标题、类型、locator 足以粗筛，季节、交通、路线等事实仍需正文证据。

## Candidate

确定性选择优先图文、有 locator、标题含川西及攻略/路线/环线/国庆/成都/自驾词，按词命中排序并跳过相同标题；不按点赞最高排序，不用 LLM。依据标为 DERIVED，只表示可能有用，未证明正文研究价值。

选中索引 19、2，按稳定 note ID 去重。第一篇匿名来源 `xhs-sha256:e32d7aa10e70a74b5877af9a`，备用 `xhs-sha256:06b63b2466be60dd4e710077`。第一篇失败即停止，备用未打开。duplicate_details_avoided=0 表示没有提出重复调用；成功/失败来源都不重复访问的能力另由离线测试验证。

## Detail

| 候选 | 结果 | completeness | 正文、图片、评论 |
|---|---|---|---|
| e32d7aa10e70a74b5877af9a | 一次导航后 UNEXPECTED_PAGE；用户确认正常图文页 | NOT_EVALUATED | 没有接受详情 payload；字段/正文长度/完整性/source_locator 未知；未分析图片、未展开评论 |
| 06b63b2466be60dd4e710077 | NOT_RUN | NOT_EVALUATED | 未访问、未解析 |

detail_operations=1，成功解析详情 **0**。NOT_EVALUATED 仅是报告对未分类状态的说明，不是新增契约枚举。没有正文结果，不用 METADATA_ONLY/PARTIAL_TEXT 掩盖适配失败；搜索元数据也不冒充详情结果。

用户看到正常图文页不能证明读取器已取得正文。旧进程只记录 UNEXPECTED_PAGE，没有内部失败阶段，诊断为 **NOT_CAPTURED**；T03 缓存登录证据不能替代当前详情页证据。

本地审查确认 Python 路径校验要求跳转后的路径与 href 完全一致，而 JS 已允许相同 ID 的 `/explore/<id>` 和 `/search_result/<id>`。已最小修复并统一两种合法路径，仍拒绝不同 ID、其他 origin 和异常路径；新增固定 read_diagnostic 标签，不含 URL/token/异常原文。**代码不一致已确认，但不能确证就是本次失败根因。** 修复只经离线测试，没有实站复测，不倒填历史诊断。

完整度规则：HTTP 200 不等于 FULL_TEXT；有正文但范围未知为 PARTIAL_TEXT，仅摘要为 SUMMARY_ONLY，仅元数据为 METADATA_ONLY。FULL_TEXT 需正文与同页 DOM 一致、明确无截断/待展开及成功状态。真实脚本不假定 expandable/truncated=false，不能凭成功导航升级全文。正文 locator 使用文本版本 hash 与 Unicode 字符半开区间；本轮真实 locator 未产出。图片保持 IMAGE_NOT_ANALYZED，不做 OCR/视频分析/图片 Evidence；无法断言信息是否 IMAGE_ONLY。

## Network

以下为 **BrowserContext 真实 request 事件数**，scope=context_events_since_attach，包含失败请求、重定向与窗口内后台流量，不等于成功 HTTP 响应或全浏览器/OS 出站量。没有为测量增加导航/fetch 或阻断资源。业务操作与请求分别计数。

| 阶段 | navigation | document | xhr_fetch | image | media | other | total_requests | total_bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| LOGIN | 1 | 1 | 137 | 157 | 0 | 50 | **345** | NOT_MEASURED |
| SEARCH | 3 | 3 | 78 | 45 | 0 | 47 | **173** | NOT_MEASURED |
| DETAIL 1（失败前窗口） | 1 | 1 | 33 | 3 | 0 | 49 | **86** | NOT_MEASURED |
| DETAIL 2（未执行） | 未测 | 未测 | 未测 | 未测 | 未测 | 未测 | NOT_MEASURED | NOT_MEASURED |
| OUTSIDE_WINDOW | 0 | 0 | 73 | 45 | 0 | 3 | **121** | NOT_MEASURED |
| TOTAL | **5** | **5** | **321** | **250** | **0** | **149** | **725** | NOT_MEASURED |

- 应用一次登录导航、一次 search goto、一次 detail goto。SEARCH 同窗口观察到 3 个导航请求和 2 个 301 响应，与重定向行为一致，但未逐条保存请求链或 301 资源类别；不能称执行了三次 search。
- LOGIN 窗口 32.116361 秒、SEARCH 3.263935 秒、DETAIL 1 仅 1.174866 秒即停止。总观察跨度 284.482335 秒含等待操作者时间；OUTSIDE_WINDOW elapsed 不是独立空闲时长。
- 按请求发起窗口归属，晚到 response/finished 更新原窗口。最终 SEARCH：200=156、301=2、failed=15、finished=158；DETAIL 1：200=86、failed=0、finished=86。成功响应没有使详情解析成功。
- TOTAL：200=683、301=2、failed=31、finished=685；其余 9 个请求未观察到终结事件，不猜测结果。association_losses=0、callback_errors=0。字节量不可靠，total_bytes 始终 null。
- **详情 86 次仅是失败前窗口，不能当作完整成功详情成本。** OUTSIDE_WINDOW 121 次含后续加载/后台活动，不能全归给详情或忽略。没有延长等待或重开页面强求数字。
- context 附加前、未暴露给其事件的浏览器/worker/缓存行为不宣称覆盖。host 含 invalid=24、UNKNOWN=1；未保留 scheme 来追溯传输，725 不应表述为“725 个已验证 HTTP 出站请求”。全部 HTTP 字节、封面/头像精确分类和严格因果归因仍 NOT_MEASURED。

搜索自动加载 image=45；图片 CDN host 事件 34、头像 CDN host 事件 10，说明存在这类加载，但 host 数不是精确封面/头像分类。搜索 analytics 规则命中 32；media=0 不等于视频相关静态域资源为 0。

详情未调用评论加载器、展开或翻页，仍观察到 **1 次 comment 规则命中请求**。该用途由 host/path 固定规则 DERIVED，未读响应验证端点实际语义，不能声称取得评论正文；也不能仅因未展开评论就把评论相关流量记为 0。详情 analytics=12、image=3、media=0；全程 analytics=98、comment=1。

必要性暂作评估：官方文档/业务 XHR 是业务所需候选，图片/静态资源是页面展示，analytics 命中是可能非必要；未知 XHR 保持 unknown。没有响应证据证明每条请求的必要性，不做 aggressive blocking。本轮证明少量业务操作仍带来大量资源加载，尚未验证未来缓存/缺口研究可节约多少访问。

## Safety

- search=1、detail=1；无 fallback、第二篇、重复详情、无限加载、大量滚动、评论展开、OCR 或视频下载。
- 无点赞、收藏、评论、发布、私信、follow 等平台内容写操作。正常页面 POST 总计 208，不应误记成“全部 HTTP 方法都是 GET”。
- 无 stealth/fingerprint/代理/账号或 IP 轮换/CAPTCHA 绕过。页面或官方 document/xhr/fetch 出现登录/验证/401/403/429 会锁存停止；真实运行未触发这些限制。
- 派发前保存预算 checkpoint；失败占预算；非零记录阻止重启清零。generation/session 在派发前后校验；晚到拒绝只用 Fake 验证，没有重复实站制造竞态。
- 真实应用审计 **63** 条，非白名单记录 **0**，`SECRET_` sentinel 命中 **0**；原始日志不打印或保留。网络仅保留 host、方法、分类、状态、计数，不保存 URL/query/header/body。
- 注入秘密的脱敏回归使用合成 sentinel。真实日志没有注入实际秘密为扫描词，0 命中不是所有秘密的穷尽证明；本次安全摘要与应用日志检查未发现 Cookie/token 泄漏，不声称检查全部浏览器原生日志或 profile 内容。
- 真实运行只落地 Git 忽略的 `.local/t04-smoke/summary.json` 安全摘要，未存真实正文/图片/完整页面状态/截图/trace。报告只有匿名 hash、存在性、数量和状态，不提交 Cookie/session/xsec_token。

## 实现与离线验证

| 文件 | 关键符号与变化 |
|---|---|
| `live_page.py` | SEARCH_SCRIPT、DETAIL_SCRIPT、LiveBrowserBackend._read/_guard；复用 T03 owner 线程、固定读取、同 ID 双路由与诊断 |
| `live_parsing.py` | parse_search/parse_detail、LiveCandidate/LiveSearch/LiveDetail.safe_summary；字段真实性、身份/locator 隔离、保守完整度 |
| `live_reader.py` | LiveSmokeReader.search/detail/selection/_scope；1/2 硬预算、失败去重、generation、确定性选择 |
| `live_observability.py` | LiveNetworkObserver.attach/start_window/finish_window/snapshot、LiveNetworkSnapshot；被动窗口、晚到归属、限制锁存 |
| `live_smoke.py` | SmokeController、CountingBrowserManager、AuditCounter、main；显式操作、原子安全 checkpoint、有限退出 |
| `scripts/xhs_read_smoke.py` | 人工 CLI；无 --live 不启动 |
| `tests/unit/test_live_*.py`（5 份） | parser/JS VM/Fake 资源/预算/日志/网络/控制器回归 |
| `contracts/test-matrix.csv` | T04-01～15 设计条目，initial_status 保留计划值 NOT_RUN，执行结果见本报告 |
| README、sidecar README、设计/provenance、发布门槛文档 | 当前范围、T04 部分成功和停止边界 |
| 本报告、document-validation.md/json | 实测与文档检查输出 |

前五个模块均位于 `integrations/xhs-sidecar/xhs_sidecar/`。原 T03 登录模块和公共 HTTP 契约未修改。T04-01～05 由 parser 测试覆盖；06/10/13～15 由 reader/network 覆盖；07～09 由完整度/图片边界测试覆盖；11～12 由网络缺测/秘密注入测试覆盖。另覆盖 checkpoint、晚到 generation、官方限制、窗口外流量、JS 原子 origin 校验及关闭失败。

实际执行（自动测试全局 network deny，不启动真实浏览器）：

| 命令 | 实际结果 |
|---|---|
| `git merge-base --is-ancestor ccd329056794d3f29549ff0383f6236ce6373f36 HEAD` | 退出码 0 |
| `.venv\Scripts\python.exe scripts\xhs_read_smoke.py --live` | 人工登录成功、search PASS、detail UNEXPECTED_PAGE、quit 退出码 0 |
| `.venv\Scripts\python.exe -m pytest tests -q --tb=short -p no:cacheprovider` | 修复后 **382 passed，2 warnings，3.90s**；T01/T02/T03 回归通过 |
| `.venv\Scripts\python.exe -m ruff check .` | All checks passed |
| `.venv\Scripts\python.exe -m mypy` | 19 source files，无问题 |
| `.venv\Scripts\python.exe tools/export_sidecar_contract.py --check` | PASS，HTTP 契约快照一致 |
| `.venv\Scripts\python.exe tools/validate_pack.py` | **12/12 PASS**，162 个相对链接、137 个历史测试设计条目；见 [文档校验](document-validation.md) |
| `git diff --check`、`git diff --cached --check` | 均通过，无空白错误 |

两条 warning 是既有 FastAPI/Starlette 关于 httpx/anyio 别名的弃用提示。实站前全量 373 passed，后补路由回归后最终为 382；独立关联复核 130 passed、0.97 秒，未访问站点。修复后真实 detail 未复测，第二篇 NOT_RUN，不能计 PASS。

`git diff --cached --stat` 实际输出摘要（写入本段前的暂存快照；最终本报告新增行数由提交统计反映）：

```text
README.md                                           | 18
contracts/test-matrix.csv                            | 15
docs/15-release-acceptance.md                        | 8
docs/architecture/xhs-poc-design.md                  | 40
docs/architecture/xhs-upstream-provenance.md         | 17
integrations/xhs-sidecar/README.md                   | 54
integrations/xhs-sidecar/xhs_sidecar/live_observability.py | 339
integrations/xhs-sidecar/xhs_sidecar/live_page.py      | 255
integrations/xhs-sidecar/xhs_sidecar/live_parsing.py   | 403
integrations/xhs-sidecar/xhs_sidecar/live_reader.py    | 176
integrations/xhs-sidecar/xhs_sidecar/live_smoke.py     | 236
reports/T04-xhs-read-smoke-test.md                    | 157
reports/document-validation.json                    | 8
reports/document-validation.md                      | 8
scripts/xhs_read_smoke.py                            | 15
tests/unit/test_live_observability.py                | 396
tests/unit/test_live_page.py                         | 457
tests/unit/test_live_parsing.py                      | 316
tests/unit/test_live_reader.py                       | 193
tests/unit/test_live_smoke.py                        | 236
20 files changed, 3313 insertions(+), 34 deletions(-)
```

## Conclusion

1. search 本次简单关键词搜索可用，不能外推所有 query/筛选。
2. detail 适配器失败，正文和 completeness 的真实验证未完成。
3. 标题/类型/locator 能做第一层粗筛去重；相关性 DERIVED，不能证明日期、交通、路线事实。
4. 没有成功正文，尚不能判断研究所需内容是否足够；真实 source_locator 也待验。
5. 最大缺口：搜索缺发布时间、summary、目的地/地点、旅行时间证据；详情未通过、图片未分析。
6. 一次 search 窗口 173 个请求事件、45 个 image、3 个导航请求；同窗口另观察到 2 个 301 响应，未保存逐条重定向链。
7. 一次 detail 失败前窗口 86 个请求事件，含 1 次评论规则命中；完整成本未测，窗口外 121 次单列。
8. 暂不建议进入 T05。用户确认后另行授权最小详情验证，用固定诊断确定实际失败环节，再验正文、completeness、locator；不自动增加本轮预算。

**G0 整体未通过**（有限真实正文通道仍缺），G1 未验证。本轮本地提交和报告后停止，等待确认，不进入 T05/RAG/正式研究服务，不追加攻略搜索。
