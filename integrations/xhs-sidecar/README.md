# XHS Readonly Sidecar｜T03 登录生命周期

这是 TravelAgent 自己控制的 Python 服务。upstream 只提供已锁定的设计/字段参考，没有复制、启动或代理完整 Go MCP Server。默认 `offline` 模式保留 T02 Fake；显式 `login` 模式使用普通 Chrome/Chromium，只实现登录生命周期。**启动服务不启动浏览器；经用户授权的本机真实登录、重启复用和断开清理已通过，见 [T03.8 验收报告](../../reports/T03.8-implementation.md)。**

## 实现边界

- BrowserManager.start/get_session/close 复用一个 BrowserSession；真实 Playwright sync API 由专用工作线程串行调用，没有任意启动参数、浏览器控制端点或反检测选项。
- GET login/status 只读取缓存，既不启动浏览器也不观察页面。offline 返回 NOT_IMPLEMENTED；login 模式仅 POST connect 允许启动和一次官方页导航。profile 存在只表示 SESSION_PRESENT_UNVERIFIED，不能把浏览器 ACTIVE 当成已登录。
- connect 并发/重复请求复用当前 flow_id、generation 和等待任务。登录等待只读当前页 DOM，不导航/刷新。过期 profile 保持 LOGIN_REQUIRED，首次登录进入 WAITING_USER，两者都继续观察，确认后 AUTHENTICATED；此后再次显式 connect 在同一 browser/page 核实，不导航。240 秒等待上限是应用限制，不是平台二维码 TTL。
- VERIFICATION_REQUIRED 暂停自动观察；用户手工处理后 POST resume 在同页继续。ERROR 后须显式 cancel/disconnect 清理，再决定是否重新 connect；不自动重试。稳定账号 ID 只留私有内存，API 仅报告 KNOWN/UNKNOWN，用户名不作为身份。
- cancel、disconnect、退出先使 generation 失效，再取消任务并关闭自有浏览器；旧结果不能写回 AUTHENTICATED。cancel/退出保留 profile，disconnect 关闭成功后清理，失败报告 ERROR。重启不联网，显式 connect 才核实旧会话。
- SourceIdentity由provider+note_id构成；AccessLocator是不可JSON序列化的内存对象，token使用SecretStr、TTL为UNKNOWN，按BrowserSession隔离。关闭时清理handle和定位材料。
- filter_requested/filter_applied/filter_status明确区分APPLIED、NOT_REQUESTED、FAILED、UNKNOWN；未确认条件不输出为applied。
- completeness由提取证据决定；默认合成正文为PARTIAL_TEXT，HTTP200不升级为FULL_TEXT。全文仅指验证后的文本范围，images_read始终false。
- NetworkObserver 区分导航与 document/xhr_fetch/image/media/other。真实 connect/login 缺测保持 NOT_MEASURED/null；Fake 事件为 SIMULATED。`login_status_external_requests=0` 单独描述 status 路径，不能推导整个浏览器零请求。页面自身可有后台请求，total_bytes 未知时为 null。
- SafeAuditLog在创建LogRecord前只接受固定事件、枚举标签和有界整数；结构化敏感字段不记录。SensitiveDataRedactor另提供递归字段替换、已登记secret值替换和URL/对象删除。不输出异常字符串、请求正文或完整URL；uvicorn访问/原始错误日志关闭。

## 完整路由表

所有已注册接口要求本机Host/Origin与非空Bearer凭证；查询串拒绝，自动API文档关闭。

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | /health | 当前模式健康状态，无浏览器启动/下载 |
| GET | /v1/browser/session | 本地会话状态 |
| POST | /v1/browser/session | offline 创建 Fake；login 返回 409 LOGIN_ONLY |
| DELETE | /v1/browser/session | offline 关闭/清 handle；login 等价 cancel，保留 profile |
| GET | /v1/login/status | 本地快照；不调用 browser/page/network |
| POST | /v1/login/connect | login 显式启动/复用一个流程，导航官方页一次 |
| POST | /v1/login/resume | 人工验证后在同页恢复观察，无新导航 |
| POST | /v1/login/cancel | 失效 generation、取消与关闭，保留 profile |
| POST | /v1/login/disconnect | 失效 generation、关闭后清专用 profile |
| POST | /v1/feeds/search | offline 合成候选；login 返回 409 LOGIN_ONLY |
| POST | /v1/feeds/detail | offline 合成内容；login 返回 409 LOGIN_ONLY |
| GET | /v1/metrics | 网络观测快照 |

