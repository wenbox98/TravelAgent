# T07｜具体安排、预算与可逆修改

## 工程问题与本次目标
实现确定性时间/费用计算，软硬约束，改选proposal和确认，锁定项、依赖重算、取消原因与版本恢复。

## 前置与输入
前置任务：T06。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/06-agent-planning.md](../../docs/06-agent-planning.md)
- [fixtures/itinerary-case.json](../../fixtures/itinerary-case.json)
- [fixtures/budget-case.json](../../fixtures/budget-case.json)
- [prompts/revise-plan.md](../../prompts/revise-plan.md)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `apps/api/travel_agent/planning/feasibility.py`
- `apps/api/travel_agent/planning/budget.py`
- `apps/api/travel_agent/planning/diff.py`
- `apps/api/travel_agent/services/revision_service.py`
- `apps/api/travel_agent/services/trip_service.py`
- `tests/unit/test_feasibility.py`
- `tests/unit/test_budget.py`
- `tests/integration/test_revision.py`

## 关键实现位置/接口
evaluate_itinerary、calculate_budget、build_plan_diff、RevisionService.preview/confirm；unknown费用不能为0。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不先引入复杂求解器，不将有限搜索未找到说成绝对无解。

## 验收证据
AC510/ABCD760/ABD470分钟；预算240000～270000分；锁定不变；冲突解释可追算；旧结果不能覆盖新版本。

用例 ID：PLAN01, PLAN02, PLAN03, PLAN04, PLAN05, PLAN06, PLAN07, JOB01, JOB02, JOB04。应创建/更新的测试：
- `tests/unit/test_feasibility.py`
- `tests/unit/test_budget.py`
- `tests/integration/test_revision.py`

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T07-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。
