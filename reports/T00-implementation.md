# T00 实现报告

状态：COMPLETED_OFFLINE。2026-09-22，Windows / Python 3.14.7 / Node 22.23.2 / pnpm 11.24.0。

## 目标与前置检查

从纯设计包建立可启动的离线工程。已读启动清单、产品、架构与开发部署文档。目录不是 Git 仓库；未创建分支、提交、推送。没有已有业务代码。

## 文件与符号

| 文件 | 符号 | 职责 |
|---|---|---|
| apps/api/travel_agent/settings.py | Settings.load、RuntimePaths | mock 强制、loopback、路径边界、3/6 默认护栏 |
| apps/api/travel_agent/main.py | create_app、local_boundary | 无凭证健康检查、Host/Origin 校验、静态页面 |
| scripts/dev.py、scripts/doctor.py、scripts/check.py | main | 启动、环境检查、真实测试退出码 |
| scripts/_bootstrap.py | enter | 使用项目虚拟环境 |
| apps/launcher/main.py | main | 仅启动离线开发服务 |
| apps/web/src/App.vue、style.css | checkHealth | 常驻合成标识、健康检查、未配置能力说明 |
| pyproject.toml、uv.lock、apps/web/package.json、pnpm-lock.yaml | 依赖锁 | 真实解析版本，无虚构校验和 |
| tests/unit/test_settings.py、tests/security/test_runtime_paths.py、tests/contract/test_control.py | test_* | 默认配置、非法配置、路径边界、本地 HTTP |
| tools/validate_pack.py | check_json、check_links | 不再扫描虚拟环境/第三方依赖目录 |

## 实际执行

| 命令/项目 | 结果 | 说明 |
|---|---|---|
| git status --short --branch | SKIPPED | 目录不是仓库，无 diff --stat |
| 首次 python tools/validate_pack.py | FAIL | jsonschema 未安装 |
| python -m venv .venv | FAIL | ensurepip 失败；通过 uv 建立依赖环境 |
| 本地安装 uv；uv lock；uv sync --locked | PASS | uv 0.12.17，真实解析 41 个包 |
| 首次 pytest（实现前） | FAIL | travel_agent 尚不存在，符合最小失败测试预期 |
| pnpm build（TypeScript 7.0.2） | FAIL | vue-tsc 无法加载 lib/tsc |
| pnpm add -D --save-exact typescript@5；pnpm build | PASS | TypeScript 5.9.3，Vue 3.5.43，Vite 8.3.0 |
| python scripts/check.py --suite unit | PASS | T00 的 6 项配置测试 |
| python scripts/check.py --suite security | PASS | T00 的 2 项；沙箱临时目录失败后获准重跑 |
| python scripts/check.py --suite contract | PASS | T00 的 3 项控制面测试；修正 Windows asyncio socketpair 的测试隔离 |
| python scripts/doctor.py | PASS | 端口可用；浏览器检测到但未实测；DPAPI API 存在但未验证，凭证持久化禁用 |
| .venv/Scripts/python.exe tools/validate_pack.py | PASS | 修正依赖目录扫描后 12/12；仅 L0 |

## 契约与边界

业务 OpenAPI 尚未实现，未暴露未鉴权业务接口。控制面仅 GET /health 与静态页面，不含路径、凭证状态或用户资料。后续业务接口必须实现 07 章身份/CSRF 约束后开放。

依赖方法参考 [uv 锁与同步](https://docs.astral.sh/uv/concepts/projects/sync/)、[FastAPI 测试](https://fastapi.tiangolo.com/tutorial/testing/)、[Vite 环境要求](https://vite.dev/guide/)。兼容结论以本机实际构建/测试为准。

## 外部调用与未验证

开发时读取官方文档并从 PyPI/npm 安装依赖；小红书/模型/地图/报价访问均 0。离线测试拒绝网络连接，Windows 私有 socketpair 仅供事件循环内部唤醒。

SEC01 仅验证本地 API 范围，sidecar 属于后续任务；REL01 是 T11 干净 Windows 发行验收，SKIPPED，不能将本机源码启动记为该用例通过。浏览器交互 E2E、真实账号、上游构建、模型、价格与发行仍 SKIPPED/BLOCKED。

下一任务：[T01](../docs/tasks/T01-contracts-mocks.md)。本轮按 CODEX_START 继续 T01，然后停止。

T01 完成后实际启动检查：`python scripts/dev.py --mode mock` 成功监听 127.0.0.1:8765，GET /health 与 GET / 均 200，页面包含“合成演示”。最终完整测试计数见 T01 报告。本轮未运行浏览器交互测试。
