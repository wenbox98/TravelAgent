# T03 实现报告｜普通浏览器与持久登录生命周期

日期：2026-09-23。范围：在 T02 上实现普通浏览器、专用 profile、登录状态机与离线验收；真实浏览器/登录 smoke **NOT_RUN**，等待用户确认。不进入 T04。

## 基线与规模

开始时 `git status --porcelain` 为空；分支 `feature/xhs-readonly-sidecar`；HEAD 为 `ba3b4056b2ef586e0f50e0761eb20354a351d4ed`，提交对象存在。没有覆盖原有未提交修改。继续使用此分支，提交消息按用户要求为 `feat(xhs): implement persistent login lifecycle`；不 push。

复用 T02 的 BrowserManager、BrowserSession、Pydantic 内部契约、loopback 路由边界、SafeAuditLog、SensitiveDataRedactor 和 Fake 测试。只新增三个 sidecar 实现模块（profile、ordinary_browser、login）和一个 CLI，没有 GUI、研究调度或插件框架。BrowserManager 的小重构用于统一页面观察接口，并在关闭失败时保留已经撤销的资源以便清理重试；Playwright sync API 必须在同一个工作线程执行，不能直接交给 FastAPI 多个请求线程。

最终 diff stat 在本文末尾记录。

## 实现位置与契约

| 文件/符号 | 实际行为 |
|---|---|
| `integrations/xhs-sidecar/xhs_sidecar/browser.py`：BrowserManager、BrowserSession、AccountIdentity、LoginObservation | 一个专用会话；关闭失败仍撤销使用权并保留清理所有者；身份原值用 SecretStr 私有保存 |
| `profile.py`：ProfileStore.get_profile_path/exists/prepare/clear_profile | 系统应用数据目录；固定子目录和所有权标记；Git/日常浏览器/UNC/链接路径保护；最多3次删除 |
| `ordinary_browser.py`：launch_configuration、OrdinaryBrowserBackend、OrdinaryBrowserResource | 标准 Playwright 持久 context；所有驱动调用同线程；一次显式导航、只读当前页DOM；异常脱敏、有限等待 |
| `login.py`：LoginLifecycle.status/connect/resume/cancel/disconnect/shutdown、_apply_observation | 本地不可变状态快照、并发幂等、generation、显式恢复和退出语义 |
| `app.py`：create_app；`models.py`：LoginState、NetworkSnapshot、Health | 内部API升至0.2.0；新增四个登录POST；login模式禁止研究和旧浏览器启动入口 |
| `__main__.py`：configured_login/main；`scripts/xhs_login.py`：main | 默认offline；显式serve只启动本地服务；CLI固定loopback端点、拒绝代理及重定向、错误不打印原值 |
| `redaction.py`：SensitiveDataRedactor、SafeAuditLog | 增加会话数据/账号ID敏感字段，日志先白名单再创建LogRecord |

公开API共12个method/path、10条路径。GET login/status只读内存；POST login/connect、resume、cancel、disconnect都要求本机Host/Origin和专用Bearer。offline模式登录操作返回409 LOGIN_NOT_ENABLED；login模式search/detail及POST browser/session返回409 LOGIN_ONLY。DELETE browser/session在login模式走cancel，关闭失败500。登录POST的200代表返回状态，`status=ERROR`及error_code必须处理，不能当作成功退出。未扩展业务OpenAPI、Evidence或数据库语义；显式同步的是 `contracts/xhs-sidecar.openapi.json`。

## 普通浏览器配置与依据

锁定依赖：Playwright **1.63.0**、platformdirs **4.11.12**；Playwright直接运行依赖为pyee **13.0.1**、greenlet **3.5.6**，pyee使用已有typing-extensions。uv.lock记录解析版本和分发hash。没有stealth、undetected、CloakBrowser或上游Go浏览器依赖。没有自定义UA/device/proxy、修改navigator.webdriver、init script或ignore_default_args。

应用实际传给 `chromium.launch_persistent_context` 的完整kwargs：

```text
user_data_dir = ProfileStore.get_profile_path()
headless = False
channel = "chrome"（默认）或 None（预先安装的 Playwright Chromium）
no_viewport = True
chromium_sandbox = True
timeout = 15000
args = []
```

`args=[]`仅表示应用未增加命令行参数，不表示Playwright默认参数为空。静态检查已安装的Playwright 1.63.0 `driver/package/lib/coreBundle.js` 的 chromiumSwitches 和 Chromium._innerDefaultArgs（本机版本约34816、43317行）；headed persistent模式合成的参数如下，**不是实机启动采集**：

