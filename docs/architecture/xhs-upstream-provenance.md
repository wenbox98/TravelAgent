# XHS upstream provenance｜T02/T03/T04

## 固定参考

- Repository：`https://github.com/xpzouying/xiaohongshu-mcp`
- Commit：[`8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff`](https://github.com/xpzouying/xiaohongshu-mcp/commit/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff)
- 提交时间：2026-09-22T14:31:32+08:00；设计审查时远端HEAD/main与本地checkout一致，本轮继续使用明确批准的固定SHA，不自动升级。
- upstream LICENSE文件为Apache-2.0；本项目尚未选择许可证。本次没有vendored upstream源码，不宣称已经完成发行许可证审查。

## 实际复用和修改

**复制的upstream实现文件：0；修改的upstream文件：0；运行的upstream二进制：0。** T02采用独立Python实现；不导入Go MCP、headless_browser、CloakBrowser、humanize或其浏览器下载器。不存在需发布的upstream patchset，所以patchset_sha256保持null；这不是遗漏补丁hash。

| upstream参考 | 本项目实现 | 复用/差异及原因 |
|---|---|---|
| xiaohongshu/search.go:FilterOption | integrations/xhs-sidecar/xhs_sidecar/models.py:SearchFilters | 参照固定枚举；新增requested/applied/status，避免筛选未知冒充已生效 |
| types.go / xiaohongshu/types.go | models.py:SourceIdentity、AccessLocator、Candidate、RawDetail | 参照note ID/token关系；独立定义严格类型，凭证不进入公共响应 |
| feed_detail.go | completeness.py:classify_completeness | 没有复用页面抓取代码；HTTP200不证明全文，按文本范围证据保守分类 |
| browser/browser.go、service.go | browser.py:BrowserManager、service.py:SidecarService | T02新建Fake生命周期抽象；T03继续复用同一会话，未导入上游浏览器实现 |
| xiaohongshu/login.go | login_detection.py:LOGIN_OBSERVATION_SCRIPT | 历史 T03 参考旧登录 selector；T03.8 已用多信号和同页 userInfo 修复旧 selector 单点依赖，并完成本机登录验收 |
| 非upstream代码 | ordinary_browser.py、profile.py、login.py | 标准Playwright 1.63.0、platformdirs 4.11.12；自有persistent context、profile归属、generation及取消清理，不依赖Go指纹浏览器链 |
| routes.go、middleware.go | app.py:create_app、redaction.py | 独立只读路由注册、强制本机鉴权、日志字段白名单；没有隐藏/配置关闭的写工具 |
| 原上游无研究网络计量契约 | observability.py | 导航与HTTP类别分离；NOT_MEASURED/null和SIMULATED，不伪造真实请求数 |
| xiaohongshu/search.go、types.go 的字段/页面状态形状 | live_page.py:SEARCH_SCRIPT、live_parsing.py:parse_search | T04 独立读取现有页面状态的字段白名单，按稳定 ID 去重；记录 OBSERVED/DERIVED/NOT_AVAILABLE，不复制 Go 实现或运行其服务 |
| xiaohongshu/feed_detail.go 的 noteDetailMap/note 形状 | live_page.py:DETAIL_SCRIPT、live_parsing.py:parse_detail | 独立读取正常详情初始页，核对 ID；不调用 upstream 接口，不展开评论，不以页面成功证明 FULL_TEXT |
| 原上游无此实验约束 | live_reader.py、live_smoke.py、live_observability.py | 自有 1 搜索/2 详情硬预算、正常浏览器事件计数、异常停止和匿名本地摘要；未把该内部路径扩展为 HTTP mode |

上述为行为/接口参考，不是兼容整个upstream REST响应或二进制。当前也没有把本服务接入TravelResearchService；该业务循环仍未实现。

历史 T03 初次交付只运行合成离线测试，没有启动真实 Chrome/Chromium 或访问小红书，当时真实登录/重启复用为 NOT_RUN；该结论只描述 [初次 T03 报告](../../reports/T03-implementation.md)。后续 [T03.8 验收](../../reports/T03.8-implementation.md) 已通过本机正常登录、重启复用与清理，最终基线为 `ccd329056794d3f29549ff0383f6236ce6373f36`。`vendored_source_files=[]` 表示未引入上游源码文件，不表示未参考其 DOM 和契约行为。

T04 延续上述固定 upstream SHA，reference-only，无源码复制、Go 二进制运行、upstream HTTP 调用或补丁集。`scripts/xhs_read_smoke.py --live` 为独立人工入口，启动本身不访问站点，显式 connect 后才打开普通 Chromium；沿用 T03 专用 profile 与一个 BrowserSession。现有 HTTP 契约保持 0.3.0 的 offline/login，内部 `live_smoke` 结果不能作为新增 HTTP mode。

本次真实验证为 PARTIAL：同一 BrowserSession 正常登录 AUTHENTICATED；1 次 `成都 川西 国庆 攻略` 搜索取得 20 个去重候选，search PASS。1 次 detail 消耗预算后返回 UNEXPECTED_PAGE，未解析正文，detail FAIL；用户确认正常图文页不能替代程序验收。路由别名校验不一致已作离线修复，但实因未确证、无真实复测，不能把该修复宣称为线上成功。CLI 正常 quit 关闭并保留 profile，G0 未通过，不进入 T05。实际状态见 [T04 Smoke 报告](../../reports/T04-xhs-read-smoke-test.md)。

T04 的网络指标来自自有被动 BrowserContext 事件，覆盖仅 `context_events_since_attach`，不是浏览器/操作系统所有流量。窗口外与晚到响应另行归属；total_bytes 为 null。用途分类为 DERIVED，官方文档/XHR/fetch 的 401/403/429 锁存限制信号；这些是本项目保守停止策略，不是 upstream 的平台额度或接口保证。

本次 SEARCH 为 173 个请求事件；DETAIL_1 的 86 个仅覆盖失败前窗口，非完整详情成本。TOTAL 725 个请求、主 frame 导航请求 5 个，字节数未测；默认评论相关请求 1 个是 DERIVED 分类。上述结果证明少量业务操作仍可触发较多页面请求，不证明低请求研究策略已经有效。

## 后续同步流程

1. 操作者显式选择新候选SHA，先与当前锁比较README及登录、browser/session、search/detail相关文件，不自动跟随main/latest。
2. 记录接口/页面结构差异；只把必要变更映射到本项目类型与未来受控页面读取，不merge完整Go服务。
3. 同步内部OpenAPI、来源/筛选/完整度语义、脱敏合成夹具、测试和本记录；核实没有引入写路由或反检测依赖。
4. 先跑全部离线门禁。真实连接另行明确授权；通过Fake测试不改变G0状态。
5. 若未来复制实现代码，新增逐文件来源、许可/NOTICE及实际改动记录；若发布构建，再记录真实平台、产物hash和签名状态。当前没有浏览器/sidecar发行产物，artifact_sha256为null、approved_for_release=false。

历史发现保留于 [PoC上游分析](xhs-poc-analysis.md)；机器记录见 [upstream-lock](../../contracts/upstream-lock.json)。
