# T08｜高德与可用报价适配

## 工程问题与本次目标
高德地点/入口/路线按真实文档映射，核实坐标系和许可；报价Provider先Protocol/UNSUPPORTED，凭真实接口资料与key实现，不猜接口。

## 前置与输入
前置任务：T07。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/07-api-contracts.md](../../docs/07-api-contracts.md)
- [docs/11-dev-deploy.md](../../docs/11-dev-deploy.md)
- [docs/14-sources.md](../../docs/14-sources.md)
- [docs/05-data-rag.md](../../docs/05-data-rag.md)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `apps/api/travel_agent/providers/amap.py`
- `apps/api/travel_agent/providers/quotes.py`
- `apps/api/travel_agent/providers/official_search.py`
- `apps/api/travel_agent/api/settings.py`
- `tests/contract/test_amap.py`
- `tests/contract/test_quotes.py`
- `tests/live/`

## 关键实现位置/接口
AmapAdapter.resolve_place/route、QuoteProvider.search、normalize_offer、CapabilityRegistry；票价业务状态与请求错误分离。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不爬取未经允许的票务页面，不让demo价格混入真实总账，不把地图默认写RAG。

## 验收证据
无key明确未配置；真实高德需人工或授权Live验证；同条件报价可比较；未开售/售罄/失败/未知分开；不得出现虚构报价。

用例 ID：MAP01, MAP02, MAP03, QUOTE01, QUOTE02, QUOTE03, QUOTE04。应创建/更新的测试：
- `tests/contract/test_amap.py`
- `tests/contract/test_quotes.py`
- `tests/unit/test_quote_normalization.py`

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T08-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。