```text
--disable-field-trial-config
--disable-background-networking
--disable-background-timer-throttling
--disable-backgrounding-occluded-windows
--disable-back-forward-cache
--disable-breakpad
--disable-client-side-phishing-detection
--disable-component-extensions-with-background-pages
--disable-component-update
--no-default-browser-check
--disable-default-apps
--disable-dev-shm-usage
--disable-edgeupdater
--disable-extensions
--disable-features=AvoidUnnecessaryBeforeUnloadCheckSync,DestroyProfileOnBrowserClose,DialMediaRouteProvider,GlobalMediaControls,HttpsUpgrades,LensOverlay,MediaRouter,PaintHolding,ThirdPartyStoragePartitioning,BlockOriginHeaderModificationOnRedirect,Translate,AutoDeElevate,OptimizationHints,msForceBrowserSignIn,msEdgeUpdateLaunchServicesPreferredVersion
--enable-features=CDPScreenshotNewSurface
--allow-pre-commit-input
--disable-hang-monitor
--disable-ipc-flooding-protection
--disable-popup-blocking
--disable-prompt-on-repost
--disable-renderer-backgrounding
--disable-updater-scheduler
--force-color-profile=srgb
--metrics-recording-only
--no-first-run
--password-store=basic
--use-mock-keychain
--no-service-autorun
--export-tagged-pdf
--disable-search-engine-choice-screen
--unsafely-disable-devtools-self-xss-warnings
--edge-skip-compat-layer-relaunch
--disable-infobars
--disable-search-engine-choice-screen
--disable-sync
--enable-unsafe-swiftshader
--user-data-dir=<owned profile>
--remote-debugging-pipe
about:blank
```

保留库默认参数，没有新增规避检测功能；显式sandbox=True使库不增加`--no-sandbox`。库此版本并未添加`--enable-automation`，不能把“保留默认值”误写成声称存在此flag。拒绝DEBUG/PWDEBUG及自定义Node/远端Selenium等可能暴露协议或改变运行路径的环境覆盖。实际进程argv、浏览器版本兼容性、DOM和账号登录仍待人工smoke核验。

