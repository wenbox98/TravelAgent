# P06：采用版改选与可复现诊断验收

日期：2026-09-27。实际分支 `feature/g1-live-llm-validation`，起始 HEAD 为 `942eafb6fc7b0cd4361856504eff6744115acfe5`，开工时无未推送提交。实现提交 `535ad3222a669a0d3930e4fd7d8abaeb12559ca1`；本报告另行提交。G0 沿用历史，G1 保持 **NOT PASS**。

**本批改选闭环 PASS**：两个真实规划请求各返回一个合格提议，均从普通主页面完成预览、取消、再次预览同一提议和采用。重启后恢复一项非空采用版及此前两版历史；两条真实提议的本地回放通过。小红书、高德均为 0；模型 2/2，额度已用尽。本报告用 A/B 表示本机真实活动，不将私人研究关联、原始提议或源文提交 Git；实际名称和引用在原主页面保留。

## 1. 基线与数据保护

实际活动库沿用 `.local/p04-preview/preview.sqlite3`，schema 15；主页面仍为 8768。开始时采用版及草稿相同，修订为 19，无待保留的新用户改动。两项活动均未锁定预约，首项开始时间 10:00；公共交通、允许步行、往返自行安排和开发测试属性保持。当前约束未写成长期偏好。

开工先通过 SQLite backup 生成一致性备份，并保存旧代码与构建，位于忽略目录 `.local/p06-backup`。新构建放 `.local/p06-web`，原 P01–P05.2 静态目录保留。旧数据库备份仅供核对，不能覆盖当前库恢复旧额度。

结束逐表检查：其他五份历史数据库及旧静态资源摘要不变；活动库旧行全部保留（当前旅行状态和路线输入允许正常更新），原采用版在历史内完整保留。Evidence 仍为 **35**，历史审核、原失败任务和旧批次账本未改写。当前 5 条地点线索范围仍 UNKNOWN，其中 2 条身份是历史已检查；本批没有把地点线索变成 Evidence。

首次规划功能保持：原 P05.2 真实采用版被完整读取、用于第一次修改基准，随后进入采用历史；旧协议和首次规划回归仍通过。本批不重新请求首次规划，也不重新验证旧公交值。

## 2. 协议、固定条件与逐方案检查

新增显式协议 3：`RevisionResponse / RevisionProposal`，规则 `intent-revision-3.0`。模型仅返回已有活动 ID、日序、停留下界/上界、休息、引用 ID、受控修改理由代码。首项时间、交通、往返范围、截止和预约来自程序输入，不允许模型覆盖。

每个提议先检查严格结构，再复用原引用、范围、预约和截止检查，最后与发起时采用版比较修改意图。一个提议不合格不会丢掉独立合格提议；共享 URL/凭据污染仍整体阻断。没有新增自由解释字段：额外说明拒绝相关提议，说明隔离计数为 0，不将删除说明后的旧失败洗成新成功。

- LONGER_FIRST 锁定发起时首个活动 ID 和完整顺序，只允许该项停留两端同时增加。指定增量必须精确一致；未指定时允许 5–120 分钟建议。其他项目、日序与休息不能改变。
- FEWER 恰好删除一个未锁定项目；其余身份、相对顺序、时长与引用保留。首项 10:00 是时间约束，不自动锁定活动身份；一个剩余项目合法。只有一项或全锁定时不派发请求。
- 请求绑定输入摘要、`base_revision`、采用版本和目标。差异由程序计算；预览不会改采用版。取消后可重新预览同一已存提议，不再次生成。采用前重验版本、范围、来源、固定条件、意图和预览摘要；旧提议不能覆盖新采用版。
- 地图参考过期仍为未知，不使用历史约 21 分钟，不将未知交通当作零。人工数值修改仍可本地保存，不受模型额度耗尽影响。

域契约和 OpenAPI 随实现显式更新，增加 V3 提议及可选增量；104 个域定义、38 个 API operation。数据库 schema 15 未迁移。旧协议 1/2、旧模型输出和旧 FAILED 保持原义。

