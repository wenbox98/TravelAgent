# T02｜自有只读 XHS sidecar 离线基础

## 工程问题与本次目标
用户接受设计审查后明确限定：创建本项目控制的普通浏览器生命周期与只读sidecar基础，upstream仅作reference。没有复制/运行完整upstream，不交付真实浏览器或Go二进制；无patchset/发行产物时hash保持null。来源见[provenance](../architecture/xhs-upstream-provenance.md)。

本阶段禁止真实小红书访问、扫码、真实search/detail、TravelResearchService、RAG与完整旅行Agent。只用Fake browser/reader，真实登录属于T03，不能因T02测试通过而继续。

## 前置与输入
前置任务：T01。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/03-xhs-access-login.md](../../docs/03-xhs-access-login.md)
- [docs/09-security-open-source.md](../../docs/09-security-open-source.md)
- [docs/14-sources.md](../../docs/14-sources.md)
- [contracts/upstream-lock.json](../../contracts/upstream-lock.json)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `integrations/xhs-sidecar/xhs_sidecar/`、`scripts/xhs_sidecar.py`
- `contracts/xhs-sidecar.openapi.json`、`tools/export_sidecar_contract.py`
- `contracts/upstream-lock.json`、`contracts/test-matrix.csv`
- `tests/unit/test_sidecar_foundation.py`、`tests/contract/test_xhs_sidecar.py`
- `tests/security/test_sidecar_routes.py`、`tests/security/test_sidecar_redaction.py`
- 相关架构、验收、来源与T02报告；不新增重复任务单。

## 关键实现位置/接口
BrowserManager/BrowserSession、FakeBrowserBackend、SidecarService、SensitiveDataRedactor/SafeAuditLog、SearchResult筛选状态、classify_completeness、SourceIdentity/AccessLocator、NetworkObserver。内部API独立于T01 FetchResult/Evidence契约，不实现研究调度或真实账号登录。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不新增签名破解、反检测、账号/代理轮换，不使用latest；不以仅隐藏按钮替代删除写路由。

## 验收证据
普通浏览器配置无反检测入口；会话可复用且关闭撤销；写路由/MCP不存在；凭证、Host/Origin校验；captured日志中sentinel为0；筛选失败不报告applied；HTTP200不直接FULL_TEXT；身份与token分离；未知网络计数NOT_MEASURED/null。所有测试禁止外网。

当前只有Fake backend，没有真实Chrome启动器、Cookie存储、QR或页面读取。真实浏览器/平台验收与发行构建为SKIPPED/BLOCKED，不属于本次离线完成标准。

主用例ID：T02-01～T02-10，关联SEC01～SEC04、SEC07。矩阵initial_status保留NOT_RUN作为设计历史，实际结果及pytest映射记录于T02报告。不将RES08/RES09真实页面行为或T03登录竞态标成通过。

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
最终执行全部离线 `python -m pytest tests -q -p no:cacheprovider`、`python -m ruff check .`、`python -m mypy`、`python tools/export_sidecar_contract.py --check`、文档validate与`git diff --check`。mypy strict覆盖新增sidecar模块，Ruff覆盖全仓库Python。无真实浏览器E2E，明确SKIPPED。

## 完成报告
写入 `reports/T02-implementation.md`，记录真实命令/结果、路由、模型、网络调用、差异、风险与T03缺项。用户本轮明确授权Git初始化、基线和完成提交；分支feature/xhs-readonly-sidecar，不添加remote、不push。完成提交后停止等待确认。
