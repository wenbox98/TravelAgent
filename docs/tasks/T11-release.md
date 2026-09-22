# T11｜Windows发行包与开源发布准备

## 工程问题与本次目标
构建one-folder发行候选，验证干净Windows不需开发环境，检查依赖、上游patch、browser资源和签名状态。生成能力矩阵、卸载与数据清理说明。

## 前置与输入
前置任务：T10。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [docs/11-dev-deploy.md](../../docs/11-dev-deploy.md)
- [docs/09-security-open-source.md](../../docs/09-security-open-source.md)
- [docs/15-release-acceptance.md](../../docs/15-release-acceptance.md)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `apps/launcher/`
- `packaging/`
- `scripts/build_release.py`
- `SECURITY.md`
- `NOTICE`
- `docs/user-guide.md`
- `reports/release-acceptance.md`
- `.github/workflows/`

## 关键实现位置/接口
ReleaseManifest、startup doctor、supervised shutdown；hash和构建版本实际生成；LICENSE需项目拥有者选择。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不自动上传发布，不创建公开repo，不关闭Windows安全机制；Windows不可用则留候选和BLOCKED报告。

## 验收证据
解压/启动/配置/扫码/研究/退出流程有证据；无secret或真实资料；能力未接通如实标记；产物hash匹配。

用例 ID：REL01, REL02, REL03, REL04, RAG06。应创建/更新的测试：
- `tests/e2e/test_packaged_startup.py`
- `tests/security/test_release_contents.py`

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T11-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。
