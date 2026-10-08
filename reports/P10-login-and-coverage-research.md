# P10：登录先行、覆盖驱动研究与会话迭代

本轮基线 `227081f4cea9be619e95a7f8f30b6b6c12b73027`，包含原私人试用交接基线。原新旅行选材修复已在历史提交中完成，本轮没有重复重写。随后根据用户在“优化旅行想法提交流程”中的指导，修复登录顺序、覆盖早停与会话交互。本报告不改写历史 G1、P10 或真实失败成绩。

结论：代码、离线生产链路和同一8768部署可评审；最新真实小红书整链仍未通过验收，地图也没有本轮新的实站核实。不能宣布完整私人版交付或稳定发布。

## 修复前后

| 缺陷/场景 | 基线行为 | 当前生产规则与实测证据 |
|---|---|---|
| 登录与搜索 | 自动研究未先完成登录确认，页面缺少明确等待登录阶段 | `ResearchService.run` 在搜索前 connect；worker 显示 LOGIN_CHECK、LOGIN_REQUIRED、LOGIN_AUTHENTICATED。Fake 验证需要登录前搜索/详情为0，同一会话正常继续；过期、验证和拒绝停止 |
| 七天需求只取得一项活动 | `activity_target=1` 及非空缓存可能提前结束 | `advisory_coverage.assess` 按路线、玩法、时长、交通、季节、内容对照和选择面评估。一个活动/部分缓存不能判充分；仍可生成有用局部建议，状态为 PARTIAL |
| 单查询耗尽正文 | 固定一次搜索/两篇正文难以补不同缺口 | `CoveragePlanner` 按缺口给不同查询；ResearchService 共享正文额度，取得足够覆盖立即停止。离线验证不同查询、正文分配、早停和总时限 |
| 重复/复制/冲突 | 候选重复、不同来源同文可能虚增覆盖 | 相同来源不重读，相同正文不重提取；引用高重合不能充当独立内容对照；冲突保留缺口。作者独立性仍未知，不声称已经证明 |
| 对话成为长面板 | 补充条件和诊断面板为主要交互 | `AutomaticPlanning.vue` 以会话、方案卡、快捷问题和输入框组织。研究诊断及已保存攻略折叠；生产Vue的禁网浏览器验收通过 |
| 点选/文字/下一轮脱节 | 无统一的版本化会话选择 | `conversation.action/model_context` 用稳定ID、独立版本、幂等回执持久化方向、排除、撤回和相关用户意图；下一次显式生成冻结最小上下文 |
| 提问误触发新研究或改选 | 普通修改入口不区分提问 | “为什么推荐这些”仅用当前有效引用作本地解释；正常API鉴权/CSRF及真实8768页面验证没有新增研究/模型任务 |
| 模型忽略排除项 | 仅提示词不能保证执行 | 允许活动池先移除排除项；逐方案校验拒绝照搬排除组合，独立合格结果保留；锁定、引用、范围和预算检查继续执行 |
| 排除后知识引用失配 | 初版使用 `zip(strict=True)` 绑定缩小后的活动 | `knowledge.planning.payload` 按活动ID重新绑定，不跳过卡片来源或版本检查；回归通过 |
| 允许池被误当已选池 | 初版排除兼容修改将全部允许活动视为已选 | `advisory.payload` 取“当前草稿已选ID与允许池”的交集；旧攻略、预览取消及本地复核回归通过 |

所有规则适用于同类输入，没有按目的地、景点名、来源ID、旅行ID或测试编号写特殊分支。更换合成目的区域、2/7/10天以及活动数量后，充分/不足规则仍按同一函数执行。覆盖是研究充分性启发规则，不证明每天排满、开放、班次或现实可行性。

## 主要修改位置与契约

