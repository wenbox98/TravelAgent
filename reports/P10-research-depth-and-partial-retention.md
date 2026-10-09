# 研究深度、正文拆分与合格部分保留

日期：2026-10-09。基线：`b807af8cb25b081b221d237003b6e9a277b36cc4`。功能分支：`feature/g1-live-llm-validation`。

本批解决通用生产逻辑和正常页面，不重新执行用户已经终止的任务。新增真实小红书连接/搜索/详情/浏览器、项目模型、高德、embedding、报价请求均为0。真实模型的跨文章规划质量未复验，G1仍未通过；合成回归不能代替真实质量验收。

## 只读核对的原问题

| 用户已执行的历史任务 | 实际记录 | 停止及影响 |
|---|---|---|
| 第一轮 | 搜索3次；列表条目60、去重51；详情尝试5次、成功保存4篇新正文；2个采信来源、8条合格引用；模型8次 | 后续EMPTY_BODY使研究PARTIAL、自动任务BLOCKED；merge_research尚未执行，research_ids/own_research_ids为空，已经合格的资料未进入可用选择。 |
| 第二轮 | 搜索1次；列表条目20、去重20；详情尝试1次、成功新正文1篇；本轮采信来源0、复用历史来源1；模型2次 | 审核HTTP200，但reviews[3].explanation超过schema maxLength；整篇SCHEMA_INVALID后终止，不是策略认为一篇足够。 |

这些是用户修复前的真实费用和失败，未移除、退款或重跑。第二轮原回复未保存，不能根据错误位置、历史手工审核或本次合成回复补造接纳结果。两次历史任务属于同一当前旅行，GET呈现当前状态而非分别还原旧页面。只读核对第一轮8条中，6条属于现有规划主题；另2条是OTHER，不擅自改为玩法。当前新投影有6条直接引用、7个内容点（含已有知识关联），内容点实际为交通/时令参考，没有新采信玩法；不能把页面拆分改善冒称正文玩法已变丰富。第一轮8条合格引用本身仍在库中，新代码只读关联原旅行的自有终态研究，恢复可见性，不改旧任务结论。

“搜索6次”未在当前本轮投影复现：第一轮实际本轮账本和研究记录均为3，第二轮为1。未确认其来自历史累计或其他页面状态，不把猜测写成已修复的双计费缺陷。页面现分别展示本轮预留、成功返回列表、列表条目、去重笔记、详情尝试、成功正文、采信来源、历史复用与历史累计；分轮body_reads也明确是详情尝试，包含失败。

## 修改的通用函数与规则

| 文件/符号 | 生产行为 |
|---|---|
| research/planning.py: CandidateSelector.select | 对齐PLAY/ACTIVITY_SCOPE/LODGING/SEASON缺口，支持玩法、观鸟、看点、住宿等标题；缺口互补优先、再比较标题差异。不是固定读列表首篇，也不把弱相关标题当正文事实。 |
| research/advisory_coverage.py: assess、CoverageEvaluator、CoveragePlanner | 覆盖规则v2增加多日住宿片区/落脚取舍；单独“片区”不算住宿依据。按真实缺口组织下一查询。 |
| research/material_eligibility.py、providers/llm.py | 住宿取舍正文可进入原严格提取；模型从既有span目录按缺口选择路线、玩法和条件，不再把全部优先项耗在路线名称上。 |
| research/context_review.py: transport_schema、run_review | 分离有界传输与严格逐条接纳。解释超过200字的条目待审、不截断批准、不保存超长提议；独立合格兄弟条目仍经过原上下文/角色/依赖检查。 |
| research/service.py: ResearchService.run；preview/worker.py: run_job | 新自适应任务遇SOURCE_UNAVAILABLE/EMPTY_BODY，只跳过本篇、消费照计，在同一总预算内读不同候选。保存source_skips。验证、登录、访问拒绝、身份不匹配及全局错误仍停止。 |
| planning/automatic.py: run_task、task_view | 后续硬停止前关联已经合格的独立材料；停止后不再规划或追加外部调用。暴露真实跳过、进展及计数。 |
| planning/materials.py: natural_names、activities、references | 自然正文在明确动作旁保守选择逐字公共名称；否定、宏观环线、未知名称不生成地点身份。通过原旅行/账号/目的地关联终态研究，只读显示已合格资料，仍执行来源与撤回检查。 |
| planning/reference_overview.py: project、choices、view、derive、export | 路线对象与正文拆分点分开，保留角色、条件、审核和已证明的作用范围；多个点不冒充多个来源。版本与完整引用绑定校验选择，导出同样保留性质和关系未知处。 |
| planning/conversation.py: action、freeze_context；suggestions.py: create_job | 兴趣选择、排除、撤回、恢复为本地动作。研究合并后、创建新规划前冻结最新有效取舍与条件；不重写完成提议原输入。 |
| planning/private_payload.py: payload、assemble；advisory.py: payload；questions.py: payload | 选择点的必要原文和条件实际进入planning_advisory_v4，而非只传ID。活动必需引用与选中兴趣优先，继续来源数/6000字/SourcePolicy和过滤；必要内容无法放入则失败。排除引用和依赖活动不进入新输入，锁定项保护不删。 |
| planning/flow.py: get；AutomaticPlanning.vue、planning-api.ts | 即使任务BLOCKED，已合格的正文点仍可查看、选择、排除、恢复；展开准确引用。未知关联不说成每站特色。研究计数与真实正文读取区分。 |

