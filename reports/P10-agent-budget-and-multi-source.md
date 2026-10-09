# P10 有界循环成本预留与同列表多来源研究修复

基线：`a46ebe3359e59c4c7fb7bf7988c80206f6d04867`；功能分支`feature/g1-live-llm-validation`。本轮只修通用生产逻辑；真实小红书、DeepSeek、高德、embedding、报价请求均为0。没有替用户提交草稿或重跑旧失败。真实语义质量、实站研究深度和地图闭环仍NOT_MEASURED，G1仍NOT PASS。

## 先复现的实际失败

通过普通AutomaticStart/ConversationAction入口、生产agent/worker/审核/规划和OpenAICompatibleProvider请求序列化，自编两篇材料，拒绝外部socket/DNS。修改生产代码前新增的两项回归实际均失败：

- 默认后续冷缺口：真实离线链为理解→监督→提取→审核→监督，共5次；返回TOOL_PERMISSION_OR_INPUT_REQUIRED，未派发规划，无法预览新版建议。
- 同一搜索返回多个候选：实际顺序仅CONNECT→SEARCH→DETAIL，正文数1。旧工具与worker均固定ResearchBudget(1,1)。

复现命令：`.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_goal_research_budget.py -q --tb=short --basetemp=E:/workSpace/travel-agent-project/agent-budget-repro-normal`，结果2 failed。受限进程第一次遇到pytest临时目录WinError5，之后均以普通本机用户权限执行禁外网测试；未改ACL或安装依赖。

## 通用生产修改与新契约

- `agent_contract.limits`、`AutomaticService._create/start/action`、`conversation.action`：普通页面新提交使用明确的PRIVATE_GOAL_AGENT_V4，初次短旅行模型13次、长/区域18次，后续8次；搜索/正文/连接仍2或3/4或6/1，后续1/2/1。仅新许可；V3仍按原9/13、后续5，旧JSON、账本与失败不重写，不追加自动子许可。
- `agent.tools/decision_payload/run`：决策前扣除本轮模型成本，动态确定可负担正文批次，保留后续反馈决策1次与规划1次；派发时再次核对。最后监督轮不允许派发还需下一轮的研究。合格规划后本地结束，无额外模型FINISH；仍严格检查来源和逐方案约束。
- `preview.worker.run_job.Permits`、`ResearchService.run`：一个RESEARCH_GAP允许一次搜索及有界多正文批次；每篇真实提取/审核后在同一列表重新选择，依据最新缺口与标题多样性。详情前校验生成预留；原空正文、重复正文、审核待审/拒绝和验证停止边界保留。
- `CandidateSelector.select`：可考虑本批已读标题，不因重新排序丢掉多样性。原文审核仍决定是否接纳，标题不变成Evidence。
- 原详情账本指纹过滤跨批次的已尝试来源，包括空正文没有source行的失败；不会再次读取失败详情。重复查询在父任务派发前拒绝，重复正文仍计实际读取，但不再次提取或增加覆盖。
- `questions.payload`、`agent_model.run.current`：V4监督输入最多6个过滤后的来源，当前明确选择与本任务新资料优先；引用带匿名source_ref用于区分来源，保留作者角色、日段时长、整体背景范围与条件。缓存问答仍最多2个来源；派发前后重验采用同一规则，不能在跨进程时丢掉第3个及以后的来源。
- 首页、对话用途说明和AgentProgress同步V4成本与批次含义，兼容显示旧V3进展。domain/openapi正常提交/会话许可枚举新增V4、保留V3；SQLite仍18，无数据迁移。

没有目的地、景点、来源、旅行或测试编号特判，没有放宽上下文或事实标准；没有改写历史报告、数据库攻略或导出。

## 实际离线调用序列和成本

普通默认后续许可为模型8、搜索1、正文2、连接1，无额外手动预算参数：

| 顺序 | 实际生产阶段 | 模型累计 | 站点工具累计（合成Adapter） |
|---|---|---:|---|
| 1 | travel_intake_v1 | 1 | 0 |
| 2 | travel_supervisor_v1，选择RESEARCH_GAP | 2 | 0 |
| 3 | CONNECT、SEARCH；择读第一个合格候选 | 2 | 连接1/搜索1/详情1 |
| 4–5 | select_evidence_references_v1、review_evidence_context_v2 | 4 | 不新增搜索 |
| 6 | 最新缺口下择读同列表另一候选 | 4 | 详情2 |
| 7–8 | 第二篇提取、审核 | 6 | 不新增搜索 |
| 9 | 监督输入真实两篇结果/引用/内容点，选择GENERATE | 7 | 不新增站点调用 |
| 10 | planning_advisory_v4；严格逐方案校验后本地停止 | 8 | 总连接1/搜索1/详情2 |

上述“顺序”含本地工具事件，不等于模型调用次数；最终实际Provider请求8次，与同grant账本model=8一致。列表20条、去重19个；首条为视频未读取，实际选读第6和第18条（自编列表的位置），不是固定第一篇。两来源各5条合格引用，涵盖ROUTE、EXPERIENCE、DURATION、TRANSPORT、TRADEOFF；作者计划和历史记录保持不同角色，DAY_SEGMENT不变整趟时长。下一轮生产payload含10条引用、可选路线与正文拆分点；可生成非空、可预览提议，不等于现实可行性。

进一步执行的边界：

