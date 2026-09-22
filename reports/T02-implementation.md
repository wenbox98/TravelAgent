# T02 实现报告｜自有只读 sidecar 离线基础

状态：COMPLETED_OFFLINE。唯一可执行backend为Fake；没有真实普通Chrome启动器、Cookie/QR或真实小红书读取。没有实现TravelResearchService、RAG或完整旅行Agent，不进入T03。

## Git基础与范围

- 根目录：`E:/workSpace/travel-agent-project/travel-agent`。执行git rev-parse并检查父目录，确认不存在已有Git仓库后执行git init -b main。
- 基线提交：`11c5e66fcba889e13d76e90c0ae3ed849e7ccc58`，保留已审查文档与既有T00/T01源码，共102文件。基线不是本轮T02功能diff。
- 工作分支：`feature/xhs-readonly-sidecar`；没有已有remote，没有添加remote、创建远端仓库、push或PR。
- .gitignore补齐Cookie/session/token、profile/user-data-dir、原始页面/trace、数据库及WAL/SHM、日志和开发缓存；git check-ignore确认示例运行路径被忽略。仓库只包含合成夹具和合成sentinel，不包含真实登录材料。
- 本报告随T02完成提交保存；最终提交SHA以git log -1及用户交付消息为准，避免把报告自身的hash写入自身。

## 固定upstream与实现方式

`https://github.com/xpzouying/xiaohongshu-mcp`，SHA `8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff`。更新[锁文件](../contracts/upstream-lock.json)与[provenance](../docs/architecture/xhs-upstream-provenance.md)。

只参考筛选枚举、note ID/token关系、元信息和详情字段；复制源码0、修改upstream文件0、运行upstream二进制0。自有Python服务替代“导入完整服务再禁用工具”的路线，绝不声称兼容整个upstream二进制。未产生upstream patchset或发行产物，hash为null、approved_for_release=false。

## 修改文件与精确符号

| 文件/目录 | 实现或变化 |
|---|---|
| integrations/xhs-sidecar/xhs_sidecar/browser.py | BrowserOptions、BrowserBackend、FakeBrowserBackend、BrowserSession、BrowserManager.start/get_session/lease/close、SessionClosed |
| models.py（同目录） | 严格内部模型：SourceIdentity、AccessLocator、SearchFilters、SearchResult、RawDetail、DetailResult、NetworkSnapshot及本地状态/错误 |
| backend.py / service.py（同目录） | ReadonlyBackend、FakeXhsBackend、SidecarService；仅search/detail；内存handle、来源核对、关闭撤销，无研究编排 |
| completeness.py / observability.py（同目录） | classify_completeness、NetworkObserver、FakeNetworkObserver；保守文本范围判断与缺测/模拟计数 |
| redaction.py / app.py（同目录） | SensitiveDataRedactor、SafeAuditLog、SidecarConfig、create_app；源头日志允许字段、强制本机鉴权、仅注册只读路由 |
| __init__.py / __main__.py（同目录）、scripts/xhs_sidecar.py | 独立离线入口，固定loopback，无live开关、无浏览器下载或启动 |
| contracts/xhs-sidecar.openapi.json、tools/export_sidecar_contract.py | 新增内部API v0.1.0快照；导出/检查不启动server/browser、不联网 |
| tests/unit/test_sidecar_foundation.py | 普通配置、复用/并发/撤销、清理异常、完整度、网络模型、launcher约束 |
| tests/contract/test_xhs_sidecar.py | 筛选真假状态、身份与locator、严格输入、HTTP合成链路、来源不符/HTTP失败、快照一致性 |
| tests/security/test_sidecar_routes.py、test_sidecar_redaction.py | 所有写路径/MCP不存在；Host/Origin/Bearer；结构化、校验和异常日志的sentinel检查 |
| pyproject.toml、uv.lock | 精确依赖与测试路径；Pydantic 2.13.5、Ruff 0.16.8、Mypy 2.3.1；Ruff仓库规则和sidecar strict类型检查 |
| tools/validate_pack.py | 删除两个既有未使用变量/导入，以通过基础lint；校验逻辑未改变 |
| contracts/test-matrix.csv | 登记T02-01～T02-10，initial_status仍为历史NOT_RUN，实际结果在本报告 |
| README、integrations/xhs-sidecar/README、docs/03、07、12、14、15、两份PoC架构、provenance、原T02 task sheet | 同步当前离线范围、全部路由、来源、契约与验收；未创建重复任务单 |
| reports/document-validation.json/md | 本轮实际文档/契约校验输出 |

## BrowserManager

BrowserOptions仅engine=chrome/chromium与headless，禁止透传任意启动参数，没有stealth/指纹/代理/UA轮换能力。当前仅FakeBrowserBackend，调用start不启动操作系统进程。RLock使并发start复用同一个BrowserSession；get_session不自动启动；lease提供串行借用；close幂等并先撤销旧对象，即使清理失败旧对象也不可继续使用。Sidecar关闭时清除内存locator，旧handle不能继续detail。

