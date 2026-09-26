# T06｜先粗略攻略后追问的Agent

P01 仅接通已审核缓存→草案→最多两项条件引导。没有完成新资料自动研究、普通入口 v3 或自动上下文审核；原任务未整体完成。见 [P01 范围](../architecture/p01-cached-preview.md)。

## 工程问题与本次目标
实现INTAKE到WAITING_CHOICE，unknown条件保留，提供有证据路线方向和至多两个带建议问题。工具与中断节点分离；模型输出Schema校验和有限修复。

## 前置与输入
前置任务：T05。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/01-product.md](../../docs/01-product.md)
- [docs/06-agent-planning.md](../../docs/06-agent-planning.md)
- [prompts/overview.md](../../prompts/overview.md)
- [prompts/extract-evidence.md](../../prompts/extract-evidence.md)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `apps/api/travel_agent/planning/graph.py`
- `apps/api/travel_agent/planning/nodes.py`
- `apps/api/travel_agent/providers/model.py`
- `apps/api/travel_agent/api/trips.py`
- `apps/web/src/components/RouteOptions.vue`
- `tests/unit/test_overview.py`
- `tests/integration/test_graph_resume.py`

## 关键实现位置/接口
build_graph、parse_intent、draft_overview、ask_next_choice；trace只存安全状态；unsupported model capabilities明确报告。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不把未配置供应商包装为已查询；不让模型直接运行上游MCP。

## 验收证据
只输入模糊需求也先产出草案；不默认预算/交通/人数；资料不足不凑三条；中断恢复不重复已完成付费调用。

用例 ID：PROD01, PROD02, PROD03, PROD04, QUAL06, QUAL07, JOB03。应创建/更新的测试：
- `tests/unit/test_overview.py`
- `tests/integration/test_graph_resume.py`

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T06-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。