- 先做CACHE与DECOMPOSE会多消耗两次监督；后续8次许可自动把正文批次降为1，仍以8次总请求生成建议，不先读第二篇耗尽收尾成本。
- 已有选择/排除时再补两篇，真实监督payload包含当前选择、排除ID与至少3个来源的有效引用；新任务不覆盖旧采用版。
- 空正文或重复正文的批次只增加一个来源的5条合格引用，只提取/审核一次；重复正文不增加覆盖。第二篇验证时立即停止，先前合格资料保留；取消时晚到结果不能提交，已合格Evidence保留。
- 后续搜索再次观察空正文失败来源时，按原账本跳过；合成执行连接1/搜索2/详情3/模型9，保留2个合格来源，没有重复失败详情。
- 默认后续两篇结果经独立进程恢复：引用10、来源2、非空提议、已用模型8/剩余0，外部尝试0；恢复不重派理解、研究或规划。
- 新许可成本公式在未知天数、1天、7天、区域/非区域、后续下分别校验；生产函数不引用测试目的地常量。最后决策轮及不足收尾成本时研究不可用。

## 执行与验收

本轮16项新增回归已通过；最终全量1463 passed，2项既有弃用警告，420.51秒。前端10组测试、TypeScript/Vite构建通过；ruff全仓与标准mypy107文件通过；契约校验通过（129定义、221引用、46操作、277相对链接）。中途前端原“一篇”文本断言和合成review helper的重复关键字/错误测试预期均已定位修复，不把中间失败报告为通过。

实际执行：

- `.venv\Scripts\python.exe -X utf8 -m pytest -q --tb=short --basetemp=E:/workSpace/travel-agent-project/agent-budget-full`：1463 passed；本机忽略日志`.local/goal-agent/full-budget-tests.log`。
- `npm.cmd test`、`npm.cmd run build`：最终用途说明下全部通过，TypeScript与Vite8.3.0构建通过。
- 最终构建再次运行`.venv\Scripts\python.exe -X utf8 -m pytest tests/e2e/test_automatic_workbench.py -q --tb=short --basetemp=E:/workSpace/travel-agent-project/agent-budget-final-ui`：1 passed，17.23秒。独立localhost隔离页面实际检查V4普通提交/18次许可、正文2篇、模型提议、选择、预览、取消、采用、后续条件更新、假设不改条件、刷新和窄屏恢复。测试只使用合成Adapter及本机页面，外部网络拒绝；没有操作用户的8768草稿。
- `.venv\Scripts\python.exe -m ruff check .`：PASS；标准`MYPYPATH=apps/api;integrations/xhs-sidecar`下mypy：107文件PASS。
- `tools/export_preview_contract.py`及`tools/validate_pack.py`：PASS。本轮只有许可枚举增加，无SQL迁移或Evidence标准变更。

## 部署与数据保护

全量回归后核对8768无活动任务，正常关闭旧PID36432。先复制新哈希资源、最后切换index.html，保留所有旧资源；使用原库`.local/p04-preview/preview.sqlite3`与原专用profile启动新PID14060（Windows TokenElevation=false，普通用户），服务会话35439保留运行。

启动命令：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

已经运行时直接使用`http://127.0.0.1:8768/`，刷新加载新页面；需要本机会话入口时用同一启动器或`product_preview.py open`，不清库、不改Cookie。部署本身用serve（没有--open），没有替用户打开/提交草稿。

- 启动ready=true、BrowserSession=0、health200、active_tasks0。
- JS为`index-DzM2mkOo.js`，SHA256 `3e44f79a5309cb3e08d6dee51b3ee9b358bd7bb6d4da24cc7148786b405851b6`；CSS为`index-C8gDcWmn.css`。dist、运行静态目录及实际HTTP字节完全一致。
- SQLite仍18；对本轮一致性快照61张表逐行比对，changed_tables=[]。claims54、sources24、knowledge_cards22、preview_jobs32、planning_tasks7、continuation_operations131均保持原样。旧采用版、失败、选择与账本没有重置。
- 原三个未跟踪T03报告SHA256均不变；未操作用户已有浏览器草稿或原导出。忽略目录`.local/goal-agent-budget`保存升级前一致性快照、静态副本、计数/哈希和部署核对；它们不进Git，不可用于恢复旧额度。
- 实测生产model_http/amap_http/external_dns/external_socket/blocked_external增量均0，指标没有歧义文件；账本没有新增业务操作。小红书connect/search/detail/browser、DeepSeek、高德、embedding、报价本批均0。GitHub同步单独计为Git操作。
- 浏览器站点导航/请求/字节为NOT_MEASURED，未实站试跑；BrowserSession=0来自实际启动自检，不把本机合成页面Chromium计为小红书会话。

## Git交付

仅按明确文件清单暂存；提交前扫描暂存内容，提交后扫描完整未推送提交范围，检查配置密钥、真实正文片段、认证材料、数据库、profile、图片及敏感诊断。原三份T03报告不暂存。最终提交/compare链接及完整本地、远端SHA核对随交付消息提供，不合并master、不发布稳定版。

实际`git diff --cached --stat`（补录本节前）：28 files changed, 653 insertions(+), 88 deletions(-)。最大变更为350行生产路径离线回归；生产代码、契约、界面、文档和测试随同交付，忽略目录及运行数据不暂存。

## 剩余边界

本轮为禁外网离线证据；自编Provider响应不是DeepSeek真实推理质量。真实小红书、多来源实际可用性、真实高德均未重测。有限循环不能保证每个来源都通过审核或每次都给出完整攻略；额外决策可降低实际正文数。每次批次仅持有自身观察列表，覆盖足够即停，不承诺读完所有元数据。地图仍需要用户确认公共地点；没有新的真实试跑许可，既有人工待办不被重开或催促。
