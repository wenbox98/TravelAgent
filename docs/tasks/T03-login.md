# T03｜普通浏览器与持久登录生命周期

## 工程问题与本次目标
在 T02 已有 BrowserManager、只读 sidecar、脱敏与观测模型上，实现“一次正常登录，后续尽量复用本地会话；过期时才重新登录”。本阶段只交付最小登录生命周期和离线验证，真实登录 smoke 必须在提交并汇报后等待用户另行确认。

## 前置与输入
已确认干净的 `feature/xhs-readonly-sidecar`，T02 提交为 `ba3b4056b2ef586e0f50e0761eb20354a351d4ed`。沿用当前分支，不覆盖其他改动。先读 [AGENTS.md](../../AGENTS.md)、[T02 报告](../../reports/T02-implementation.md)。

必读文件：
- [03 登录](../03-xhs-access-login.md)、[07 契约](../07-api-contracts.md)、[08 交互](../08-ui-ux.md)。07/08 的完整业务 UI 是后续目标，不是本阶段实现要求。
- [PoC 上游分析](../architecture/xhs-poc-analysis.md)、[PoC 设计](../architecture/xhs-poc-design.md)。
- [sidecar 契约](../../contracts/xhs-sidecar.openapi.json)、[测试矩阵](../../contracts/test-matrix.csv)、[发布门禁](../15-release-acceptance.md)。

## 实现范围

复用 `integrations/xhs-sidecar/xhs_sidecar/`，小规模扩展普通浏览器 backend、profile 存储与登录服务；同步 CLI、离线测试、契约和现有文档，不预建 GUI/RAG/多账号/云同步框架。

1. 标准 Playwright Chrome/Chromium，可见官方窗口；披露锁定库与实际 launch 参数，无 stealth、指纹修改、随机 UA、代理或 upstream 指纹依赖。
2. 系统 appdata 下 TravelAgent 专用 `xhs/browser-profile`；支持开发/测试专用根目录覆盖。提供 `get_profile_path()`/`clear_profile()`，校验所有权、路径和链接边界，不读取日常 Chrome profile。测试只操作临时目录。
3. LoginState 包含 DISCONNECTED、STARTING_BROWSER、SESSION_PRESENT_UNVERIFIED、CHECKING、LOGIN_REQUIRED、WAITING_USER、AUTHENTICATED、VERIFICATION_REQUIRED、CANCELLED、ERROR。profile 存在不表示已认证。
4. GET `/v1/login/status` 只读本地快照；POST connect 才允许启动、加载 profile、导航一次。等待只观察同页 DOM，无后台远端探活或重复刷新。
5. 重复与并发 connect 原子复用同一流程。取消、断开、关闭先增加 generation；异步结果提交前核对，旧任务不能恢复身份或 AUTHENTICATED。
6. disconnect 先取消和关闭，再有限重试清除自有 profile；失败返回 ERROR。cancel 和正常关闭保留 profile，重启只标待核实。
7. 额外验证/访问限制暂停自动流程；用户手工完成后显式 resume，同页继续，不绕过、不重开。稳定账号 ID 不可靠则 UNKNOWN，可靠 ID 也只留私有本地内存。
8. 保留 T02 源头日志过滤和网络分类。`login_status_external_requests=0` 单独表示本地查询无外部操作；真实浏览器流量缺测保持 NOT_MEASURED/null。

## 禁止范围
本轮禁止真实站点访问、扫码、搜索、feed detail、真实攻略抓取和任何平台写操作。不做 TravelResearchService、RAG、CandidateSelector、Electron GUI、酒店/地图/交通，不进入 T04；禁止 CAPTCHA 绕过、stealth/fingerprint spoofing、代理/IP/账号轮换和自动解决 challenge。

## 离线验收

`T03-01`～`T03-18` 分别覆盖：普通 launch 配置、专用 profile、启动待核实、100 次本地 status 无外部操作、单 BrowserSession、重复/并发 connect、登录成功、会话失效、验证暂停、generation 失效、晚到结果拒绝、清理成功/失败、重启无网络、日志 sentinel、等待不重复启动及缺测不填 0。

sentinel 至少包含 `SECRET_COOKIE_T03`、`SECRET_XSEC_T03`、`SECRET_SESSION_T03`，并覆盖 authorization、二维码原始内容、session data、稳定账号 ID 与异常路径；捕获全部测试日志断言出现 0 次。矩阵的 `initial_status=NOT_RUN` 是设计登记，不代替实现报告中的真实执行结果。

## 命令要求
```text
.venv/Scripts/python.exe -m pytest tests -q --tb=short -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe tools/export_sidecar_contract.py --check
.venv/Scripts/python.exe tools/validate_pack.py
git diff --check
```

所有自动测试默认阻断 DNS/TCP/UDP 外连，浏览器 API 与观察器使用 Fake。离线集成测试不得借普通浏览器实现之名打开真实窗口或网站。

## 完成报告
写 [T03 实现报告](../../reports/T03-implementation.md)：实际文件/符号、契约变更、命令输出、PASS/FAIL/SKIPPED/BLOCKED、外部访问、限制及 diff。全部离线门槛通过后，按用户明确授权提交 `feat(xhs): implement persistent login lifecycle`，不 push、不发布。

汇报 commit、diff、浏览器库/参数、无 stealth 证据、profile 路径、状态机、status/generation/断开/重启/验证机制、测试与日志结果及待执行 smoke 命令。**到此停止。** 用户再次确认后的人工 smoke 仅验证打开普通浏览器→正常登录→关闭→重启待核实→显式复用→断开清理，仍禁止搜索与详情。