- `research/advisory_coverage.py::limits/assess/CoverageEvaluator/CoveragePlanner`；`research/service.py::run`：覆盖、动态查询、全程截止与正文共享额度。
- `preview/worker.py`：登录阶段、真实查询进展、本任务来源过滤及剩余缺口。
- `planning/automatic.py::_cached/_create/merge_research/run_task/task_view`：缓存充分性、任务内选材、来源版本、锁定保护、局部完成和真实计数。
- `planning/conversation.py::ConversationAction/action/options/model_context/explain`：同一旅行的会话、方向与排除状态；`automatic_api.py` 新增同源会话API。
- `knowledge/planning.py`、`private_payload.py::assemble`、`advisory.py::payload/validate`、`scoped_context.py`：最小对话输入、活动排除、独立引用绑定与原作用范围检查。
- `material_eligibility.py`、`quality.py`、`reporting.py`、`materials.py`：缺口相关实质正文进入严格提取；冲突规则复用，季节与取舍不因缺少地点关系而无声丢失。准入不是事实接纳。
- `flow_models.PlanView`/`flow.py`、Vue组件、`planning-api.ts` 与导出工具：新增会话投影、V2有限操作意图和展示字段；同步 `domain.schema.json`、`openapi.yaml`。本轮无数据库迁移。

一两天/未知天数的小范围任务上限为连接1、搜索2、正文4、模型9；多天或区域任务为1/3/6/13。是正常页面明确提交时的新有限许可，失败计数，不能取用旧余额；不是本轮开发人员新增实站授权。缓存充分时收窄到零站点调用和一次规划。研究2700秒、编排等待2850秒、监督3300秒；单模型请求仍120秒、外层190秒。无自动重试，挑战/限流/拒绝停止。

会话摘要仅包含相关用户文字和结构化选择，不把助手解释当证据，不发送整份档案或原始地图结果。每来源每次6000字过滤上限继续执行。局部提问/选择不改写已存模型回复；下一轮模型输入冻结，方向与最终采用分离。

## 实际执行的检查

最后一次生产页面修改后的全量回归：**1359 passed，2 warnings，326.29秒**。两条是Starlette/httpx与anyio的既有弃用提示。其余实际检查如下，不能替代实站结果：

- 登录、覆盖及自动研究定向回归：79项通过；新覆盖/去重/多查询/时限与季节正文回归通过。
- 会话生产服务/API定向回归7项通过，组合定向回归54项通过；旧建议上下文/建议攻略/会话兼容34项通过；多日覆盖/住宿本地复核68项通过。
- 真正构建后的Vue页面，在隔离合成库及网络守卫下：一次提交→建议、选方向→提问→撤回→重选、预览→取消→采用、追加天数与交通→下一轮、刷新恢复及窄屏通过。捕获的下一轮生产payload含方向和新增条件；被排除活动不进入新方案。不是Work手填生产结果。
- mypy：99个源文件无错误。ruff范围检查通过。前端类型检查、Vite生产构建、10份组件脚本通过。
- 过程中全量检查曾有9项失败：UI折叠状态假设以及已选池错误引起的旧建议/复核兼容问题，修复后定向通过。另一次临时目录误放Git仓库内，触发现有profile目录安全拒绝；该运行中止，改为仓库外专用临时目录，不放宽profile规则。默认沙箱的Vite辅助进程EPERM与测试目录权限问题通过正常审批后执行解决，未关闭系统安全或TLS校验。

本地证据在忽略目录：`.local/automatic/conversation-*`、`.local/conversation-ui2/`、`.local/coverage-deploy/`，不提交运行库、截图、日志或真实正文。

实际命令包括 `.venv\Scripts\python.exe -m pytest -q --basetemp=E:\workSpace\travel-agent-project\.test-tmp-conversation-delivery`、`python -m mypy`、范围 `ruff check`、本机已安装 Node 执行 `vue-tsc --noEmit`、`vite build` 和 `apps/web/tests/*.mjs`，以及 `tools/export_preview_contract.py`、`tools/validate_pack.py`、`git diff --check`。契约/文档验证12项全部PASS，包括121个定义、43个API操作和259个相对链接；这些是结构和合成校验，不是完整OpenAPI合规或实站认证。

