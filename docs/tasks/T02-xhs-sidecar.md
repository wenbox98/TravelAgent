# T02｜锁定和裁剪小红书只读sidecar

## 工程问题与本次目标
读取锁定上游的真实文件再写最小patch：REST只读白名单、禁用/mcp、loopback/鉴权、日志脱敏、取消、可观测请求、拒绝访问上报和有界重试。形成patch清单及构建产物hash。

## 前置与输入
前置任务：T01。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/03-xhs-access-login.md](../../docs/03-xhs-access-login.md)
- [docs/09-security-open-source.md](../../docs/09-security-open-source.md)
- [docs/14-sources.md](../../docs/14-sources.md)
- [contracts/upstream-lock.json](../../contracts/upstream-lock.json)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `integrations/xhs-sidecar/`
- `apps/launcher/supervisor.py`
- `apps/api/travel_agent/providers/xhs/adapter.py`
- `apps/api/travel_agent/providers/xhs/error_mapper.py`
- `tests/contract/test_xhs_mapping.py`
- `tests/security/test_sidecar_routes.py`

## 关键实现位置/接口
XhsReadonlyAdapter、SidecarSupervisor、UpstreamErrorMapper；对发布/评论/点赞等路径证明不可达；模型只见业务Protocol。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不新增签名破解、反检测、账号/代理轮换，不使用latest；不以仅隐藏按钮替代删除写路由。

## 验收证据
假sidecar契约通过；裁剪二进制可编译；未带token拒绝；非白名单路径不存在；trace不含敏感URL。构建不可用标BLOCKED。

用例 ID：SEC02, SEC03, SEC04, RES08, RES09。应创建/更新的测试：
- `tests/contract/test_xhs_mapping.py`
- `tests/security/test_sidecar_routes.py`
- `tests/security/test_redaction.py`

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T02-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。
