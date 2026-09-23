# 03｜小红书数据接入与低操作成本登录

## 本章解决什么问题
让普通用户通过官方页面正常登录，并按需复用应用专用会话。T03 只实现登录生命周期，覆盖离线测试及经用户授权的本机人工登录验证；不执行搜索、详情或研究，不开发 Electron GUI。研究是后续独立阶段，登录不表示获得内容存储、推理或分享权限。

## 已核实的技术基线
2026-09-22 设计审查固定 `xpzouying/xiaohongshu-mcp` 提交 `8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff`。T02 仅参考接口/行为并自建离线 sidecar，没有复制或运行完整 upstream；T03 在同一基础上增加普通 Playwright 浏览器与持久 profile。2026-09-23 本机真实登录、重启复用及断开清理通过，详见 [T03.8 验收报告](../reports/T03.8-implementation.md)；这不等同于搜索/详情通道通过。上游锁定记录在 `contracts/upstream-lock.json`。[S02]

| 观察到的能力/行为 | 来源 | 对本项目的影响 |
|---|---|---|
| REST 有登录、搜索、详情，也有发布/评论等写接口 | routes.go [S03] | 必须裁剪，不能原样暴露 |
| 二维码接口返回图片和 timeout；后台保存扫码会话 | service.go [S04] | UI 可展示二维码，不能返回后立即杀浏览器 |
| 登录状态检查会创建浏览器并访问页面 | service.go [S04] | 前端每秒轮询绝不能直连上游 status |
| 登录会话有“同一时刻一个待扫码会话”的管理 | login_session.go [S05] | 本项目仍需请求幂等和注销竞态测试 |
| 详情需要 feed_id 和 xsec_token，load_all_comments 控制额外评论加载 | [S01][S06][S07] | token 只保留在受控会话内；明确不加载评论 |
| 搜索筛选有固定枚举，不提供本项目可假定的任意日期分页 API | search.go [S11] | 不编造游标、page_size、start_date 参数 |

历史 issue 有二维码会话与额外验证反馈；它们不是当前版本必现缺陷，也不是绕过验证的方法。用作回归案例，不当作今天仍未修复的结论。[S12][S13]

小红书官方账号开放文档本次读取失败。因此 **不沿用此前“某 scope 当前已开放/未开放”的未经本次复核结论**。正式 OAuth 能力记为 UNKNOWN；首版是本地第一方网页登录连接，不伪造 OAuth client_id 或 read_notes scope。[S14]

## 连接体验
T03 采用最小路径：显式 connect → 打开可见的普通 Chrome/Chromium 官方窗口 → 用户扫码或使用官方提供的正常登录方式 → 在同一页面观察登录结果。二维码由官方页面显示，不提取或转发到 CLI。用户无需复制 Cookie、打开 DevTools、导出 JSON 或配置日常浏览器 profile。

程序启动和本地 status 不打开浏览器；仅 connect 允许启动并加载官方页面。一个登录流程始终复用同一个 BrowserSession，等待期间只观察当前页 DOM，不反复导航、刷新或创建二维码页。页面自身仍可能产生网络请求，不能把 DOM 观察称为整个浏览器零流量。

账号密码、短信验证码和安全验证由用户直接在官方窗口处理，应用不收集。遇验证或访问限制暂停自动流程；用户处理后显式 resume，只继续观察当前页面。T03 不承诺远端无桌面登录或纯手机使用。

## 普通浏览器与专用 profile

使用标准 Playwright sync API，浏览器调用在专用工作线程串行执行；通过持久 context 交由浏览器管理 Cookie 与站点存储，不手工导出 Cookie 文件。默认选择已安装的普通 Chrome；Chromium 需由开发者预先安装，启动 sidecar 不自动下载浏览器。实际锁定版本和 launch 配置见 [sidecar README](../integrations/xhs-sidecar/README.md) 与 [T03 实现报告](../reports/T03-implementation.md)。

`platformdirs` 从系统应用数据目录定位 TravelAgent，默认在其 `xhs/browser-profile` 保存专用资料；Windows 对应本机应用数据目录下 `TravelAgent/xhs/browser-profile`，不硬编码用户名。`TRAVEL_XHS_PROFILE_ROOT` 仅供开发/测试覆盖专用根目录，profile 仍为其固定 `browser-profile` 子目录。根目录所有权标记和路径检查防止读取或删除日常 Chrome 数据；拒绝项目内路径、带 Git 祖先的目录、不安全链接及 UNC 共享路径，后者在文件系统探测前拒绝。`get_profile_path()` 只定位，`clear_profile()` 只清理核实归属的专用 profile。

profile 不进入 Git、模型或普通日志。**保存了 profile 与已验证登录有效是两种状态**；profile 目录、Cookie 文件存在及文件时间都不能证明会话有效。

