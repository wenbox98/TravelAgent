# T05｜证据抽取、权限与个人资料库

## 工程问题与本次目标
实现正文/元信息/选读图像分级，语义分块、中文预分词、向量模型隔离、FTS+向量融合、来源引用、删除传播。真实外部内容按策略决定用途。

## 前置与输入
前置任务：T04。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/05-data-rag.md](../../docs/05-data-rag.md)
- [docs/09-security-open-source.md](../../docs/09-security-open-source.md)
- [fixtures/policies.json](../../fixtures/policies.json)
- [prompts/extract-evidence.md](../../prompts/extract-evidence.md)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `apps/api/travel_agent/research/extractor.py`
- `apps/api/travel_agent/knowledge/`
- `apps/api/travel_agent/providers/embeddings.py`
- `apps/api/travel_agent/domain/permissions.py`
- `tests/unit/test_retention.py`
- `tests/integration/test_knowledge.py`

## 关键实现位置/接口
EvidenceExtractor、PolicyGate、KnowledgeIngestor、HybridRetriever、VectorIndex、RetentionService.delete_source；embedding失败显示降级。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不把用户点登录当全文保存许可，不共享真实小红书向量集，不批量OCR所有图片。

## 验收证据
仅元信息不生成正文事实；禁止保存内容不进DB/log/checkpoint；同源删除后检索不可见；不同dim拒绝混算；无模型时明确关键词降级。

用例 ID：RAG01, RAG02, RAG03, RAG04, RAG05, RAG06, QUAL04, QUAL05, SEC08。应创建/更新的测试：
- `tests/unit/test_retention.py`
- `tests/contract/test_evidence.py`
- `tests/integration/test_knowledge.py`

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T05-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。
