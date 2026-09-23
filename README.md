# TravelAgent｜开源旅行规划助手
## Codex 设计、开发与测试文档包 v1.1（小红书研究 PoC 强化版）

**编制日期：2026-09-22。交付状态：开发规格，不是已经开发完成的应用。**

目标：用户给出模糊旅行需求后，工具自动研究小红书等来源，先提供几个大致路线和停留时间，再通过带建议的对话确定交通、项目、住宿和预算。研究成果在权限允许的范围内进入个人资料库；修改选择后进行局部重算。

目标仓库是 `wenbox98/TravelAgent`，与 `devagent-lab` 学习仓库独立。项目许可证尚未确定，不在本次文档导入中代选。此压缩包是待导入材料，不表示已经写入远端仓库。

## 现在怎么交给 Codex

1. 将此包导入 `wenbox98/TravelAgent` 根目录。导入前先检查远端和本地内容，不覆盖已有文件；成功导入后，在 Codex 中选择该仓库即可读取文档，无需再下载聊天附件。
2. 在 Codex 中打开该目录，把 [CODEX_START.md](CODEX_START.md) 的启动指令整段发给它。
3. 首次完成 T00、T01 后逐个执行任务，不要求一次生成全部系统。每个任务的产物和验收见 [任务总表](docs/12-task-plan.md)。
4. 原包历史上只执行过文档校验；T00/T01 离线实现见 [T00 报告](reports/T00-implementation.md)、[T01 报告](reports/T01-implementation.md)。后续本机登录专项已由 [T03.8 报告](reports/T03.8-implementation.md) 验收；真实读取、访问成本和 Windows 发行安装不能据此视为通过，T04 当前状态见下文。

没有真实账号、Windows 或 API 凭证时，Codex 应完成离线可验证部分，准确记录阻塞项，不得把 mock 结果写成实测。

## 首版边界

**首版 v0.1：Windows x64 本地单用户；支持本地正常登录小红书、有限自动研究、粗略攻略、多轮选择、个人资料复用、明确标记状态的预算，以及高德地图接入。**

发布包的体验目标是解压/安装后启动应用，点“连接小红书”，在官方页面或官方生成的二维码完成登录。不要求普通用户安装 Docker、Python、Go，或复制 Cookie。开发者构建可以使用开发工具。

首版不做云端托管多人账号、不承诺纯手机独立运行、不做无人值守验证码处理、不做账号/IP 轮换、不自动下单。真实票价必须有可用供应商才能显示为报价；未接通时标记未知，不构造“演示价”。

## 阅读导航

| 文档 | 解决什么问题 |
|---|---|
| [01 产品需求](docs/01-product.md) | 做成什么样、首轮怎么回答、哪些不做 |
| [02 总体架构](docs/02-architecture.md) | 模块边界、目录、进程和数据流 |
| [03 小红书接入与登录](docs/03-xhs-access-login.md) | 低操作成本登录、上游核实、只读适配、异常恢复 |
| [04 准确性与请求预算](docs/04-research-efficiency.md) | 先筛后读、去重、缺口搜索、计数与熔断 |
| [05 数据与 RAG](docs/05-data-rag.md) | 保存什么、权限、检索、时效与删除 |
| [06 Agent 与规划引擎](docs/06-agent-planning.md) | 多轮状态、修改、时间与预算计算 |
| [07 接口与领域契约](docs/07-api-contracts.md) | HTTP、事件、错误、并发和版本规则 |
| [08 页面与交互](docs/08-ui-ux.md) | 登录页、粗略攻略、取舍预览、资料库 |
| [09 安全与开源边界](docs/09-security-open-source.md) | 凭证、来源指令注入、数据用途、发布边界 |
| [10 测试设计](docs/10-test-strategy.md) | 离线、集成、人工实测、度量与门禁 |
| [11 开发部署运行手册](docs/11-dev-deploy.md) | 命令、配置、桌面打包、排错 |
| [12 开发任务总表](docs/12-task-plan.md) | 任务顺序和 Codex 每次改什么 |
| [13 设计质询](docs/13-design-review.md) | 十二项反例检查与调整 |
| [14 来源与事实状态](docs/14-sources.md) | 哪些已读源码、哪些待验证 |
| [15 发布验收](docs/15-release-acceptance.md) | 什么程度才能说“可用” |
| [16 小红书筛选实施细则](docs/16-xhs-screening-spec.md) | 未知值、正文验证、停止语义及筛选审计 |

