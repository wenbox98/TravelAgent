# P09 建议攻略、食宿策略与旅行预算

本报告中的真实知识内容使用匿名代号；具体采用版及导出在忽略的私人目录 `.local/p09-audit`。不提交知识卡、原文、来源身份、数据库或私人导出。

## 范围与环境

基线 e3693db16f0fed2e848479c1bd8b87a9f3a485fa；功能分支 feature/g1-live-llm-validation，未合并master。沿用8768、P07许可、原schema16数据库。升级前SQLite一致性备份和旧静态构建位于 `.local/p09-backup`，不能覆盖活动库恢复额度。

普通新旅行默认ADVISORY，旧采用版按原DETAILED/LOCKED语义保留。新增建议、组合改选、食宿策略、费用和采用版Markdown；G1保持历史NOT PASS，向量NOT_IMPLEMENTED，供应商报价未接入。

## 代码与显式契约变更

- `advisory.py`：v4输入白名单、逐方案严格审核、有效候选池、组合预览、采用前引用重验。
- `guide_models.py` / `trip_budget.py`：扩展已有AmountRange/BudgetLine概念，整数分、每人/每天/间夜、可选项、套餐去重、已付与预算目标。
- `guide_view.py`：数据库投影、缺口、食宿策略、费用差异及安全导出。
- `flow`、`suggestions`、`workbench`、`revision_diagnostics`：复用原许可/任务/修订/七天诊断，不增加阶段预算常量。
- `AdvisoryGuide.vue` / `PlanningPanel.vue`：同入口建议模式，普通本地编辑不受模型余额限制；详细时间可选展开。
- domain/openapi同步，早期合成budget-case计数改ONCE×已展开quantity，金额和预期总数不变；没有转换真实历史报价或修改SQL存量表。

详见 `docs/architecture/advisory-guide-and-trip-budget.md`。

## 离线验证

最终代码修改后的全量回归 **1156 PASS，2条上游弃用提示，135.51秒**；Ruff通过，85个源文件mypy通过。前端8组SSR、vue-tsc和独立Vite构建通过。文档/契约校验全部通过。没有跳过失败测试或降低事实标准。

新增测试覆盖未知钟点/地图/休息非空建议、软偏好与硬截止、逐方案独立拒绝、AC→ABD取消/采用、晚到/取消/撤销许可、费用940–1380合成小计、未知人数、部分套餐、已付单计、禁止伪报价、知识清原文后输入、撤销知识阻止导出、独立进程零网络恢复、同源认证和可回放失败诊断。

## 两次真实模型验收：未通过完整采用闭环

请求A：一个P08地点线索卡，经普通页面新建独立测试旅行，一天/时间未定/交通未定/往返自行安排。发送前在禁止读取正文的上下文中验证v4输入：1活动、1最小引用、零地图值、首项为空；未加入完整原文或BodyBlock。

| 项目 | 请求A：真实知识卡 | 请求B：合成多日 |
|---|---|---|
| 输入性质 | 一张现有地点线索卡、一个来源 | 自编A/B/C/D、虚构东/西片区，2天1晚2人1间房 |
| 外部请求 | 1次DeepSeek | 1次DeepSeek |
| 原始返回 | 1个方案，原规则接纳1、拒绝0 | 1个方案，原规则接纳1、拒绝0 |
| 页面发现的问题 | 未选择步行被旧布尔默认值表达为禁止步行 | 预算条件将已明确的2人/1间房声称为未知 |
| 修复后本地复验 | 接纳0，PLANNING_UNSUPPORTED_FACT / walking_preference | 接纳0，GUIDE_BUDGET_CONTEXT_CONFLICT / budget_context.people |
| 模型方案最终采用 | 否；保留原知识卡草稿 | 否；取消模型预览，保留原合成输入 |
| 修复后新增模型请求 | 0 | 0 |

两次响应均正常返回结构，失败在产品输入/语义一致性，不能把“模型收到结果”写成可用建议通过。A将默认未选择步行改为null；B增加已知人数、房间、天晚口径不可被自由文案声称未知的检查。规则由advisory-guide-1.0/1.1推进到1.2。现有响应做本地复验，原记录不改写；A明确标为修正输入后的本地校验，B为原输入的新规则复验，不冒充新的模型审核。页面保留原校验历史，旧提议失效时禁用预览，采用路径重新校验。

原响应仍在私人七天诊断；A修正输入复验、B新规则复验存于 `.local/p09-audit`，无第三次请求、无连通性测试或重试。没有用Work填写停留/金额或手工批准响应来凑成功。

## 用户实际读到的采用版

**真实知识草稿（有限，非AI规划成功）**：一天，交通/首项钟点未定，往返自行安排；仅有地点线索K1，页面写“已发现地点，具体看点资料不足”，停留待选、休息自定。午餐给“在已选活动片区解决”的通用选择原则，一日住宿不适用。六类费用保留，其中往返自行安排、住宿不适用，其他未知；没有全程总价。具体公共名称在本机 `a-adopted-guide.md`，不提交Git。

**合成采用版（本地组合，不冒充AI）**：第1天合成A慢游、合成B手作，第2天合成D观景，时段/停留保持未知；每天午餐给片区用餐原则，住宿仍比较靠近活动/衔接次日/减少换酒店。已知2人、1晚、1间房保留，但没有合格金额，小计未知。模型曾在被取消的预览中提供90–150分钟停留和食宿策略；它的460–1280元部分草案有口径冲突，未采用、未作为报价或有效预算交付。

