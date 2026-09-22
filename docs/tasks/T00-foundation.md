# T00｜工程骨架与真实依赖锁

## 工程问题与本次目标
建立独立项目、mock启动模式和本地目录；doctor检查Python/Node/浏览器/端口/secret-store能力；兼容版本要真实解析并锁定。先不装小红书登录数据。

## 前置与输入
前置任务：无。先查看对应 `reports/Txx-implementation.md`。前置真实环境门禁不足时可继续离线实现，但不得改变未验证状态。

必读文件：
- [README.md](../../README.md)
- [docs/01-product.md](../../docs/01-product.md)
- [docs/02-architecture.md](../../docs/02-architecture.md)
- [docs/11-dev-deploy.md](../../docs/11-dev-deploy.md)

## 允许创建或修改的目标路径
以下是计划中的源码位置，不代表已经存在；发现已有实现先复用，不覆盖。
- `apps/api/travel_agent/main.py`
- `apps/api/travel_agent/settings.py`
- `apps/launcher/`
- `apps/web/`
- `scripts/dev.py`
- `scripts/doctor.py`
- `scripts/check.py`
- `pyproject.toml`
- `uv.lock`
- `apps/web/package.json`
- `apps/web/pnpm-lock.yaml`
- `.gitignore`

## 关键实现位置/接口
create_app、Settings、RuntimePaths、doctor.main、dev.main；mock模式常驻合成提示；进程只绑定127.0.0.1。

## 执行步骤
1. 阅读输入、现有代码与前置报告，写一段“要解决的工程问题”和改动计划。
2. 先增加最小失败测试，再实现本任务范围；合成夹具使用 `fixtures/`。
3. 按外部网络默认关闭的原则运行测试；需要本机/账号的项目单独列出。
4. 检查契约与文档一致性；改契约时同步 Schema/API/夹具/测试，不偷偷换字段。
5. 写实现报告，列出实际函数、命令、结果、残余风险和下一任务。

## 禁止范围
不接真实网站、不设计多人账号、不引入Redis/Postgres，不创建全部业务空壳后宣称完成。

## 验收证据
mock页面与health能启动；没有secret也能运行；运行目录不落Git；不存在的服务明确未配置。

用例 ID：SEC01, REL01。应创建/更新的测试：
- `tests/unit/test_settings.py`
- `tests/security/test_runtime_paths.py`

## 命令要求
本包立即可执行：`python tools/validate_pack.py`。
本任务实现后执行 `python scripts/check.py --suite unit`，以及涉及的 contract/integration/security/e2e 套件；脚本要真正调用测试并透传退出码。不涉及的套件可注明未运行，不伪造输出。

## 完成报告
写入 `reports/T00-implementation.md`，使用 [报告模板](../../reports/TEMPLATE-implementation.md)。未经明确要求不 commit/push/publish。本轮结束后停止，让用户可检查结果。
