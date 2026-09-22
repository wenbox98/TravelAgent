# XHS Readonly Sidecar｜T02 离线基础

这是 TravelAgent 自己控制的 Python 服务。upstream 只提供已锁定的设计/字段参考，没有复制、启动或代理完整 Go MCP Server。当前唯一浏览器与读取 backend 为 Fake，没有真实 Chrome 启动器、登录、站点导航或网络客户端，不能用配置切换为 live。

## 实现边界

- BrowserManager.start/get_session/close 复用一个 BrowserSession；lease 串行借用，关闭即撤销旧对象。BrowserOptions 只有普通 chrome/chromium 与 headless，没有任意启动参数或反检测选项。
- GET 状态不会启动浏览器。search/detail 仅返回明确标识 is_synthetic/offline 的合成数据。login/status 返回 NOT_IMPLEMENTED、remote_checked=false，不能把浏览器ACTIVE当成已登录。
- SourceIdentity由provider+note_id构成；AccessLocator是不可JSON序列化的内存对象，token使用SecretStr、TTL为UNKNOWN，按BrowserSession隔离。关闭时清理handle和定位材料。
- filter_requested/filter_applied/filter_status明确区分APPLIED、NOT_REQUESTED、FAILED、UNKNOWN；未确认条件不输出为applied。
- completeness由提取证据决定；默认合成正文为PARTIAL_TEXT，HTTP200不升级为FULL_TEXT。全文仅指验证后的文本范围，images_read始终false。
- NetworkObserver区分导航与document/xhr_fetch/image/media/other。缺测NOT_MEASURED且计数null；Fake事件为SIMULATED，不能作真实平台访问指标。total_bytes未知时null。
- SafeAuditLog在创建LogRecord前只接受固定事件、枚举标签和有界整数；结构化敏感字段不记录。SensitiveDataRedactor另提供递归字段替换、已登记secret值替换和URL/对象删除。不输出异常字符串、请求正文或完整URL；uvicorn访问/原始错误日志关闭。

## 完整路由表

所有已注册接口要求本机Host/Origin与非空Bearer凭证；查询串拒绝，自动API文档关闭。

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | /health | 离线健康状态，无浏览器启动/下载 |
| GET | /v1/browser/session | 本地会话状态 |
| POST | /v1/browser/session | 幂等创建Fake普通浏览器会话 |
| DELETE | /v1/browser/session | 关闭并清理内存handle/token |
| GET | /v1/login/status | 本地未实现登录标记，不核实远端 |
| POST | /v1/feeds/search | 合成候选与明确筛选状态 |
| POST | /v1/feeds/detail | 内部handle定位的合成内容与完整度 |
| GET | /v1/metrics | 网络观测快照 |

只有上述8个method/path组合，6个路径。publish/comment/like/follow/private-message、MCP/SSE/tools代理不注册，直接404/405；不是返回200+disabled。DELETE关闭的是本应用资源，不是平台写操作。具体请求/响应见 [内部OpenAPI](../../contracts/xhs-sidecar.openapi.json)。这不是对upstream REST或现有业务API的整体兼容声明。

## 离线运行与验证

用已有虚拟环境，独立入口为 `.venv/Scripts/python.exe scripts/xhs_sidecar.py`。启动前由调用进程在环境中设置随机的 `TRAVEL_XHS_SIDECAR_SECRET`（至少32字符），可设置 `TRAVEL_XHS_SIDECAR_PORT`，默认18061；host固定127.0.0.1。不要把凭证放入命令行、URL、Git或发给模型。未设置凭证时入口安全退出2，不开服务。

自动测试只通过ASGI TestClient与内存对象，不监听真实网络、不启动浏览器。公共测试fixture默认拒绝DNS/TCP/UDP外连，仅允许Windows asyncio内部socketpair。

```text
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe tools/export_sidecar_contract.py --check
.venv/Scripts/python.exe tools/validate_pack.py
git diff --check
```

mypy strict覆盖本阶段10个sidecar模块，Ruff覆盖仓库Python文件；旧T00/T01未补全的类型注解不在本次strict范围。契约快照用export_sidecar_contract.py显式生成并由测试比对，生成过程无服务器/浏览器/网络。开发依赖锁在根目录uv.lock，安装完成后所有测试均离线。

## 尚未实现

真实普通Chrome/Chromium启动器、专用profile/Cookie原子存储、账号scope、官方二维码、登录事件与generation竞态、真实页面解析/筛选确认/网络观测、研究预算和去重调度均不属于当前可运行能力。T03/T04需另行确认，当前不提供integration test自动访问真实站点。来源许可与发行许可仍需门禁。

参考与同步方式见 [upstream provenance](../../docs/architecture/xhs-upstream-provenance.md)，实际结果见 [T02报告](../../reports/T02-implementation.md)。