## 状态机
```text
无 profile 启动 → DISCONNECTED
有 profile 启动 → SESSION_PRESENT_UNVERIFIED
显式 connect → STARTING_BROWSER → CHECKING
CHECKING → AUTHENTICATED（页面确认有效）
CHECKING → LOGIN_REQUIRED（已有 profile 但已失效）
CHECKING → WAITING_USER（首次登录、没有历史 profile）
LOGIN_REQUIRED / WAITING_USER → 同页观察 → AUTHENTICATED 或 VERIFICATION_REQUIRED
AUTHENTICATED → 显式 connect → 同页 CHECKING（不导航）
VERIFICATION_REQUIRED → 显式 resume → 当前页 CHECKING
取消 → CANCELLED；失败 → ERROR
断开且关闭/清理均成功 → DISCONNECTED
```

`AUTHENTICATED` 仅代表本次页面观察已确认登录，不保证后续永远有效。未知页面不得推断为已登录；无法可靠获取稳定账号 ID 时 `account_identity=UNKNOWN`，不以昵称作为唯一身份。可靠 ID 仅留本机私有内存，不出现在状态响应、日志或模型中。

`generation + flow_id` 标识当前登录流程。重复或并发 connect 返回同一活动流程，不新增 browser、page 或登录任务。取消、断开、关闭均先使旧 generation 失效；任何晚到观察结果须在同一同步边界核对 generation，失效结果不得改写登录状态或身份。

## 低请求的登录状态实现
T03.8 将同页证据提取与 classifier 分离。先验证官方 origin，再优先处理 verification/访问限制，其次处理登录弹窗、登录按钮或显式游客状态；只有已完成加载的 `/explore` 页面且反向信号均明确不存在，才考虑正向认证证据。正常页面 `userInfo.value`、`userInfo._value` 或直接对象中的严格 `guest=false` 是正向证据，账号 ID 缺失不阻止登录；guest=true 优先于旧认证快照。旧账号入口只作诊断，绝不作为读取用户状态的前置门槛。实测可见的自我导航链接（我/个人入口）与同页可靠 ID 指向一致时可以作 fallback，单独“无登录弹窗”、URL变化或 ID存在均不算成功。

每轮最多480次观察，连续 UNKNOWN 默认30秒后停止并返回 ERROR/LOGIN_STATE_UNCERTAIN；正常扫码等待有240秒总上限。时间和次数配置必须有限且为正，晚到认证结果不能越过截止时间。原生浏览器操作仍受20秒调用上限约束，不能保证硬件/驱动故障时精确到毫秒退出；自动流程不会无限 CHECKING。诊断只返回最后一组布尔信号、固定 URL 分类、观察次数和停止原因，不输出页面或账号原值。

1. `GET /v1/login/status` 只读取内存快照，不调用 BrowserManager、页面、Cookie 验证或网络；离线用例连续读取 100 次核对零导航、零外部操作。
2. `POST /v1/login/connect` 在启动前原子判定活动流程；显式创建一个浏览器、加载专用 profile、导航官方页一次，随后只读当前 DOM。
3. 有效会话进入 AUTHENTICATED；已有 profile 失效保持 LOGIN_REQUIRED，首次登录为 WAITING_USER，两者均在同一窗口继续观察正常登录。AUTHENTICATED 后再次显式 connect 只在当前 browser/page 核实，不导航。未知解析或浏览器错误不自动重试导航。
4. `POST /v1/login/resume` 用于人工完成验证后继续观察当前页，不刷新、不新建浏览器。普通 status、重启与后台定时器不会触发远端探活。
5. `login_status_external_requests=0` 是本地 status 路径的单独保证。真实 connect/login 的全浏览器请求量尚未可靠测量，保持 `NOT_MEASURED`，导航、document/xhr_fetch/image/media/other 和总量为 null，不填写假 0。

这些是 sidecar 内部接口；[07 章](07-api-contracts.md) 的业务 UI API 仍是后续适配设计，不能混称已开放。

## 注销与断开
“断开连接”指撤销本应用保存的本地登录状态，不宣称撤销平台所有会话或官方 OAuth token。

`POST /v1/login/disconnect`：先增加 generation → 撤销当前等待任务 → 关闭本应用拥有的 BrowserSession → 确认关闭成功后清除专用 profile 与私有身份 → 成功才报告 DISCONNECTED。旧任务无法在清理后重新写回 AUTHENTICATED；删除前确保浏览器不再持有 profile。

Windows 文件占用只允许有限次删除重试。浏览器关闭或 profile 清理失败保持明确 ERROR，不能谎报已退出；不杀用户其他 Chrome/Edge，不删除未核实归属的目录。`POST /v1/login/cancel` 仅取消、关闭并保留 profile，状态为 CANCELLED。

普通程序关闭同样撤销旧任务、关闭浏览器，但保留 profile。下一次启动只进入 SESSION_PRESENT_UNVERIFIED，不联网；用户显式 connect 后才核实并尽量复用。浏览器原生持久化替代原方案的独立 Cookie 文件写入，generation 保护本地结果，关闭后再删除防止旧浏览器继续写盘。