## 部署、数据与恢复

正常停止原8768进程27144，确认没有QUEUED/RUNNING任务后以原工作区启动33960。沿用 `.local/p04-preview/preview.sqlite3` 与 `.local/workbench-web`，一致性数据库备份和旧静态文件保留于本机。HTTP实取 HTML、JS、CSS与最终构建逐字节一致：JS `index-tlXfX-qL.js`，CSS `index-G8D3n-fG.css`；后端已出现新会话API并完成一次本地解释。视觉检查发现输入框吸附遮住卡片，已恢复正常文流，最后全量使用这一构建。

部署前后逐表摘要比较，只有该正常本地提问对应的 `preview_sessions` 和 `preview_receipts` 变化。37条Evidence、8张知识卡、25个旧模型/研究job、80条操作账目及1个旧自动任务保留。没有改变旧采用版、原文、审核、历史失败、导出或profile。三个原未跟踪T03报告保留。

正常8768页面提问后刷新恢复了2条非空会话消息；另一个独立进程封锁socket/DNS后读取同一库，恢复消息完全相同，旧失败任务仍BLOCKED，没有重放任务。合成浏览器验收另覆盖了非空建议和采用版恢复。生产的新链路尚没有新成功建议，不能把本地解释恢复当作真实研究成功。

启动：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

页面：`http://127.0.0.1:8768/`。操作说明见 [日常私人工作台](../docs/private-advisory-quickstart.md)。

## 真实调用、失败和仍需验收的部分

| 层级 | 实际结果 |
|---|---|
| 本轮代理主动派发 | 小红书connect/search/detail/browser、项目模型、高德、embedding、报价全部0；没有新建非零真实许可或额外测连接 |
| 隔离测试 | Fake/合成结果；pytest守卫禁止外部访问，浏览器外部请求为空，测试worker记录无真实适配器或模型派发 |
| 更新后8768服务 | serve审计model_http/amap_http/external_dns/external_socket/blocked_external均0；本地提问未增加任务或账目。服务指标只代表该进程，不能冒充整机统计 |
| 工作期间用户在旧运行版发起的操作 | 保留了一次旧自动任务：connect1、search1、detail2，观察候选20；必要文字不足，停于RESEARCH_NEEDS_REVIEW，模型0、未产生新合格证据或建议。它不是本轮代理的新验收，也不是整链PASS |
| 整机网络 | NOT_MEASURED；不声称整机零访问 |
| Git同步 | 独立代码同步流量，不计作旅行业务调用；安全检查及最终远端SHA在收尾核实 |

最新真实登录→多查询→正文→提取/审核→覆盖→有用建议仍待限定的操作者许可和正常官方登录，不能沿用旧余额。旧任务正文不足尚不能证明新逻辑能在任意目的地获取足够资料；新真实场景可能仍BLOCKED或PARTIAL，必须如实记录。图片/视频未分析，来源作者独立性未知，住宿片区与新目的地广泛质量未验证。

高德已有地点确认和分段参考入口、独立有限许可及离线回归保留；本轮没有实站新查询，也没有自动关键路段核实闭环，不能称为已完成新的地图验收。对话目前为有限确定性条件解析与本地依据解释；任意自然语言问题的模型问答未实现。不添加供应商、酒店报价、向量或地图调度外围功能。

## Git收尾

只提交源码、合成测试、契约和文档；完整未推送范围扫描配置密钥、认证材料、真实正文片段、数据库、profile和二进制运行产物。功能分支提交推送，不合并master、不创建发行版。最终SHA和远端一致性以本次收尾输出为准。

本轮差异摘要：38个文件，2231行新增、193行删除（含新增测试、会话与覆盖模块和生成契约）。`research/service.py` 的一部分差异是原嵌套调用格式规范化，没有另行引入站点重试或浏览器策略。
