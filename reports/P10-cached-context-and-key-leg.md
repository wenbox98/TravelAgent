# 缓存会话、路线参考与关键路段交付

日期：2026-10-09。基线：`2bc1f487fae78380af63bb62afcd68bf285f61b8`。原功能分支 `feature/g1-live-llm-validation`；不合并 master，不发布稳定版。

## 结果与边界

本批改善“已有合格路线却什么也不能讨论”的正常首页路径：无具体活动也能显式整理、选择/撤回和独立导出本地路线参考。主对话框具备一次缓存 AI 问答的生产路径，模型解释的条件需另行确认；有来源依据的公共活动可以只核实所选一段，不强制家庭地址、采用攻略或完整地图。

本批真实项目外部调用全部为0：模型、小红书连接/搜索/详情/browser、高德地点/路径、embedding、报价均0。真实缓存只作本地投影和恢复；问答/关键路段调用用合成适配器验收。新增真实问答和地图结果 **SKIPPED，未追加许可**，不能声称真实成功。当前东北无合格具体活动，关键路段入口正确保持待补充，不从宏观路线造景点。

已结束的东北实站批次另见 [真实验收](P10-northeast-live-validation.md)：连接1/搜索3/详情6/模型12，新增5条合格引用，仍是 PARTIAL。此处不重用其模型剩余额度、不重写旧 BLOCKED，也不把本地参考叫作新模型攻略。G1仍NOT PASS，完整私人建议版仍不可冻结。

## 保存回复的漏斗审查

零联网读取原提取候选、模型审核提议与程序判断。50条定位通过不代表语义通过：模型 REJECT20→程序拒绝20；模型 NEEDS_REVIEW13→待审13；模型 REFERENCE17中程序接纳5、待审12。

12条额外待审分为角色不匹配4、遗漏上下文条件5、重要事实未核实1、依赖未解决2。最后2条在独立诊断副本恢复原单条判定后走正常发布，实际得到 `ROUTE_ASSOCIATION_WITHOUT_ACCEPTED_ROUTE`：依赖的路线对象没有接纳，不能独立发布。该副本不是新结果，主库候选、审核及 Evidence 均不改写。没有证据支持放宽原标准。

六篇已存正文原始/规范/过滤字符数分别为400/400/392、155/155/150、318/318/313、525/525/520、91/89/87、344/344/344。图片数3/5/9/1/2/3；没有读取图片，图片内容未知。未复现大量过滤丢文，不能凭短正文宣称图里必有路线。审核不足继续保留。

## 通用生产函数与契约

- `planning/reference_overview.py`：`references/project/derive/view/export`，当前旅行最小合格引用、来源分组、作者角色/条件/时长/路线对象、版本与绑定核查、单独参考导出。具体活动0也可用；同源不算独立对照。
- `planning/questions.py`：`payload/create/view/validate/run`，现有 SourcePolicy/外发过滤、当前选择/排除/条件、至多两来源6000字限制、QUESTION独立许可、单次任务和晚结果防护。回答不是 Evidence，条件解释另行确认。
- `planning/conversation.py`：`derive_overview/select_reference/clear_reference/ask/confirm_intent`；明确陈述的条件优先于问号分类，假设性问题不默改条件；继续 revision/version、锁定和幂等检查。
- `planning/automatic.py`：未来任务材料不足但有合格路线时返回本地参考 PARTIAL；旧任务原结果保留。失效/重启同时关闭未完成问答，刷新不派发。
- `planning/critical_map.py`：`view/enrich/action` 及 `CriticalMapAction`，同日相邻公共活动、一次选段、独立MAP许可、真实POI确认、最多地点2/路径1、先存意图回执再I/O、失败不重试。
- `flow/flow_api/flow_models/flow_maps/automatic_api`、`workbench`、`research/bounded`、`suggestions`、`network`、`scripts/product_preview.py`：投影、路由、用途/额度、worker派发和单模型网络边界。问答模型120秒，监督180秒。
- `AutomaticPlanning.vue/PlanningPanel.vue/CriticalMap.vue/planning-api.ts`：同一入口的路线卡、单次AI输入框、条件确认、问答状态与选段地图；本地解释和AI回答明确区分。

OpenAPI与领域Schema同步增加QUESTION、新会话动作、参考导出与关键路段DTO，`tools/export_preview_contract.py`同步生成；无数据库迁移。完整语义见 [契约](../docs/architecture/cached-conversation-and-key-leg.md)。

## 修复前后回归