## 3. 自由文案反例与历史失败

已用合成文本复现“开放时间未知”“开放时间：未知”“尚未查询开放时间，请先确认”“开放时间未知，但门票免费”“不保证十点开放”“已核实十点开放”“无需包车，保持公共交通”以及改为自驾/包车的情况。

旧 V2 正则确实会拒绝“开放时间：未知”。P06 不继续增加关键词例外，而是让当前修改路径只接受结构与受控理由，由程序生成未知项和差异；纯结构式建议不再依赖模型自由说明通过。旧 V2 对该句的行为没有偷偷改判。

**不能推断历史两条真实失败就是这句话触发的。** P05.2 原响应缺失，具体触发句仍 UNKNOWN，原失败保留。本批两次真实请求均成功，没有真实失败需要复验，没有第三次请求。

## 4. 两次真实页面验收

请求均从正常 8768 页面进入同一生产 payload、耐久预留和 worker；未通过 Work 手写活动、数字或批准提议。只发送现有必要公共名称、来源提及与过滤条件，沿用每来源每次最多 6000 字；不含私址、地图响应、认证材料或隐藏推理。供应商和模型配置未变；120 秒等待、180 秒外层监督，无连通性测试、自动重试、提取或审稿。

| 本批请求 | 用途 | 生成 | 结构及意图合格 | 说明隔离 | 拒绝 | 当时可采用 | 结果 |
|---|---|---:|---:|---:|---:|---:|---|
| 1 | 第一项多玩一会儿 | 1 | 1 | 0 | 0 | 1 | COMPLETED，已实际采用 |
| 2 | 少安排一个项目 | 1 | 1 | 0 | 0 | 1 | COMPLETED，已实际采用 |

第一次真实差异：

| 项目 | 原采用版 | 模型提议及采用结果 |
|---|---|---|
| A 停留 | 45–75 分钟 | **75–105 分钟**，下界与上界各增加 30 |
| B 停留 | 45–75 分钟 | 45–75 分钟，不变 |
| 两项活动后休息 | 各 15 分钟 | 各 15 分钟，不变 |
| 顺序、日序、开始时间 | A → B；第 1 天；首项 10:00 | 全部不变 |
| 交通与往返 | 公共交通和步行；往返自行安排 | 不变 |

页面展示首项预计结束 11:15–11:45，后续抵达待交通核实。已点击预览、取消并确认原 45–75 分钟恢复，再预览同一保存结果并采用；过程中只有第一次生成调用模型。

第二次相对第一次已采用版：模型移除 A，保留 B，活动数 **2 → 1**。B 的 45–75 分钟与活动后休息 15 分钟未变。两项当时均无锁定预约，因此允许删除 A；时间锚点仍为 10:00。已预览、取消恢复两项及 A 的 75–105 分钟，再预览同一提议并采用。原交通和往返方式保持。

当前可读采用版是：**第 1 天，10:00 开始 B，建议停留 45–75 分钟，预计 10:45–11:15 结束，活动后休息 15 分钟，往返自行安排。** 这是模型提出、程序检查、页面采用的结果。首次增加 A 的版本保存在历史中，并非声称当前一项版仍含 A。

仍缺：地点范围、开放条件及实际可达性未核实；地点提及不等于作者亲历，停留和休息仍为 AI_PROPOSED；没有新的地图移动参考或节假日可行性保证。保留这些缺口，不能以改选成功认定 G1 通过。

## 5. 受限诊断与确定性本地回放

普通页面显示返回/解析状态、生成/合格/隔离/拒绝计数、具体字段路径、步骤、rule_id 和规则版本；原因区分引用、约束或无法判定。V3 没有自由展示文案通道，因此不存在需要采用的展示文案判定。不向主页面回显拒绝原句。

私人记录位于库旁 `planning-diagnostics`，只保留尺寸、类型和字段白名单内的结构提议，以及原 job 引用、输入/请求摘要、base_revision、协议/规则/模型配置摘要。原请求业务快照复用 `preview_jobs`，不重复保存源全文。敏感或未知字符串不能安全保存时，记录仅标不可回放；不保存完整 HTTP、headers、API Key、Cookie、token、真实地图或 reasoning_content。

