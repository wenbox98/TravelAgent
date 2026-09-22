# T03｜可恢复的用户登录闭环

## 工程问题与本次目标
完成连接→二维码/官方窗口→保存后核实→复用→过期恢复→断开。UI状态只查本地；idempotency和generation防双击及旧回调。建立最小设置页供真实用户扫码。

## 前置与输入
前置任务：T02。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/03-xhs-access-login.md](../../docs/03-xhs-access-login.md)
- [docs/07-api-contracts.md](../../docs/07-api-contracts.md)
- [docs/08-ui-ux.md](../../docs/08-ui-ux.md)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `apps/api/travel_agent/api/auth.py`
- `apps/api/travel_agent/services/auth_service.py`
- `apps/api/travel_agent/providers/xhs/session_broker.py`
- `apps/api/travel_agent/security/secret_store.py`
- `apps/web/src/components/XhsConnect.vue`
- `apps/web/src/views/Setup.vue`
- `tests/unit/test_auth_state.py`
- `tests/integration/test_login.py`
- `tests/e2e/test_login.spec.ts`

## 关键实现位置/接口
AuthService.start_session/get_local_status/disconnect、SessionBroker.on_cookie_saved、GenerationGuard；断开先停进程再清数据。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不采集密码/SMS，不读取其他浏览器profile，不声称零验证永久登录。

## 验收证据
UI轮询100次不新增上游status调用；双击只有一会话；保存失败不CONNECTED；注销晚到回调无效；正常路径不要求复制Cookie。真实扫码单列人工报告。

用例 ID：AUTH01, AUTH02, AUTH03, AUTH04, AUTH05, AUTH06, AUTH07, AUTH08, AUTH09。应创建/更新的测试：
- `tests/unit/test_auth_state.py`
- `tests/integration/test_login.py`

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T03-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。

## v1.1 PoC 必做
CLI 也必须提供“连接小红书”正常登录路径；普通用户不得手工复制 Cookie。任务在 NEED_LOGIN/ACTION_REQUIRED 时保存进度，恢复登录后继续，而不是重建整个研究任务。