这证明生命周期基础与Fake所有权，不证明真实Chrome进程清理或登录generation竞态已经实现。

## 全部路由与只读保证

| 方法 | 路径 |
|---|---|
| GET | /health |
| GET / POST / DELETE | /v1/browser/session |
| GET | /v1/login/status |
| POST | /v1/feeds/search |
| POST | /v1/feeds/detail |
| GET | /v1/metrics |

总计8个method/path组合、6个路径。health与本地状态不会启动浏览器；login/status是NOT_IMPLEMENTED且remote_checked=false。已注册接口要求loopback Host、允许的Origin、非空Bearer，禁止查询串；自动OpenAPI/docs路由关闭，契约仅离线导出。

代码不存在publish/comment/like/follow/private-message、MCP或任意工具代理。路径不存在时404、错误method为405；未授权访问已注册路径401。删除会话是本地资源清理，不是平台写操作。测试同时检查实际路由清单、无/有凭证写路径与MCP tools/call，未使用200+disabled或隐藏按钮。

## 敏感日志验收

SafeAuditLog在创建LogRecord前只保留固定事件、枚举标签和有界整数，未知结构化字段被排除。SensitiveDataRedactor另提供敏感字段递归替换、已登记secret值替换、URL和对象移除。没有把原始请求、错误字符串或traceback先写入再处理；uvicorn access/error原始日志在正式入口关闭。

测试注入`SECRET_XSEC_TOKEN_SHOULD_NEVER_APPEAR`和合成session secret，覆盖嵌套Cookie/Authorization/QR/session字段、不同字段里的已知值、非法请求、含token URL和backend RuntimeError。captured log中的sentinel出现次数为**0**，错误响应也不包含sentinel；并断言安全事件实际存在，排除“没有记录任何日志”的空通过。测试客户端httpx自身URL日志不属于服务输出，在捕获时设WARNING；断言覆盖捕获的全部服务日志。

## 完整度、身份与网络模型

- completeness允许FULL_TEXT/PARTIAL_TEXT/SUMMARY_ONLY/METADATA_ONLY。HTTP200且正文范围未验证为PARTIAL_TEXT；只有明确验证完整文本范围且无截断才FULL_TEXT。默认Fake详情为PARTIAL_TEXT，图片未读；来源ID不符或backend HTTP失败拒绝作为成功详情。
- SourceIdentity以provider+note_id计算稳定source_id；更换token不改变身份。AccessLocator仅内存、不可直接JSON序列化、token用SecretStr且repr不泄密、TTL为UNKNOWN；输出使用随机note_handle，不暴露定位材料，不生成Evidence claim。当前隔离边界是Fake session，真实账号scope留待T03。
- NetworkObserver区分browser_navigation和document/xhr_fetch/image/media/other；HTTP总量不包括导航计数。缺测为NOT_MEASURED且total_requests/total_bytes及类别为null；显式Fake计量窗口标SIMULATED。任何事件字节未知则total_bytes仍null，不能填0。尚未接入真实浏览器事件或声称完整网络覆盖。

## 契约与兼容性

新增独立内部OpenAPI v0.1.0，与实现快照比对。未修改T01业务domain.schema/openapi.yaml/SQLite语义，也未把Sidecar结果冒充FetchResult/Evidence。增加内部状态不表示现有业务API已开放。未实现HTTP网络adapter、预算许可、去重早停或旅行研究服务。

## 实际执行与结果

Windows，项目Python 3.14.7；所有pytest沿用拒绝DNS/TCP/UDP的autouse fixture，只有Windows asyncio内部socketpair例外。ASGI测试不监听TCP；CLI测试替换uvicorn.run，不实际启动服务器。

| 命令 | 状态 | 实际结果 |
|---|---|---|
| 新T02测试首次运行（实现前） | FAIL，预期 | 2个缺少xhs_sidecar模块的收集错误 |
| 初次全套沙箱测试 | FAIL | 76通过、2失败、8错误；pytest临时目录ACL导致8错误，caplog第二次set_level改变捕获阈值导致2失败 |
| 修复捕获级别、允许临时目录后 | PASS | 86通过；不改变禁止网络fixture |
| 最终 `python -m pytest tests -q --tb=short -p no:cacheprovider` | PASS | **92通过，0失败**；包含既有42项和本阶段50项；2个已有Starlette/httpx/anyio弃用警告 |
| `python -m ruff check .` | PASS | 全仓库Python基础lint通过 |
| `python -m mypy` | PASS | strict检查10个新增sidecar模块，无问题；不声称旧T00/T01代码已全量严格类型化 |
| `python tools/export_sidecar_contract.py --check` | PASS | 运行契约与快照一致 |
| `python tools/validate_pack.py` | PASS | **12/12**；17个JSON、96行设计用例、132个相对链接均通过 |
| `git diff --check` | PASS（提交前复核） | 无空白错误 |

首次mypy暴露Pydantic computed_field属性装饰器限制与APIRoute.methods可空类型；采用局部兼容注释和可空保护修复。首次lint使用环境继承规则；现已在项目显式固定基础E4/E7/E9/F规则，并移除校验工具两处未使用项。新增源码已格式化。未通过降低网络防护或隐藏失败测试取得PASS。

