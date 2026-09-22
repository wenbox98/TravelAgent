# T09｜完整旅行工作台与可见失败

## 工程问题与本次目标
整合对话、粗略路线、地图、每日计划、预算、资料库、改选预览、来源完整性、SSE重连与设置；移动布局不意味着开放LAN。

## 前置与输入
前置任务：T08。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/08-ui-ux.md](../../docs/08-ui-ux.md)
- [docs/07-api-contracts.md](../../docs/07-api-contracts.md)
- [docs/01-product.md](../../docs/01-product.md)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `apps/web/src/views/`
- `apps/web/src/components/`
- `apps/web/src/stores/`
- `apps/web/src/api/`
- `apps/api/travel_agent/api/events.py`
- `apps/api/travel_agent/api/knowledge.py`
- `tests/e2e/`

## 关键实现位置/接口
TripWorkspace、ResearchProgress、PlanDiff、BudgetPanel、Knowledge、SseClient；所有前端状态由契约驱动。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不通过长文掩盖未实现页面，不把上游token放浏览器storage。

## 验收证据
无问卷阻塞；来源失败明显；预算未知项可见；改选先预览再确认；SSE重连不再抓一次；键盘可用。

用例 ID：UI01, UI02, UI03, UI04, PROD03, JOB05。应创建/更新的测试：
- `tests/e2e/test_login.spec.ts`
- `tests/e2e/test_overview.spec.ts`
- `tests/e2e/test_revision.spec.ts`
- `tests/e2e/test_degraded.spec.ts`

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T09-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。
