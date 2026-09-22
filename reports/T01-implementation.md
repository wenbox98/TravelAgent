# T01 实现报告

状态：COMPLETED_OFFLINE。范围仅 T00/T01；真实小红书仍关闭。

## 本轮目标与前置检查

已读 T00 报告、T01 指定输入、Schema/OpenAPI/SQLite 和全部启动清单。完成严格领域值、v1→v2 迁移、基础仓储和固定合成 mock；未实现 T02～T05 登录/研究调度/RAG。完整冲突记录见 [v1.1 契约审查](v1.1-contract-review.md)。

## 修改文件与实现位置

| 文件 | 类/函数 | 职责 |
|---|---|---|
| apps/api/travel_agent/domain/models.py | DomainModel、SourcePolicy、FetchResult、Trip、AuthSession、ResearchSession、EvidenceBundle、semantics | 直接执行 JSON Schema、保留 null、不做类型强转、不可变内部 JSON、来源和范围语义校验 |
| apps/api/travel_agent/persistence/database.py | Database.migrate、transaction、statements | 单次增量迁移、嵌套事务、外键、升级失败回滚、拒绝未知库/降级 |
| apps/api/travel_agent/persistence/repositories.py | TripRepository、OperationRepository、EvidenceRepository | 旅行创建/读取、操作幂等与状态迁移、权限/有效期/账号隔离后的结构化证据保存与读取 |
| apps/api/travel_agent/providers/xhs/protocol.py | XhsReadonlyAdapter | 内部只读接口；不暴露给模型 |
| apps/api/travel_agent/providers/mock/xhs.py | MockXhsReadonlyAdapter、metrics | 固定候选池、正文/摘要/元信息边界、错误注入、无 transport/线上回退 |
| apps/api/travel_agent/providers/mock/llm.py | LLMProvider、MockLLMProvider | 无密钥合成模型输出 |
| contracts/domain.schema.json、openapi.yaml、migrations/002_poc.sql | 严格契约/v2 SQL | Evidence 扩展、错误名称、ResearchSession、UNKNOWN 权限限制 |
| fixtures/evidence.json、fetch-result.json | 合成样例 | 与新增必需字段同步 |
| tests/contract、tests/integration/test_database.py、tests/unit/test_mock.py、tests/security/test_mock_network.py | test_* | 正负例、迁移/外键/回滚、幂等、权限到期、mock 错误和网络拒绝 |
| tests/conftest.py | deny_network、clock、fixture_data | 每测试隔离、固定时钟、拒绝 DNS/TCP/UDP；仅例外放行 asyncio 内部 socketpair |

## 契约变化

详见审查报告及 docs/07-api-contracts.md。领域 Schema 是单一校验来源，没有维护一份易漂移的宽松字段模型。OpenAPI 仍为未开放的业务设计契约，引用更新后的 Schema；控制面只有 T00 页面和 health。

SQLite v1 草案保留，v2 增加来源类型、目的地、适用条件、缺失字段、置信度与完整度写入限制。旧完整度仅明确转换，无法解释的值使整个升级回滚；未知来源类型保留 UNKNOWN。没有已有用户运行数据库被迁移。

## 实际执行

执行环境：Windows，Python 3.14.7，SQLite 3.50.4。详细最终结果见本报告的“最终验证”段。

| 阶段 | 命令/结果 |
|---|---|
| 实现前 | pytest 新增 T01 文件：FAIL（3 个缺少实现模块的收集错误，预期失败） |
| 实现后首轮 | `.venv/Scripts/python.exe -m pytest tests -q --tb=short`：PASS，39 项；2 个第三方弃用警告 |
| 精确版本锁 | `uv lock --offline`、`uv sync --locked --offline`：PASS，41 个解析包、40 个已安装依赖 |
| 实际启动 | `python scripts/dev.py --mode mock`：绑定 127.0.0.1:8765；本机 HTTP GET /health 返回 200 和仅存活 JSON；GET / 返回 200，包含合成标识与 CSP |

DATA01（严格契约）、DATA02（外键/回滚）、DATA03（重复迁移、保留数据升级和失败回滚）由上述测试覆盖。PLAN05 是 T07 预算计算用例，SKIPPED；本轮只验证未知金额不是零及范围约束，不冒称预算引擎完成。设计矩阵 initial_status 保留原始状态，当前结果在本报告中单独记录。

## 外部调用

小红书 search/detail/auth、真实模型、高德、报价均 0。mock 结果中的 search_ops/detail_ops 是合成逻辑操作计数，绝非真实站点访问。HTTP/page 观测不可用为 null，不把未测量写成 0。开发阶段读取官方文档、PyPI/npm 安装依赖；运行 smoke 仅请求 127.0.0.1。

## 风险与尚未验证

- PASS 仅证明离线基础契约与仓储，不证明研究质量、早停、预算预留调度、source 合并、登录恢复或 revision 防覆盖；XPOC/SEL 门禁留待 T04。
- EvidenceRepository 仅保存结构化派生证据，不实现原文/向量/FTS 索引写入、完整策略撤回传播、删除审计或策略感知备份；这些仍为 T05/T11 工作。迁移已使用原子事务，不做可能复制受限内容的整库备份。
- OperationRepository.reserve 只预留操作记录，尚不是可授权上游调用的预算 permit。当前无真实 adapter，T04 接入前必须实现共享预算与账号串行守卫。
- 20 个业务 HTTP 接口、真实模型 adapter、上游构建和登录 UI 尚未实现；真实集成 BLOCKED（本轮未启用），浏览器 E2E/干净 Windows 发行 SKIPPED。
- 安装的 Starlette 对 httpx 和 anyio 别名发出 2 个弃用警告，测试可执行且通过，后续升级应复验。
- MANIFEST.json 保留原始导入包清单，不代表当前源码校验和。没有 Git 仓库，无 git diff --stat；未初始化仓库、提交、push、merge 或创建 PR。

下一任务：[T02 小红书只读 sidecar](../docs/tasks/T02-xhs-sidecar.md)。按启动指令，本轮完成 T00/T01 后停止。

## 最终验证

以下是实际运行的最终结果，均以项目 `.venv` 执行，普通测试拒绝外部网络：

| 命令 | 退出码 | 状态 | 结果 |
|---|---:|---|---|
| python scripts/check.py --suite unit | 0 | PASS | 17 项 |
| python scripts/check.py --suite contract | 0 | PASS | 14 项；2 个第三方弃用警告 |
| python scripts/check.py --suite integration | 0 | PASS | 7 项 |
| python scripts/check.py --suite security | 0 | PASS | 4 项 |
| python scripts/check.py --suite e2e | 5 | SKIPPED | 尚无浏览器 E2E 实现，未作为通过 |
| .venv/Scripts/python.exe tools/validate_pack.py | 0 | PASS | 12/12；39 个领域定义、27 正例、5 负例 |
| .venv/Scripts/python.exe .local/startup_smoke.py | 0 | PASS | 两次实际启动：health=200、page=200、schema=2；第二次无重复迁移；只结束自身创建的进程 |

合计 42 项应用离线测试通过，最终失败 0；早期预期失败与依赖不兼容修复记录保留在 T00/T01 报告，不删除失败历史。启动入口现已在监听前执行 Database 的幂等迁移；数据目录为 `.local/runtime`，迁移失败会阻止启动。
