# TravelAgent｜开源旅行规划助手
## Codex 设计、开发与测试文档包 v1.1（小红书研究 PoC 强化版）

**编制日期：2026-09-22。交付状态：开发规格，不是已经开发完成的应用。**

目标：用户给出模糊旅行需求后，工具自动研究小红书等来源，先提供几个大致路线和停留时间，再通过带建议的对话确定交通、项目、住宿和预算。研究成果在权限允许的范围内进入个人资料库；修改选择后进行局部重算。

目标仓库是 `wenbox98/TravelAgent`，与 `devagent-lab` 学习仓库独立。项目许可证尚未确定，不在本次文档导入中代选。此压缩包是待导入材料，不表示已经写入远端仓库。

## 现在怎么交给 Codex

1. 将此包导入 `wenbox98/TravelAgent` 根目录。导入前先检查远端和本地内容，不覆盖已有文件；成功导入后，在 Codex 中选择该仓库即可读取文档，无需再下载聊天附件。
2. 在 Codex 中打开该目录，把 [CODEX_START.md](CODEX_START.md) 的启动指令整段发给它。
3. 首次完成 T00、T01 后逐个执行任务，不要求一次生成全部系统。每个任务的产物和验收见 [任务总表](docs/12-task-plan.md)。
4. 原包只执行过文档校验；当前 T00/T01 的离线实现与实际测试见 [T00 报告](reports/T00-implementation.md)、[T01 报告](reports/T01-implementation.md)。真实小红书登录、读取、调用量和 Windows 发行安装仍为 **NOT_RUN**，不能引用为已通过。

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

**v1.1 仍是开发规格包，不代表已经完成真实小红书登录或实测。**

## 离线开发启动（T00/T01）

使用 Python 3.14 和 Node 22.12+，先运行 `uv sync --locked`，再在 `apps/web` 运行 `pnpm install --frozen-lockfile` 和 `pnpm build`。返回项目根目录运行：

```text
python scripts/doctor.py
python scripts/dev.py --mode mock
```

打开 `http://127.0.0.1:8765` 查看合成演示；Ctrl+C 停止。本轮未实现研究聊天或真实登录。

测试：`python scripts/check.py --suite unit|contract|integration|security`（分别执行，竖线表示选项）；`e2e` 暂无测试时返回 5/SKIPPED。文档检查使用 `.venv\Scripts\python.exe tools/validate_pack.py` 或激活虚拟环境后运行原命令。运行资料在 Git 忽略的 `.local/`；真实 XHS 在代码和默认配置中关闭。