| 场景 | 修复前 | 当前 |
| --- | --- | --- |
| 已采信路线、活动0 | 普通页面无可用内容 | 本地参考可展示/选撤/导出，仍无伪造活动 |
| 明确说只有5天、不自驾，同时带问号 | 可能归为提问而漏条件 | 明确陈述按约束解析；假设句不改草稿 |
| 有问题想继续讨论 | 只有本地引用解释 | 主框显式单次AI问答；无隐式研究 |
| 选择/资料在问答期间变化 | 无独立问答协议 | 晚结果取消，不写回旧上下文 |
| 重启未完成问答 | 无独立恢复语义 | 取消、关闭新许可、已消费不恢复、不重发 |
| 只想核实一个公共活动对 | 需进入完整地图操作 | 选段授权→两个地点→实际POI确认→一次路径 |
| 无关第三活动没有来源 | 全体检查可能阻止所需路段 | 只检查当前相邻对，未发送无关活动 |
| 刷新/重启地图 | 临时值不适合当长期事实 | 保留选择/额度，结果过期，不自动补查 |

测试更换了合成活动、天数、来源与活动数量；生产代码没有按城市、旅行ID、来源ID、测试编号特殊分支。真实东北只验证已有资料的本地消费，未据此宣称其他目的地实站通过。

## 实际检查

- Ruff：修改的Python路径检查通过。
- Mypy：仓库配置入口 `.venv\Scripts\python.exe -m mypy`，102个源码文件通过。一次误用 `mypy apps/api` 扩大到未纳入当前配置的旧基础代码，报告210条类型/导入错误；未据此改动外围代码，按既有配置复核通过。
- 前端：`npm.cmd test` 十组组件脚本通过；`npm.cmd run build` 类型检查及Vite生产构建通过。
- 全量pytest：最终生产输入补齐已证明路线关系及日段范围后，`.venv\Scripts\python.exe -m pytest --basetemp E:/workSpace/travel-agent-project/.test-tmp-context-relationship -q`，1371通过，218.76秒，2条既有Starlette弃用警告。前一轮最终构建回归也为1371通过。
- `tools/validate_pack.py`：12项通过，结构检查不冒充完整OpenAPI认证。

新增集成测试覆盖实际服务函数的0活动参考、幂等问答、私址过滤/已知预算、当前选择/排除、条件确认、错误引用、晚结果、重启取消，以及选段计数、失败早停、顺序失效、无关活动隔离。实际构建的Vue合成浏览器验收覆盖问答单击提交、条件确认、下一轮输入、选段2地点/1路径、刷新和窄屏；合成成功不是供应商实站成功。

## 运行与本地验收

沿用原 `.local/p04-preview` 工作库、专用登录profile和 `.local/workbench-web`；构建前保留数据库一致性副本及旧静态文件以备回滚，未以备份覆盖当前数据或恢复预算。启动和打开仍是：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

地址 `http://127.0.0.1:8768/`。已运行时原命令只打开正常本机入口，不重启任务。无需阶段参数、Cookie复制或开发者工具。

当前东北首页本地整理版本2展示5条既有合格路线/时长引用、单一来源及原缺口；选择/撤回/重选均只记本地会话。原研究BLOCKED不覆盖，未生成具体活动或采用版。正常页面导出到本机下载目录，实际文件与服务端Markdown的SHA256一致；浏览器下载事件等待曾超时，但文件已成功落地，不将事件超时误判为业务失败。

正常停止再启动8768，独立只读进程禁止socket/DNS/子进程后恢复：参考版本、有效选择、完整视图及导出哈希与重启前完全相同，网络尝试均0。页面刷新也正常恢复；没有模型问答任务或新采用版。

逐表内容哈希保护通过：claims42、sources18、source_policies1、extraction_attempts19、context_review_runs14、extraction_candidates175、knowledge_cards13、continuation_operations102、research_continuations21、planning_tasks2、preview_jobs26全部与开发前一致。仅正常本地会话/幂等回执新增，不覆盖历史审核、采用版或账本。所有本批正常serve进程网络审计均model_http/amap_http/external_dns/external_socket=0。

真实生产问答payload只读检查通过：5条最小引用、有效选中参考、当前7天条件、DAY_SEGMENT范围及5条已证明路线对象关系均进入输入；没有BodyBlock或完整正文。这是派发前检查，实际模型请求0，不拿payload正确冒充回答成功。

## 仍存限制

真实缓存只有一份已采信路线来源，不足以声称独立玩法比较。具体玩法、交通、当前可行性和资料选择面缺口仍在。AI问答不能替代严格提取审核；本批未实测新问答的真实回答质量。关键路段本批未实测高德，不能靠Fake通过宣称接通。路线参考保留来源措辞和条件，不能把建议天数套用到无关系路线或把作者说法当实测。

停止新增真实调用；若后续需要，仅在新版已部署、回归及安全提交完成后申请新的明确有限许可，不挪旧余额。

## Git差异与安全交接

写入本段前的 `git diff --cached --stat`：32个明确文件，1944行新增、45行删除。主要为三个生产模块、同页组件、合成回归、Schema/OpenAPI及中文契约；没有数据库迁移、目的地特判或正文改写。暂存与完整未推送范围检查覆盖本机配置密钥、来源正文片段、认证材料、profile、数据库、图片与原始诊断，未发现命中。真实数据、payload、导出、截图和回滚副本留在Git之外；三份原有T03未跟踪报告保留。推送只到原功能分支，使用正常TLS，不强推，不合并master。