只有上述 12 个 method/path 组合、10 个路径。publish/comment/like/follow/private-message、MCP/SSE/tools 代理不注册，直接 404/405。登录操作在 offline 模式返回 409 LOGIN_NOT_ENABLED；真实 mode 的禁止路径在浏览器调用前拒绝。登录操作返回的 HTTP 200 可能是 `LoginState.status=ERROR`，须检查状态和安全 error_code，不能只凭 HTTP 成功判定登录/注销成功。DELETE browser/session 的关闭失败则返回固定 500 错误。具体请求/响应见 [内部 OpenAPI](../../contracts/xhs-sidecar.openapi.json)，不声明兼容整个 upstream REST 或业务 API。

## 多信号登录识别与诊断

内部 API v0.3.0 增加安全的 LoginEvidence、observation_attempts 和 stop_reason。当前页官方 origin、路由分类、登录弹窗、登录按钮、账号入口、明确的用户 guest 状态、账号 ID 可用性、验证及访问限制分别采集；生产 classifier 优先 verification/限制，再处理登录/游客，证据不足为 UNKNOWN。T03.7 实测失效的 `.main-container .user .link-wrapper .channel` 不再阻断后面的用户状态读取。

严格 `guest=false` 可独立于账号 ID 确认认证；支持 `userInfo.value`、`userInfo._value` 及直接对象，冲突 guest=true 优先。当前实测的自我导航链接与同页稳定 ID 指向一致时可作为 fallback；旧入口只作诊断，单独缺少弹窗或出现 ID 不确认认证。账号身份无法可靠读取时保持 UNKNOWN，不额外访问主页或接口。真实信号和 Smoke 结果另以本轮报告为准，合成测试不代替线上验证。

同页观察默认间隔0.5秒，最多480次；连续 UNKNOWN 最多30秒，正常登录等待总计最多240秒。证据不足时为 ERROR/LOGIN_STATE_UNCERTAIN，stop_reason 为 OBSERVATION_TIMEOUT 或 OBSERVATION_LIMIT；登录总时限为 ERROR/LOGIN_TIMEOUT。失败不自动重开浏览器或刷新，须显式 cancel/disconnect 清理。CLI 显示布尔信号和固定分类，不显示账号、Cookie、二维码或原始 URL。GET status 仍只读本地快照。

## 浏览器配置与 profile

依赖精确锁定 `playwright==1.63.0`、`platformdirs==4.11.12`。标准 Playwright 自身的启动默认值保留；代码显式传给 `chromium.launch_persistent_context` 的配置为：

```text
user_data_dir = 应用核实归属的专用 browser-profile
headless = False
channel = "chrome"（默认）或 None（Playwright Chromium）
args = []
no_viewport = True
chromium_sandbox = True
timeout = 15000
```

没有 `ignore_default_args`、随机 UA、device 参数、proxy、stealth 插件、fingerprint 浏览器或用于隐藏自动化的脚本；不修改 `navigator.webdriver`，不使用 upstream CloakBrowser/headless_browser。`chromium_sandbox=True` 保留浏览器沙箱。`args=[]` 指应用不增加参数，并不声称 Playwright/Chrome 的完整进程命令行为空。launch 配置有离线替身核对，本机人工 smoke 使用相同的生产 Chromium 启动路径。

浏览器启动前拒绝可泄露协议内容的 DEBUG/PWDEBUG 等诊断环境设置及自定义 Node/远端 Selenium 注入路径，避免第三方调试输出绕过源头日志过滤；不输出原始驱动异常。准确允许边界以 `ordinary_browser.py` 中固定检查与离线测试为准。

默认选择本机已安装的普通 Chrome。`TRAVEL_XHS_BROWSER=chromium` 使用预先安装的 Playwright Chromium；服务不自动下载，缺少浏览器以受限错误报告。开发者可另行安装所需标准浏览器，不能把发行供应链/打包已完成作为当前能力。

通过 `platformdirs` 系统 API 取得本机应用数据目录，不硬编码用户名；Windows 默认为 `%LOCALAPPDATA%/TravelAgent/xhs/browser-profile`。`TRAVEL_XHS_PROFILE_ROOT` 仅开发/测试覆盖专用根目录，仍使用其固定 `browser-profile` 子目录，拒绝仓库路径、带 Git 祖先的目录和不安全链接/所有权；UNC 共享路径在 resolve/lstat 前拒绝，避免启动状态探测接触网络共享。`get_profile_path()` 只定位，`clear_profile()` 仅删核实归属的 profile；不读取日常 Chrome profile，也不要求用户提供该路径。

