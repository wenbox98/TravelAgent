# T10｜系统测试、质量评测与小规模实测

## 工程问题与本次目标
执行完整测试矩阵与离线对照；修复明确缺陷。经操作人显式开启后在本机进行小规模真实研究/登录/高德流程；所有未跑项保持未验证。

## 前置与输入
前置任务：T09。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/10-test-strategy.md](../../docs/10-test-strategy.md)
- [docs/15-release-acceptance.md](../../docs/15-release-acceptance.md)
- [contracts/test-matrix.csv](../../contracts/test-matrix.csv)
- [docs/13-design-review.md](../../docs/13-design-review.md)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `tests/`
- `scripts/check.py`
- `scripts/evaluate.py`
- `reports/`
- `apps/api/travel_agent/`
- `apps/web/src/`
- `integrations/xhs-sidecar/`

## 关键实现位置/接口
EvaluationReport、NetworkCallCounters、GateEvaluator；测试报告逐个链接用例和实际命令；网站不做压力测试。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不以强行放宽预算、关闭鉴权/校验来修测试；没有真实环境不能宣称集成已通过。

## 验收证据
P0安全/硬约束零失败；真实账号门禁有脱敏证据；离线质量/节省率独立报告；不把SKIPPED计入PASS。

用例 ID：QUAL08, JOB06, SEC05, SEC06, SEC07, REL02。应创建/更新的测试：
- `tests/unit/`
- `tests/contract/`
- `tests/integration/`
- `tests/security/`
- `tests/e2e/`

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T10-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。