## 追踪映射

| ID | 测试证据 |
|---|---|
| T02-01 | test_T02_01_plain_browser_defaults、launcher约束 |
| T02-02 | test_T02_02_session_is_reused、concurrent_start |
| T02-03 | test_T02_03_closed_session_cannot_be_used、HTTP旧handle失效、close_failure |
| T02-04 | test_T02_04_write_routes_do_not_exist（14路径，有/无凭证） |
| T02-05 | test_T02_05_mcp_does_not_exist（4路径）及实际完整路由表 |
| T02-06 | test_T02_06_sentinels_absent_from_logs_and_errors、两项源头redaction异常测试 |
| T02-07 | test_T02_07_failed_filters_do_not_claim_applied（FAILED/UNKNOWN）与APPLIED/NOT_REQUESTED |
| T02-08 | test_T02_08_success_is_not_full_text（6组）与来源/HTTP失败用例 |
| T02-09 | test_T02_09_identity_is_stable_and_locator_is_private |
| T02-10 | test_T02_10_unmeasured_is_not_zero、合成分类/字节与非法零值用例 |

关联SEC01/02/03/04/07的当前服务范围通过；AUTH登录、真实RES08/09页面行为、研究XPOC与Windows发行门禁均未验证。

## 网络与尚未完成

开发工具阶段访问Python包索引，安装并精确锁定Ruff/Mypy及依赖；尝试读取PyPI工具元数据。Pydantic使用已安装缓存精确锁定。测试与服务执行没有访问小红书、扫码、真实search/detail、模型、地图或供应商；没有启动真实浏览器。自动测试不依赖互联网。

T03仍缺：真实普通Chrome/Chromium受控启动、应用专用profile与Cookie原子权限存储、正常官方QR/可见登录、账号识别/作用域、generation提交与取消竞态、事件/超时/重启恢复、真实验证/拒绝访问识别。后续真实页面解析与网络观测、TravelResearchService/预算/早停仍需相应阶段独立实现。

真实Chrome integration、登录/平台Smoke与发行构建：SKIPPED/BLOCKED。G0仍未通过，产品仍D0离线基础。**本阶段完成提交后停止，等待确认，不进入T03。**

## Git diff摘要

以下统计以main基线为比较点，包含本报告及契约生成文件；最终提交后可用git diff main..HEAD --stat复现。

<!-- T02_DIFF_STAT -->

```text
 .gitignore                                            |    7 +
 README.md                                             |    4 +
 contracts/test-matrix.csv                             |   12 +-
 contracts/upstream-lock.json                          |   63 +-
 contracts/xhs-sidecar.openapi.json                    | 1539 +++++++++++++++++++++++++++++++++++++
 docs/03-xhs-access-login.md                           |   10 +-
 docs/07-api-contracts.md                              |    4 +
 docs/12-task-plan.md                                  |    4 +-
 docs/14-sources.md                                    |   24 +-
 docs/15-release-acceptance.md                         |    2 +
 docs/architecture/xhs-poc-analysis.md                 |   18 +-
 docs/architecture/xhs-poc-design.md                   |   16 +-
 docs/architecture/xhs-upstream-provenance.md          |   33 +
 docs/tasks/T02-xhs-sidecar.md                         |   33 +-
 integrations/xhs-sidecar/README.md                    |   53 ++
 integrations/xhs-sidecar/xhs_sidecar/__init__.py      |    1 +
 integrations/xhs-sidecar/xhs_sidecar/__main__.py      |   44 ++
 integrations/xhs-sidecar/xhs_sidecar/app.py           |  161 ++++
 integrations/xhs-sidecar/xhs_sidecar/backend.py       |   58 ++
 integrations/xhs-sidecar/xhs_sidecar/browser.py       |  102 +++
 integrations/xhs-sidecar/xhs_sidecar/completeness.py  |   12 +
 integrations/xhs-sidecar/xhs_sidecar/models.py        |  199 +++++
 integrations/xhs-sidecar/xhs_sidecar/observability.py |   57 ++
 integrations/xhs-sidecar/xhs_sidecar/redaction.py     |   90 +++
 integrations/xhs-sidecar/xhs_sidecar/service.py       |  118 +++
 pyproject.toml                                        |   30 +-
 reports/T02-implementation.md                         |  164 ++++
 reports/document-validation.json                      |   12 +-
 reports/document-validation.md                        |   10 +-
 scripts/xhs_sidecar.py                                |   11 +
 tests/contract/test_xhs_sidecar.py                    |  136 ++++
 tests/security/test_sidecar_redaction.py              |   63 ++
 tests/security/test_sidecar_routes.py                 |   87 +++
 tests/unit/test_sidecar_foundation.py                 |  127 +++
 tools/export_sidecar_contract.py                      |   35 +
 tools/validate_pack.py                                |    2 -
 uv.lock                                               |  180 +++++
 37 files changed, 3443 insertions(+), 78 deletions(-)
```