此处诚实保留缺口：本轮**没有取得最终可采用的真实AI建议**；不能将两个有内容的本地采用版称为AI闭环通过。

## 页面、计算、导出与恢复

- 普通页面创建独立旅行、显式包含测试卡、选择最小卡片、每旅行登记模型1次、其它0；旧P08采用版未覆盖。
- B模型预览已取消，恢复原AC；再执行AC→ABD预览，取消回AC，再次预览并采用ABD，旧采用历史保留。本地操作不需要剩余模型额度。
- 真实页面没有合格金额，费用差异保持未知，不把未知当0。离线生产路径使用明确合成模型响应验证940–1380四项小计；改ABD为1060–1500，差额120；这些是测试数值，不是此次真实模型的有效结果。
- A/B都从页面下载采用版Markdown。私人样例 `.local/p09-audit/a-adopted-guide.md`、`b-adopted-guide.md`，模型原始建议/输入与地图值不入导出。
- 正常停止并重启同一个8768；页面恢复A一个活动、B三个活动、食宿策略、六条预算明细、采用版本、引用和历史。独立进程阻断DNS/socket后，采用版、导出、指南和累计用量与重启前逐值一致；A导出与规划输入同时禁止读原文仍通过。
- 当前窄窗页面已视觉检查；没有重复的旧精确时间面板。许可关闭后，本地组合、导出和刷新可用；两份旧模型提议不能再直接预览采用。

## 调用与数据保护

| 测量 | 本批增量 |
|---|---:|
| 项目模型HTTP | 2 |
| 项目外部DNS / socket | 2 / 2 |
| 高德HTTP | 0 |
| 额外被阻断外部连接 | 0 |
| 新增账本MODEL操作 | 2（两个正常独立旅行各1） |
| XHS connect/search/detail/browser | 0/0/0/0 |
| embedding / 报价供应商 | 0/0 |

HTTP/DNS/socket来自既有操作审计计数，账本记录相互核对；不是全系统抓包，也不包括Git推送流量。XHS为本轮无派发、无对应新账本操作及无浏览器启动，未声称OS全流量检测。服务重启、状态/导出/页面恢复之后计数保持不变。两份本轮许可已关闭，旧用量未重置。

与本批开始的一致性备份逐行比较：6来源、35条Evidence、6正文、135正文块、89抽取候选、10提取尝试、5上下文审核、3重验记录、3知识卡、50旧操作、10旧许可、13旧旅行及13旧任务全部原样保留。仅新增2旅行、2许可、2模型操作和2任务；无存量正文清理，schema仍16，活动任务0。日志不打印正文、Key、token；私人响应、导出和审计均留忽略目录。提交范围另做真实Key/来源身份/正文片段扫描。

## 实际执行的检查命令

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check apps/api/travel_agent/planning apps/api/travel_agent/providers/llm.py tests/integration/test_advisory_guide.py
.venv\Scripts\python.exe -m mypy
.venv\Scripts\python.exe tools/export_preview_contract.py
.venv\Scripts\python.exe -X utf8 tools/validate_pack.py
npm.cmd test
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
node node_modules/vite/bin/vite.js build --outDir ../../.local/p09-web-release
.venv\Scripts\python.exe -X utf8 .local/p09-audit/audit_runtime.py --recover
```

前端命令工作目录apps/web，其余仓库根目录。完整pytest输出在私人 `final-pytest.txt`；早期401预期、预算fixture单位兼容和类型名称冲突都已修复，最终检查没有这些失败。文档验证属于本地结构检查，不冒充完整OpenAPI认证。

## 分层结论与停止

建议模式和本地组合/费用计算/导出/恢复：离线PASS；正常页面零外部编辑及非空恢复PASS。两次真实模型整合验收NOT PASS，修复只有离线/已存响应复验，没有重新请求。当前仍缺实际看点、停留质量、地理交通核实和有效金额，报价能力未接通。

可以进入固定场景的本机整体验收准备；**还不具备宣称建议型AI产品整体验收通过的条件**。下一步应在后续明确额度下只复验这两类修复，不新增外围功能。本轮到此停止，不做向量、供应商、多Agent或发行。Git安全提交/推送核对结果由本任务最终回复提供；不合并master。

## Git diff 摘要

首次暂存范围快照：32 files changed, 2922 insertions(+), 122 deletions(-)。主要新增建议协议/投影/费用模型、同页组件和19项集成用例；其余为原生产链路、契约、文档和既有合成fixture兼容。随后仅追加本段Git摘要。暂存32个文件的真实Key、来源身份、原文片段、token形状和运行时文件扫描零命中；全待推送提交范围另复扫。原三份未跟踪T03报告未暂存。

## 启动与使用

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

已运行时直接打开 http://127.0.0.1:8768/ ，不要重复启动。需要重建：在apps/web运行 `node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 与 `node node_modules/vite/bin/vite.js build --outDir ../../.local/workbench-web`。

新建独立旅行→资料库显式选卡→普通页面设置有限许可→让AI给出建议攻略→预览/取消/采用。组合、预算编辑、导出、刷新均为本地操作。旧测试资料需显式勾选，不变为长期偏好。