Cookie 与站点存储由浏览器原生持久 context 管理，不导出给用户、不提交 Git、不进入模型或日志，不声称应用已额外加密全部 profile。清理只删固定 profile 子目录，保留根目录所有权标记；关闭后删除最多尝试 3 次，间隔 0.1、0.2 秒，失败不能标 DISCONNECTED。取消/正常退出保留资料，重启只标待核实。

驱动工作等待有 20 秒上限；超时不代表底层浏览器已退出。关闭仍排在该线程已有操作之后，未确认关闭时保留 profile 并报告 ERROR，不以超时为理由删除数据或杀死其他浏览器。

## 离线运行与验证

用已有虚拟环境，独立入口为 `.venv/Scripts/python.exe scripts/xhs_sidecar.py`。启动前由调用进程在环境中设置随机的 `TRAVEL_XHS_SIDECAR_SECRET`（至少32字符），可设置 `TRAVEL_XHS_SIDECAR_PORT`，默认18061；host固定127.0.0.1。不要把凭证放入命令行、URL、Git或发给模型。未设置凭证时入口安全退出2，不开服务。

自动测试只通过ASGI TestClient与内存对象，不监听真实网络、不启动浏览器。公共测试fixture默认拒绝DNS/TCP/UDP外连，仅允许Windows asyncio内部socketpair。

```text
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe tools/export_sidecar_contract.py --check
.venv/Scripts/python.exe tools/validate_pack.py
git diff --check
```

mypy strict 覆盖 sidecar 模块，Ruff 覆盖仓库 Python 文件；旧 T00/T01 未补全的类型注解不在 strict 范围。契约快照用 export_sidecar_contract.py 显式生成并由测试比对，生成过程无服务器/浏览器/网络。依赖锁在根目录 uv.lock，安装完成后所有测试均离线。

## 人工登录 smoke 操作

以下是用户授权人工 smoke 的操作说明；2026-09-23 的实际结果见 T03.8 验收报告。准备好同一终端环境中的随机 `TRAVEL_XHS_SIDECAR_SECRET`，且两个终端继承同一秘密；不要把值写入命令、文档或截图。

本次使用预先安装的标准 Playwright Chromium，启动服务的环境设置 `TRAVEL_XHS_BROWSER=chromium`。若其他环境缺少浏览器，须先由开发者准备标准浏览器；服务本身不下载或升级浏览器。

```text
# 终端 A：选择 login mode 启动本地服务；本身不启动浏览器
.venv/Scripts/python.exe scripts/xhs_login.py serve
# 终端 B：只读本地状态，然后在获准后显式连接
.venv/Scripts/python.exe scripts/xhs_login.py status
.venv/Scripts/python.exe scripts/xhs_login.py connect
.venv/Scripts/python.exe scripts/xhs_login.py status
# 仅在用户手工完成官方验证后恢复当前页观察
.venv/Scripts/python.exe scripts/xhs_login.py resume
```

在官方可见窗口正常登录，不把二维码或账号材料发送给模型。确认后 Ctrl+C 关闭终端 A 的服务，再运行 serve/status：应先为 SESSION_PRESENT_UNVERIFIED；显式 connect 才核实复用。最后运行以下命令验证清理，并 status 确认 DISCONNECTED：

```text
.venv/Scripts/python.exe scripts/xhs_login.py disconnect
```

如只需取消并保留 profile，使用 `scripts/xhs_login.py cancel`。`TRAVEL_XHS_SIDECAR_MODE=login` 也可配合原始 sidecar 入口；缺省仍为 offline。mode 切换不代替真实测试授权，smoke 全程禁止搜索、feed detail 和平台写操作。

## 尚未实现

本次已验证该 Windows 环境的人工正常登录、会话复用与清理；页面未来变化及跨环境稳定性仍需后续验证，浏览器总体网络计量保持 NOT_MEASURED。真实 search/detail、筛选确认、研究预算/去重、RAG、GUI 与发行打包未实现。没有自动联网 integration test。来源许可、供应链与发行仍须独立门禁，T03 登录专项通过不代表 G0 整体通过。

参考与同步方式见 [upstream provenance](../../docs/architecture/xhs-upstream-provenance.md)，历史结果见 [T02 报告](../../reports/T02-implementation.md) 和 [T03 初次离线交付](../../reports/T03-implementation.md)；当前结果见 [T03.8 验收报告](../../reports/T03.8-implementation.md)。