无目的地、景点、来源ID、旅行ID或测试编号特判；不手写活动到工作库、不改旧攻略文件。源事实标准、来源过滤、锁定项和逐方案审查保留。建议型产品不要求精确时刻、完整交通、每站独立体验或每天排满。

## 契约变化

- ConversationAction追加四个point动作；PlanView的开放投影增加points、selected_points、excluded_points、source_skips，无数据库迁移。选择以`local-research-points-1`和引用绑定保存在现有JSON中；原路线规则与历史版本保留。
- ModelContextReviewResponse接纳schema仍限制explanation最多200字；新增ModelContextReviewTransportResponse有限接收最多4096字，随后逐条执行接纳schema。提示词明确200字。不是放宽事实或批准超长结果。
- 任意其他整篇schema错误仍可能停止；本批没有宣称所有HTTP200格式错误均可跳过。外层非法结构、重复候选、全局provider故障、策略拒绝、限流和认证异常不能混入空正文跳过。
- 若已选正文与必需引用超过原来源数/6000字上限，则本地失败；不静默发送孤立ID或扩大授权。自然公共名称投影是保守规则，不是完整实体识别，不能证明地点身份或范围MATCH。

## 复现、回归与恢复

首批5个回归在修复前均失败：玩法/住宿标题互补、自然正文地点拆分、单条超长解释拖累独立审核、硬失败隐藏合格部分、EXPERIENCE缺少可选展示。修复后通过。补充回归覆盖前缀误提取、否定与宏观环线；多日住宿缺口的旧“充分”合成fixture补入明确住宿取舍，未删除新缺口来迁就旧断言。

生产链合成验收使用三篇自编正文，真实运行ResearchService、span提取、上下文审核、规划worker、正常API和构建页面，只替换外部I/O。验证跨来源材料与自然玩法、第三来源必要正文/条件进入protocol4、选择/排除/恢复、不同兴趣经统一submit实际派发后返回不同活动取舍。每次更新只消耗本次既定模型1次，不改原采用版与旧账本。独立进程启用socket拒绝后恢复非空点、选择、提议和原用量。

手工构造两个proposal交给validate的测试仅证明逐方案验收仍成立；另外的真实生产worker合成测试才验证选择进入派发和返回差异。二者都不能声称真实模型质量或新真实攻略通过。

正常构建页面通过HTTP和实际独立生产supervisor/研究/提取/审核/规划子进程，验证正文点选择→排除→恢复→刷新保持选择，操作账本不增加、浏览器与子进程外部请求为0；390px无横向溢出。测试图像和本机数据留在忽略目录。