默认 7 天有效，启动清理过期记录；独立清理仅作用于该目录，不删除 Evidence、源文、历史判定、采用版或预算。保留期只是工程默认。记录摘要绑定原任务；跨 scope、篡改、过期或已清理都不可回放。

验收分为两层：

1. 合成坏响应：可复现具体字段/规则，另存 `LOCAL_REVALIDATION` 版本；不更新旧判定、不自动采用。敏感 sentinel 不进入记录/日志，过期和独立清理通过。
2. 两条本批真实结构：使用正常 `diagnostic-replay` 命令，绑定实现 SHA `535ad3222a669a0d3930e4fd7d8abaeb12559ca1`，均重新得到生成 1 / 合格 1 / 拒绝 0。两次进程 DNS、socket、模型和高德计数均 0；回放前后数据库逐表摘要完全一致。原判定、当前采用版及账本不变。

不得从报告补造 P05.2 缺失响应。受限记录、实际任务 ID、内容引用和响应均未提交 Git。

## 6. 恢复、调用数和进程收尾

独立新进程禁止 DNS/socket 后读取同一数据库及 API，非空恢复 **1 项、2 个此前采用版本**；SOURCE_MENTION、AI_PROPOSED、引用定位、固定条件与开发测试属性保留。正常停止自有服务，再启动同入口，普通浏览器刷新确认当前一项版恢复，模型按钮显示本批已用完。原采用版保留历史，没有重派任务。

| 范围 | 实际计数 / 证据 |
|---|---|
| 项目模型 | **2**，账本两个耐久消耗与两个 worker 的 HTTP 计数一致 |
| 高德地点 / 路径 | **0 / 0**，本批账本无记录，进程 amap_http 为 0，出站角色限制阻止访问 |
| 小红书 connect / search / detail / browser | **0 / 0 / 0 / 0**，未启动 sidecar 或小红书浏览器，本批无许可/派发，入口出站限制 |
| 两个规划 worker | 各 model_http=1、external_dns=1、external_socket=1；blocked_external=0 |
| 首次及重启主服务 | 模型、高德、external_dns、external_socket 全为 0 |
| 两次本地诊断回放 | 模型、高德、external_dns、external_socket 全为 0 |
| 页面预览/取消/采用/刷新/重启 | 未增加任何项目外部账本记录；服务进程计数保持 0 |
| 全机器网络 / 浏览器非项目遥测 | NOT_MEASURED，不将项目进程计数冒充全机器抓包 |

Git 推送网络属于代码同步，不属于旅行项目模型/地图/小红书调用。项目实测合计 DNS=2、socket=2，均来自这两次模型请求。旧 P05/P05.1/P05.2 账本不变；新许可绑定原旅行与输入，2/2 已耗尽，不能重启、新旅行或新批次恢复。

本批两个 worker 均已退出，活动任务数 0。只保留本批主服务运行。无需用户再扫码、提供 Key 或补私址。

## 7. 离线回归与实际命令

最后代码修改后执行最终全量 Python：**1099 passed，77.90 秒，2 个既有依赖弃用提示**。并非只运行新增测试。新增改选集覆盖 30 个用例/参数情况：身份/顺序/数值、精确增量、一坏两好、额外说明与共享敏感污染、锁定/引用/范围、过期/篡改、取消晚返回、重复采用、人工修改及独立进程恢复。前端直接测试生产模板的数字差异、拒绝诊断、安全转义和预览状态。