`contracts/` 是机器可读的领域/API/数据库草案；`fixtures/` 全部是合成测试数据；`prompts/` 为 Agent 提示词规范；`docs/tasks/` 是具体施工单；`tools/validate_pack.py` 可校验本包；`00-阅读导航.html` 是目录导航，完整内容以 Markdown 与契约源文件为准。

## 三类文字的意义

- **用户要求/设计决策**：本项目应实现的行为，并非外部平台承诺。
- **源码或官方文档已核实**：带来源编号；仅证明所观察到的版本或文档内容，不等于线上成功。
- **待实测/设计目标**：必须用真实报告验证，不能当成已达到的指标。

所有测试中的地点代号、时间、票价、笔记和账号标识均为合成示例；“国庆成都去川西”只是需求输入样例，不包含真实旅行建议。

## v1.0.1 变更

补充第 16 章与 T04 的筛选验收，修正“连续两篇没有新信息”不等于研究完成的语义；加入 Git 忽略规则与文本换行规则。原 76 项应用测试继续保持 NOT_RUN；新增 SEL01～SEL12 为待实现测试设计。外部事实沿用原包来源记录，本次整理未重新运行真实平台验证。


## v1.1 变更

本版不推翻原产品设计，重点把“小红书攻略获取”收敛成可实施、可验收的 PoC：

- 首次连接通过本地正常网页会话完成，不要求普通用户复制 Cookie、开 DevTools 或配置 profile；会话失效时保留研究任务，重新连接后续跑。
- 不通过验证码破解、代理/IP/账号轮换、stealth/anti-detect 等方式规避平台安全机制；优化目标是**提高命中率与资料复用率，从源头减少无意义访问**。
- 研究改为 Evidence Gap 驱动：先查个人资料库，再少量搜索候选，先筛后读，逐篇更新缺口，证据足够即停止。
- PoC 默认护栏调整为每轮最多 3 次搜索、6 篇详情；它是应用成本上限，不是平台安全阈值。
- 统一正文完整度为 `FULL_TEXT / PARTIAL_TEXT / SUMMARY_ONLY / METADATA_ONLY`，避免标题或摘要被误报成“已阅读全文”。
- 新增 [XHS PoC 上游分析](docs/architecture/xhs-poc-analysis.md) 与 [XHS PoC 设计](docs/architecture/xhs-poc-design.md)。
- 第一阶段以 CLI 验证登录→搜索→筛选→精读→Evidence→SQLite 复用→增量补搜；Electron/完整工作台继续保留在后续阶段。
- 新增 XPOC01～XPOC10 验收设计：缓存 0 请求、预算上限、提前停止、去重、增量补搜、登录失效、验证暂停、摘要边界、revision 防覆盖、预算耗尽。

**上述 v1.1 变更说明是历史开发规格，不能单独作为实测证据；后续各阶段的真实状态以对应报告为准。**

## T02只读sidecar离线基础

T02 增加独立[只读 sidecar 基础](integrations/xhs-sidecar/README.md)：Fake 普通浏览器会话、路由白名单、源头日志脱敏、筛选/完整度/来源定位/网络模型。历史验证见 [T02 报告](reports/T02-implementation.md)，来源见 [provenance](docs/architecture/xhs-upstream-provenance.md)。没有复制或运行完整 upstream。

## T03 登录生命周期

在 T02 基础上新增标准 Playwright 普通 Chrome/Chromium、系统应用数据目录中的 TravelAgent 专用 profile，以及本地登录状态机。默认仍为 offline Fake；显式 login 模式启动服务也不打开浏览器，只有 connect 才启动可见官方窗口并导航一次。用户在官方窗口正常登录，无 Cookie 复制或二维码提取；等待复用同页，不反复刷新。

`GET /v1/login/status` 只读本地快照；profile 存在只标 SESSION_PRESENT_UNVERIFIED。generation 拒绝取消/断开后的晚到结果；cancel 和关闭保留 profile，disconnect 关闭后清理。验证要求暂停，手工处理后显式 resume 同页继续。login 模式拒绝 search/detail 和旧浏览器 POST 入口。

命令、launch 参数与 profile 边界见 [sidecar README](integrations/xhs-sidecar/README.md)。初次离线交付见 [T03 实现报告](reports/T03-implementation.md)；后续经用户授权完成登录识别修复、200 项离线测试及本机真实登录/重启复用/断开清理，执行证据见 [T03.8 验收报告](reports/T03.8-implementation.md)。**T03 登录专项已通过，最终提交为 `ccd329056794d3f29549ff0383f6236ce6373f36`。** 当时停止于 T03；本轮经用户新授权进入下面的 T04，G0 整体仍未通过。