## 最小只读 sidecar
T02/T03 使用自有 Python sidecar，upstream 只作静态参考，不运行其浏览器、MCP 或服务。**不开放 /mcp**；不是注册写工具后仅在提示词禁止调用。

以下是历史 upstream 协议映射，当前自有内部 API 以 [sidecar 路由表](../integrations/xhs-sidecar/README.md) 为准；T03 login 模式拒绝 search/detail 与旧浏览器 POST 入口，不实现真实读取：
- GET /health（仅本机）
- GET /api/v1/login/status
- GET /api/v1/login/qrcode
- DELETE /api/v1/login/cookies（仅注销流程）
- POST /api/v1/feeds/search
- POST /api/v1/feeds/detail

其余接口不注册；除了受控断开连接，全部平台行为只读。不开放用户主页、推荐流、互动、发布及通用任意工具入口。

必须完成的 patch/包装要求：loopback 绑定；随机 token 且不经 URL/命令行泄露；删除未用写路由与 MCP；源头日志脱敏；一次导航失败不在多层分别重试；可取消；请求观测；验证码/拒绝访问结构化上报；不新增或启用规避检测功能。每项有具体静态/集成测试。不能只把“发布按钮隐藏”算作只读完成。

## 适配请求映射
本节是后续只读研究接入约束，T03 不执行或实现真实 search/detail。

搜索用 POST JSON；`keyword` 是字符串，`filters` 是单个对象。筛选按已读源码支持的枚举校验；首轮默认综合/图文，不因追求新而漏掉经典路线。最新排序仅用于补齐近期信息缺口。[S07][S11]

详情传 `feed_id`、`xsec_token`、`load_all_comments:false`。评论配置不是禁用评论的开关；尤其不能把 `max_comment_items:0` 理解为一定不加载。首屏自然包含的评论只丢弃、不继续展开。具体上游响应封装应按实测更新脱敏契约，不凭文档猜全文字段完整性。[S06][S07]

`xsec_token`：来自合法搜索结果的访问定位能力（平台TTL未知，应用只短期保留）；不猜测、不伪造、不跨账号复用。只存内存映射 `note_handle→provider_locator`，不进入数据库、RAG、日志、模型或分享链接。进程退出后失效；重新定位必须占用显式搜索预算，不能无上限重搜。

## 错误语义
不能把任何 500 统一解释为账号被封。准确识别 CHALLENGE、AUTH_REQUIRED、RATE_LIMITED、CONTENT_UNAVAILABLE、PARSE_ERROR、NETWORK_ERROR、UNSUPPORTED；不确定时返回受限错误信息，保留诊断代码，不夸大结论。

验证/限流：暂停该账号全部任务，保留已有安全结果；不自动换网络、账号、请求指纹或重复访问验证页。普通网络失败允许外层最多一次有限重试，失败请求也计费计数；上游内置重试必须计入导航指标或裁剪为一次。

## G0 实机门禁
T02～T04 在用户本机验证：首次连接、复用、重启、过期、人工验证暂停、注销、搜索→详情、评论不展开、日志无 token、真实请求计数可解释。

没有账号环境时这些是 BLOCKED，而不是“理论可行所以 PASS”。侧车成功返回 JSON，只能证明接口被调用，还必须确认内容完整度与来源对应关系。

## v1.1 PoC 登录收敛
PoC 对普通用户的唯一必要动作是点击“连接小红书”并在正常官方页面/二维码完成登录确认。开发环境可以先通过 CLI 启动这个流程，但 CLI 不得要求复制 Cookie、DevTools 导出、手工 profile 路径或把账号材料发给 Codex。

连接成功后复用本应用专用本地会话；失效时研究任务进入 `WAITING_AUTH/NEED_LOGIN`，保留已取得 Evidence 与预算账本，重新连接后从缺口继续。二维码刷新只在过期、取消或用户明确刷新时发生；前端/CLI 查询的是本地状态，不以轮询 UI 为理由重复访问站点。

“开源/个人使用”不是绕过平台规则的理由。v1.1 明确不实现 CAPTCHA 破解、代理池、IP/账号轮换、设备指纹伪装、stealth/anti-detect。遇到 verification/challenge、明确限流或拒绝访问立即暂停。

## T03 当前范围与停止点

默认 `offline` 模式继续使用 T02 Fake；显式 `TRAVEL_XHS_SIDECAR_MODE=login` 才选择真实普通浏览器 backend，即使选择该模式，启动也不打开浏览器。T03 只交付代码、契约和离线验证，实际结果见 [T03 实现报告](../reports/T03-implementation.md)。T03-01～T03-18 登记于测试矩阵，测试均使用合成页面/临时 profile，并禁止外部网络。

本轮不得访问真实小红书、打开登录页或扫码。离线门槛通过并完成提交后停止，等待用户再次确认；之后的人工 smoke 只验证登录、关闭/重启、显式复用与断开清理。真实搜索、详情、研究和 G0/G1 验收仍未通过，不进入 T04。
