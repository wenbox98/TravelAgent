# T01｜领域契约、数据库与可重复mock

## 工程问题与本次目标
按契约实现严格领域模型、一次性迁移和repository接口；mock返回合成成功、认证、限流、部分数据等状态；每次测试独立临时目录与时钟。

## 前置与输入
前置任务：T00。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/05-data-rag.md](../../docs/05-data-rag.md)
- [docs/07-api-contracts.md](../../docs/07-api-contracts.md)
- [docs/10-test-strategy.md](../../docs/10-test-strategy.md)
- [contracts/domain.schema.json](../../contracts/domain.schema.json)
- [contracts/openapi.yaml](../../contracts/openapi.yaml)
- [contracts/database.sql](../../contracts/database.sql)
- [fixtures/research-pool.json](../../fixtures/research-pool.json)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `apps/api/travel_agent/domain/`
- `apps/api/travel_agent/persistence/`
- `apps/api/travel_agent/providers/xhs/protocol.py`
- `apps/api/travel_agent/providers/mock/`
- `tests/unit/`
- `tests/contract/`
- `tests/integration/test_database.py`

## 关键实现位置/接口
SourcePolicy、FetchResult、Trip、AuthSession、ResearchSession、OperationRepository；HTTP结果封装与内部领域分离；unknown不强制为0。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不从网上复制真实笔记做公共fixture；不得为过测试删除Schema限制。

## 验收证据
正例可解析；负例被拒绝；SQLite迁移/外键/回滚测试通过；mock无法悄悄访问互联网。

用例 ID：DATA01, DATA02, DATA03, PLAN05。应创建/更新的测试：
- `tests/contract/test_domain.py`
- `tests/contract/test_openapi.py`
- `tests/integration/test_database.py`

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T01-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。