## 历史 T04 首次读取 Smoke（PARTIAL）

T04 仅增加独立人工 CLI `.venv/Scripts/python.exe scripts/xhs_read_smoke.py --live`。启动不打开浏览器，输入 `connect` 后才用 T03 相同的普通 Chromium、专用 profile 和同一个 BrowserSession 正常登录。命令为 `connect/status/search/detail 0/detail 1/snapshot/quit`；`quit` 正常关闭并保留 profile。

一次固定搜索 `成都 川西 国庆 攻略`，最多两篇确定性选择的图文详情；第一篇足够技术验证时不读第二篇。不自动换词、翻页、滚动、展开评论、分析图片、下载视频或执行平台写操作，不实现完整研究服务、RAG 或最终攻略。预算在读取派发前记录，已有非零读取记录时拒绝通过重启重置预算。

输出和 Git 忽略目录中的 `.local/t04-smoke/summary.json` 仅保存匿名字段存在性、数量、完整度与网络统计。网络 scope 为 `context_events_since_attach`，保留窗口外流量和晚到响应，未知字节数为 null；业务 search/detail 次数与真实请求数分列。现有 sidecar HTTP 契约仍是 0.3.0 的 offline/login，`live_smoke` 仅是内部摘要类型。边界和命令见 [sidecar README](integrations/xhs-sidecar/README.md)，结果见 [T04 Smoke 报告](reports/T04-xhs-read-smoke-test.md)。

本次同一 BrowserSession 正常登录为 AUTHENTICATED，1 次上述搜索得到 20 个去重候选，搜索技术验证 PASS。1 次详情已消耗预算，但返回 UNEXPECTED_PAGE，未解析出正文；用户确认浏览器显示正常图文页，不能据此把自动 detail 判为成功。详情验证 FAIL，总体 PARTIAL；路由别名校验不一致仅完成离线修复，实际失败原因未确证，未进行真实复测。CLI 已正常退出并保留 profile。

搜索窗口观测 173 个 context 请求，详情失败前窗口为 86 个（不代表完整详情成本），TOTAL 为 725 个、主 frame 导航请求 5 个；字节数未测。默认评论相关请求有 1 个，分类为 DERIVED，不代表主动展开评论。G0 仍未通过，本轮停止，不进入 T05。

## T04.1 详情补验（有限技术 Smoke 通过）

[T04.1 报告](reports/T04.1-xhs-detail-smoke-test.md) 记录 423 项离线测试及真实补验：复用 profile，无需重新登录，使用 1 个 BrowserSession；旧 locator 仅在内存，因此使用另行授权的 1 次 fallback 搜索取得 20 个候选，再读取上一轮未访问的备用候选，本轮 detail 仅 1 次。入口为 `scripts/xhs_read_smoke.py --live --detail-smoke`，使用独立 `.local/t04.1-smoke/summary.json` 账本，未重置历史 T04 额度。

该详情 IDENTITY_MATCH、主响应 200，取得正文 672 字符、22 个非空行（计数 DERIVED），完整度 PARTIAL_TEXT：DOM 不完全一致，展开/截断状态未知；5 张图片未做 OCR。详情窗口 3.150135 秒观测 181 个请求，TOTAL 587，字节数未测；正常 quit 保留 profile，自有浏览器剩余 0。历史失败根因仅 LIKELY 与路由别名有关，原失败分支仍 UNKNOWN，不能确证。

T04 有限技术 Smoke 可以结束；这不自动通过 G0 完整发布门禁，也不进入 T05。下一步建议另行授权 T04.2 基线请求优化，当前未实施请求阻断。

## 离线开发启动（T00/T01）

使用 Python 3.14 和 Node 22.12+，先运行 `uv sync --locked`，再在 `apps/web` 运行 `pnpm install --frozen-lockfile` 和 `pnpm build`。返回项目根目录运行：

```text
python scripts/doctor.py
python scripts/dev.py --mode mock
```

打开 `http://127.0.0.1:8765` 查看合成演示；Ctrl+C 停止。此演示不提供研究聊天或 T03 登录 UI；登录使用上面的独立 sidecar CLI。

测试：`python scripts/check.py --suite unit|contract|integration|security`（分别执行，竖线表示选项）；`e2e` 暂无测试时返回 5/SKIPPED。文档检查使用 `.venv\Scripts\python.exe tools/validate_pack.py` 或激活虚拟环境后运行原命令。合成演示资料在 Git 忽略的 `.local/`；T03 真实 profile 位于仓库外系统应用数据目录。真实浏览器默认关闭，所有自动测试离线。