执行中失败与修复：首次全量在约10%因6个旧覆盖fixture缺少新增的住宿取舍而中断，未取得完整总结，不计为PASS；补齐合成依据后覆盖/深度31项通过。第二次完整全量为1412 PASS、1 FAIL（423.12秒）：发现正文导出将旧duration_scope=null与字符串拼接的兼容错误。已保留UNKNOWN语义修复，相关缓存/导出8项通过。最终重新运行完整全量，取得1413 PASS、2条依赖弃用警告，耗时617.41秒；没有用新增小测试替代全量失败。前端10组检查、构建、ruff、mypy（102文件）、文档契约12项均通过。

最终执行与证据：

| 命令/检查 | 实际结果 |
|---|---|
| `.venv\Scripts\python.exe -m ruff check .` | PASS |
| `.venv\Scripts\python.exe -m mypy` | PASS，102文件 |
| `.venv\Scripts\python.exe -X utf8 -m pytest -q --maxfail=1 --basetemp E:\workSpace\travel-agent-project\depth-final-tests-3` | 1413 passed，2 warnings，617.41秒；完整输出留在忽略的`.local/depth-repair/final-pytest.txt` |
| `npm test`（apps/web） | 10组PASS |
| `npm run build`（apps/web） | PASS，含TypeScript检查 |
| 实际构建页面和生产子进程回归 | PASS；选择、排除、恢复、刷新和非空跨进程恢复；拒绝外网 |
| `python tools/validate_pack.py` | 12/12 PASS |

两条警告来自Starlette对httpx和anyio BlockingPortal旧接口的弃用提示，本批没有改依赖或声称警告已消除。

## 本机部署与数据保护

部署前备份位于忽略的`.local/depth-repair`：原61表一致性副本与逐表摘要、原静态目录、原审计基线。完整回归完成后重新检查活跃任务0、原61表相同、审计调用差值为空，才正常关闭已确认属于本项目的旧8768服务。

实际测量范围：原业务审计的计数差值、原数据库61表逐表摘要、合成测试的socket/浏览器请求拒绝均已核对；没有全系统抓包，其他应用网络和站点HTTP分布为NOT_MEASURED。真实模型规划质量、站点请求减少比例与现实交通可行性也为NOT_MEASURED。GitHub同步网络与本轮项目业务调用分开。

已部署同一8768：保留旧哈希资源，先复制新资源、最后替换index，正常启动原工作空间。新服务PID35980，健康接口200；实际HTTP返回的index、`index-BRL3t8UH.js`和`index-Bfv5UkSz.css`与构建及运行静态目录逐字节一致。启动本地构造自检ready=true、browser_sessions=0，没有执行connect/search/detail或模型请求。

通过原本机入口及正常只读API核对：HTTP200，历史任务仍为BLOCKED，6条直接引用、7个内容点、选中点0，主题为交通条件/时令条件；不把恢复展示写成旧失败变成功或新玩法通过。重启前后61表内容相同，活跃任务0，业务审计计数差值为空。核对进程启用socket外网拒绝，external_calls=0。没有修改旧选择、原采用版、profile或账本；页面保留供用户试用，不自动研究。

启动或重新打开：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

已有服务时也可用`product_preview.py open`恢复入口。地址：`http://127.0.0.1:8768/`。页面“正文里有哪些玩法和取舍”可展开依据并本地选择；“按当前取舍更新建议”是新的显式有界动作，本批未代用户执行真实更新。

## 未解决与停止条件

真实资料的新内容改善、真实模型跨文章组合质量、图片内容、作者独立性和当前交通可行性未验收；原终态错误不能通过本地代码修复变成历史成功。 任意其他整篇格式失败仍可停止，不能承诺每次读满预算或必有多条路线。不会为数量补造事实、放宽审核或偷偷续跑旧任务。没有新增外围产品功能，不发布稳定版、不合并master。

Git安全检查覆盖本批明确暂存的29个文件及完整未推送提交范围，核对本机已配置秘密和真实正文片段；未发现凭据、真实正文或禁止运行产物。原三份未跟踪T03报告保留，不提交数据库、截图、profile或敏感响应。提交推送原功能分支，最终完整SHA与GitHub链接随交接给出，不合并master。

`git diff --cached --stat` 摘要：29 files changed, 1411 insertions(+), 94 deletions(-)；涉及研究与审核、规划上下文、页面、契约、通用回归和交接报告，无数据库迁移或业务数据变更。