| 实际命令 / 检查 | 结果 |
|---|---|
| `.venv\Scripts\python.exe -X utf8 -m pytest -q --tb=short -o cache_dir=.local/p06-pytest-cache` | 1099 passed |
| `.venv\Scripts\python.exe -m ruff check .` | All checks passed |
| `.venv\Scripts\python.exe -m mypy` | 80 个源文件，无错误 |
| `pnpm.cmd test`，在 apps/web | 5 组生产模板测试 PASS；既有 Vue SSR cssVars 提示 |
| `node node_modules/vue-tsc/bin/vue-tsc.js --noEmit`，在 apps/web | PASS |
| `node node_modules/vite/bin/vite.js build --outDir ../../.local/p06-web`，在 apps/web | PASS，39 modules |
| `.venv\Scripts\python.exe tools/validate_pack.py` | 12/12；104 域定义、180 引用、38 operations |
| `git diff --check` / 暂存区检查 | PASS |
| 历史库/资源及旧行保留检查 | PASS，35 Evidence 不变 |
| 两次正常 CLI 本地回放 | PASS，数据库不变，外部 0 |

开发中遇到并修复的检查问题：新增代码的格式/类型问题；合成过期用例的测试时钟与记录时钟不一致；提交扫描命中自编凭据 sentinel 的字面量，已改为测试时在内存生成并保留泄漏断言。最后全量覆盖以上修复。没有发现实际凭据或私人诊断进入提交。

本批未执行新的旅游资料研究、首次规划模型重跑、真实地图验证或 G1 重验；这些不能记为本批 PASS。

## 8. 修改文件与符号

| 文件 | 核心变更 |
|---|---|
| `planning/revisions.py` | `payload / _intent / differences / validate / safe_shape`：V3 输入、修改意图、独立检查及安全结构 |
| `planning/revision_diagnostics.py` | `retain / load / replay / cleanup`：受限记录、绑定、防篡改和版本化回放 |
| `planning/suggestions.py` | `payload_for / create_job / job_view / revision_binding / apply_proposal / run_worker`：派发、预览与 worker 路径 |
| `planning/flow.py` | `PlanningService.mutate` 的 save/cancel/adopt 路径、预览摘要与采用历史 |
| `planning/flow_models.py` | `RevisionProposal / RevisionResponse / PlanDraft.adjustment_minutes` |
| `planning/private_budget.py / discovery.py / network.py` | 追加绑定许可、既有来源复用、主入口仅允许规划 worker 出站模型 |
| `providers/llm.py` | `planning_revision_v3` 分派与结构响应契约 |
| `PlanningPanel.vue / RevisionReview.vue / planning-api.ts` | 修改选择、具体增量、计算差异、诊断与预览状态 |
| `scripts/product_preview.py` | 独立构建/审计目录、诊断命令及同入口正常启动/停止 |
| `contracts/domain.schema.json / contracts/openapi.yaml / tools/export_preview_contract.py` | 显式契约更新与导出 |
| `tests/integration/test_plan_revisions.py / apps/web/tests/revision-review.mjs / apps/web/package.json` | 生产路径回归和模板测试 |
| `README.md / docs/architecture/p06-plan-revision.md` | 当前入口、协议、预算、诊断与回滚边界 |

实现提交 diff 摘要：**21 files changed, 1258 insertions(+), 44 deletions(-)**。报告和文档校验产物另行提交。仅按明确列表暂存；三个既有未跟踪 T03 报告保留。提交前扫描通过：配置密钥、token 形状、实际 source ID、源文长行、私人活动名称、数据库/profile/原始返回及异常文件路径均无泄漏；推送前还扫描完整未推送提交范围。

## 9. 主页面与启动、清理

主页面：`http://127.0.0.1:8768/`。当前已经运行，直接使用原主页面即可。需要正常重启时，在自有服务终端正常停止后执行：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py --open
```

需要重新构建时（沿用已安装依赖，不覆盖历史静态目录）：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent\apps\web
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
node node_modules/vite/bin/vite.js build --outDir ../../.local/p06-web
Set-Location ..\..
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py --open
```

独立清理过期受限记录，不清预算或资料：

```powershell
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py diagnostic-clean
```

本批不需要用户补输入。剩余旅行事实缺口如上，后续是否核实应由新的明确任务决定。本批完成后停止，不新增研究、地图、酒店、报价或其他产品功能。
