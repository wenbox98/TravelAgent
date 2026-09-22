# T04｜少请求精准研究调度

## 工程问题与本次目标
实现证据缺口、有限搜索、候选去重、多样性排序、逐篇读取、预算预留、账号串行、暂停和恢复。分开逻辑操作/导航/可观测HTTP计数。

## 前置与输入
前置任务：T03。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/04-research-efficiency.md](../../docs/04-research-efficiency.md)
- [docs/16-xhs-screening-spec.md](../../docs/16-xhs-screening-spec.md)
- [docs/03-xhs-access-login.md](../../docs/03-xhs-access-login.md)
- [config/defaults.json](../../config/defaults.json)
- [fixtures/research-pool.json](../../fixtures/research-pool.json)
- [fixtures/research-scenarios.json](../../fixtures/research-scenarios.json)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `apps/api/travel_agent/research/query_planner.py`
- `apps/api/travel_agent/research/ranker.py`
- `apps/api/travel_agent/research/scheduler.py`
- `apps/api/travel_agent/research/coverage.py`
- `apps/api/travel_agent/worker/`
- `tests/unit/test_research_budget.py`
- `tests/unit/test_relevance.py`
- `tests/integration/test_research.py`

## 关键实现位置/接口
QueryPlanner.plan、Ranker.select_next、BudgetLedger.reserve、CoverageTracker.evaluate、ResearchScheduler.run；session总预算跨job/revision不清零。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不为了达到数字拒绝展示真实缺口，不多Agent并发打开全文，不添加自动评论/视频读取。

## 验收证据
overview不超过3搜索6详情；重复note只读一次；挑战后0个后续新访问；同一任务重启预算不重置；没有网络观测数返回null。

用例 ID：RES01, RES02, RES03, RES04, RES05, RES06, RES07, RES10, QUAL01, QUAL02, QUAL03。应创建/更新的测试：
- `tests/unit/test_research_budget.py`
- `tests/unit/test_relevance.py`
- `tests/integration/test_research.py`

补充验收：实现第 16 章 SEL01～SEL12，覆盖未知条件、元信息不完整、重复/独立来源、正文完整度、日期、商业内容归属、停止语义与筛选审计。新增用例实现前保持 NOT_RUN；实现时同步测试矩阵、契约及夹具。

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T04-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。

## v1.1 PoC 必做
实现或等价覆盖 XPOC01～XPOC10：缓存 0 请求、3/6 上限、提前停止、source 去重、增量补搜、登录失效、verification 停止、SUMMARY_ONLY 边界、revision 防旧结果覆盖、预算耗尽。`TravelResearchService` 是上层唯一研究入口；LLM 不得自由拿到底层 search/detail。