查阅依据：[Playwright persistent context文档](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context)、[官方浏览器渠道说明](https://playwright.dev/python/docs/browsers)、[platformdirs系统目录机制](https://platformdirs.readthedocs.io/en/latest/explanation.html)。实现按已安装锁定版本源码复核，不仅依据通用文档。

## Profile、状态与清理

默认 `platformdirs.user_data_path("TravelAgent", appauthor=False)/xhs/browser-profile`；Windows来自系统应用数据目录，通常为 `%LOCALAPPDATA%/TravelAgent/xhs/browser-profile`。不硬编码用户名。`TRAVEL_XHS_PROFILE_ROOT`开发/测试覆盖专用根目录，仍固定子目录browser-profile。构造/exists只读本地元数据；prepare首次建立标记，拒绝接管非空陌生目录。拒绝项目及其他Git祖先、日常Chrome路径片段、UNC、符号链接/Windows reparse祖先。clear_profile核实标记与解析后的父子关系，仅删固定子目录；根标记保留。所有测试只使用临时合成目录，没有删除真实profile。

状态包括DISCONNECTED、STARTING_BROWSER、SESSION_PRESENT_UNVERIFIED、CHECKING、LOGIN_REQUIRED、WAITING_USER、AUTHENTICATED、VERIFICATION_REQUIRED、CANCELLED、ERROR。offline仍NOT_IMPLEMENTED。有profile启动仅SESSION_PRESENT_UNVERIFIED，不启动浏览器、不验证Cookie。有效页面观察才AUTHENTICATED；失效旧profile保持LOGIN_REQUIRED，新流程等待为WAITING_USER。无法识别DOM保持CHECKING直到有限超时，不猜已登录；稳定账号ID无法可靠取得就UNKNOWN，不以昵称合并账号。

GET status不调用浏览器、页面或文件系统，仅锁内取快照。`login_status_external_requests=0`与未测得浏览器流量分开：connect期间导航和document/xhr_fetch/image/media/other/total仍NOT_MEASURED/null。当前页DOM观察本身不发请求，但网页后台请求未完整计量。

等待/启动中的重复与并发connect返回同一flow/generation，不新建任务。AUTH后显式connect可在同页重新检查过期；不导航、不另开浏览器。检测到额外验证则停止自动观察；connect不自动恢复，用户手工完成后resume观察原窗口。默认DOM间隔0.5秒、等待上限240秒，只是应用限值，不是平台阈值或二维码TTL。

取消/断开/退出先递增generation，再设置取消事件，等待worker退出并关闭自有session。观察提交在同一锁内比较generation；旧A即使在断开和B启动后晚到也不能改写B。正常退出/cancel保留profile，重启只标待核实；disconnect关闭成功后才删。Windows文件占用最多3次删除，间隔0.1/0.2秒，失败ERROR/CLEANUP_FAILED。worker等待上限35秒，驱动调用等待20秒；超时不证明原生任务已取消，保留所有者和profile，显式清理重试。

## 离线验证与发现

全部测试使用Fake或Playwright驱动替身，公共fixture拒绝DNS/TCP/UDP外连；无真实浏览器。T03-01～18映射：

| 验收 | 测试位置/重点 |
|---|---|
| T03-01、02 | test_ordinary_browser.py：launch kwargs、同线程、应用profile与拒绝外部目录 |
| T03-03～09 | test_login_lifecycle.py：启动未核实、100次status零操作、同会话、重复/8路并发、认证/过期 |
| T03-10～15 | 同上：验证暂停/同页resume、generation先失效、A晚到无效、关闭后删除、失败非成功、重启不联网 |
| T03-16 | test_login_redaction.py：全LogRecord、参数和异常元数据、响应中的六类sentinel为0 |
| T03-17、18 | test_login_lifecycle.py：反复观察只一次导航/启动、未知流量为null |
| 补充回归 | profile所有权/UNC/Git/reparse、有限清理、原生等待超时保留所有者、启动/CLI无隐式浏览器、禁止绕过登录入口 |

测试定位并修复两项问题：lifespan重复关闭同一个浏览器会把原始异常泄漏；验证终态刚发布而旧worker尚未退出时，立即resume可能丢失。另补AUTH后显式connect识别过期且不新增导航的回归。最终审阅增加官方HTTPS来源保护：驱动先检查URL，页面脚本在读取DOM前同步复核origin；手工跳到外域不能用相似DOM伪报AUTH，六个来源边界用例通过。

六类sentinel：SECRET_COOKIE_T03、SECRET_XSEC_T03、SECRET_SESSION_T03、SECRET_AUTHORIZATION_T03、SECRET_QR_CONTENT_T03、SECRET_ACCOUNT_ID_T03。覆盖正常认证以及start/navigation/observe/close/clear失败；全部捕获日志及异常元数据出现次数均为**0**，测试同时要求确实捕获到日志。不是仅检查最后格式化输出。

已执行 `uv add --bounds exact playwright platformdirs` 安装并锁定4个运行依赖；使用官方文档检索/PyPI下载。已读取本地固定upstream与安装库源码，未运行上游。本次对小红书、真实账号、搜索/detail的网络访问和浏览器启动均为0。常见Chrome二进制安装路径的只读检查未发现安装，不等于检查所有自定义位置；尚未下载Chromium。

最终门禁实际结果：

| 命令 | 实际结果 |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider` | PASS：154 passed，2 warnings，2.34s；包含全部unit/contract/integration/security |
| `.venv/Scripts/python.exe -m ruff check .` | PASS：All checks passed |
| `.venv/Scripts/python.exe -m mypy` | PASS：13个sidecar源文件strict通过 |
| `.venv/Scripts/python.exe tools/export_sidecar_contract.py --check` | PASS：OpenAPI与注册路由/模型快照一致 |
| `.venv/Scripts/python.exe tools/validate_pack.py` | PASS：12/12；17 JSON、114矩阵行、149相对链接；不代替应用/live测试 |
| `git diff --check` | PASS：退出0，无空白错误；Git提示部分现有换行策略转换 |

首次部分pytest在沙箱临时目录ACL处失败；授权扩展文件权限后复跑。扩展权限仅为运行离线测试，网络拒绝fixture保持启用。新增62个执行用例（浏览器/profile29、lifecycle/敏感日志27、启动/CLI6），加T02原有92项，共154 PASS、0 FAIL、0 SKIPPED。保留Starlette/httpx及anyio两条既有弃用warning，不掩盖成零warning。

文档同步：README.md、integrations/xhs-sidecar/README.md、docs/03-xhs-access-login.md、docs/07-api-contracts.md、docs/15-release-acceptance.md、docs/architecture/xhs-poc-analysis.md、docs/architecture/xhs-poc-design.md、docs/architecture/xhs-upstream-provenance.md、docs/tasks/T03-login.md。契约/配置同步：contracts/test-matrix.csv、contracts/xhs-sidecar.openapi.json、contracts/upstream-lock.json、pyproject.toml、uv.lock、.gitignore；tools/validate_pack.py更新报告范围文字，文档验证报告同步为本轮结果。没有新增重复设计文档。

## 人工阶段与风险

人工真实浏览器、扫码、重启session复用、disconnect实机：**NOT_RUN**（用户要求暂停）；GUI/E2E、真实研究/G0、Windows发行：未在本阶段执行。离线门槛不代表登录成功或平台兼容性已验证。

DOM来自静态参考，可能随平台变化；未知时保持CHECKING/ERROR而非伪造成功。浏览器/站点会话可能过期，profile保留不保证永久登录。当前没有完整真实请求observer，也没有验证拒绝页的全量覆盖。原生驱动永久挂起时，有限等待可返回ERROR并保留数据，但不能保证进程立即退出；没有实现按PID强杀，更不会杀用户其他浏览器。

下一阶段仅在用户确认后执行人工登录smoke，准备命令见[sidecar README](../integrations/xhs-sidecar/README.md)。若无普通Chrome，确认后可先安装标准Chromium并设置 `TRAVEL_XHS_BROWSER=chromium`。本次这些命令未执行：

```text
.venv/Scripts/python.exe -m playwright install chromium
.venv/Scripts/python.exe scripts/xhs_login.py serve
.venv/Scripts/python.exe scripts/xhs_login.py status
.venv/Scripts/python.exe scripts/xhs_login.py connect
```

serve/status不打开浏览器；只有获准后的connect访问官方页。用户登录后status确认，Ctrl+C关闭serve，重启serve/status应先待核实，再显式connect核实复用，最后disconnect/status清除。需要手工验证时仅resume同窗口。全程禁止搜索、详情、抓攻略或平台写操作。提交汇报后停止，不自行开始这些步骤。

## Git diff 摘要

基准为T02提交；下列为最终工作树的 `git diff HEAD --stat`。大部分新增行是明确要求的竞态/安全测试、生成的OpenAPI以及文档；未建立额外业务框架。完整提交SHA由提交后的汇报提供（避免提交内容中自引用SHA）。

```text
 .gitignore                                         |   2 +
 README.md                                          |  14 +-
 contracts/test-matrix.csv                          |  18 +
 contracts/upstream-lock.json                       |   7 +-
 contracts/xhs-sidecar.openapi.json                 | 559 ++++++++++++++++++++-
 docs/03-xhs-access-login.md                        |  70 ++-
 docs/07-api-contracts.md                           |  10 +-
 docs/15-release-acceptance.md                      |  10 +-
 docs/architecture/xhs-poc-analysis.md              |  20 +-
 docs/architecture/xhs-poc-design.md                |  60 ++-
 docs/architecture/xhs-upstream-provenance.md       |   8 +-
 docs/tasks/T03-login.md                            |  75 ++-
 integrations/xhs-sidecar/README.md                 |  88 +++-
 integrations/xhs-sidecar/xhs_sidecar/__main__.py   |  34 +-
 integrations/xhs-sidecar/xhs_sidecar/app.py        |  82 ++-
 integrations/xhs-sidecar/xhs_sidecar/browser.py    |  63 ++-
 integrations/xhs-sidecar/xhs_sidecar/login.py      | 231 +++++++++
 integrations/xhs-sidecar/xhs_sidecar/models.py     |  41 +-
 .../xhs-sidecar/xhs_sidecar/ordinary_browser.py    | 224 +++++++++
 integrations/xhs-sidecar/xhs_sidecar/profile.py    | 125 +++++
 integrations/xhs-sidecar/xhs_sidecar/redaction.py  |   5 +
 pyproject.toml                                     |   2 +
 reports/T03-implementation.md                      | 194 +++++++
 reports/document-validation.json                   |   8 +-
 reports/document-validation.md                     |  10 +-
 scripts/xhs_login.py                               |  63 +++
 tests/integration/test_login_lifecycle.py          | 436 ++++++++++++++++
 tests/security/test_login_redaction.py             | 130 +++++
 tests/security/test_sidecar_routes.py              |   4 +
 tests/unit/test_login_entrypoint.py                |  89 ++++
 tests/unit/test_ordinary_browser.py                | 380 ++++++++++++++
 tools/validate_pack.py                             |   2 +-
 uv.lock                                            |  71 +++
 33 files changed, 2964 insertions(+), 171 deletions(-)
```
