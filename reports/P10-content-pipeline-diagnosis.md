# P10 内容链路诊断与本地修复

本阶段为 CONTENT_PIPELINE_DIAGNOSIS。基线 `df5bcfc5f2ba5a16a98d3da8357986644240cab2`，所有旅行业务外部调用为 0。没有重新研究、提取、审核或生成攻略；历史真实轮仍已关闭，G1 仍 NOT PASS，整体内容仍 NOT_READY。本报告不替代真实攻略质量验收。

## 真实问题与判断

1. **已采信体验没有到达单站展示和必需引用集合。** 原公共名称解析会把“📍地点：介绍”的冒号及介绍一起读成名称，再拒绝该名称；历史活动通常只绑定路线。原 highlight 又只读活动固定 description。基线模块与同一自编输入的实际对比：修复前只有路线引用，修复后保留路线与明确地点体验两条引用。旧活动 ID、来源和审核记录不重写。
2. **单站条件混入整段对象背景。** `Activity.conditions` 包含定位、对象、日段和审核依赖前提，并非每一条都是当前地点的旅行限制。原页面和导出把它们逐站重复展示，容易把其他地点介绍误当本站条件。现在保留原字段供校验，新增保守的本站限制投影；完整内容及前提按引用放到来源上下文。无法关联的前提也单独保留，不能静默删除。
3. **住宿内容确实存在，不能归因于正文完全没有住宿。** 最近两篇缓存正文共 24 个候选，当时接纳 1、待审 17、拒绝 6；合格住宿片区仍为 0。一篇的住宿选址核心段没有形成候选，另有酒店选择候选：模型提议 REFERENCE，但图片维度检查为 false，程序保留 `CONTEXT_UNCERTAIN` 待审。另一篇的住宿便利建议被提取为 TRANSPORT，模型以 `ROLE_MISMATCH` 拒绝。这是提取用途/主题问题和真实审核阻塞的组合，不能把拒绝改成通过，也不能说住宿类候选全部漏提取。
4. **定向用途丢失。** 正常 AgentQuery 已指定 LODGING，服务却把全部剩余缺口传给择读、正文资格检查和提取；同目的地的泛三日路线标题仍能占用正文额度。现在单独的住宿补充查询只处理住宿缺口；标题与可读正文均须有住宿信号。该缺口消失即停止该查询，不能转而填路线槽位。综合玩法研究保留既有多来源及互补主题语义，不因一条体验参考就提前停止对照。
5. **不存在已证实的“漏用第二次搜索”程序错误。** 外层搜索上限为 2，但本次正常页面请求明确最多搜索 1 次，运行时许可也是 1 次，实际使用 1 次。上限不是必须耗尽的次数；没有增加预算、借旧余额或自动追加搜索。住宿未定仍可生成明确有限的建议，不能据此宣称住宿覆盖或完整攻略通过。

其余待审包括依赖、角色、遗漏条件、重要事实未核实、上下文不确定和信息不足。独立依赖缺失、非全 true 的审核维度及图片未分析，仍按原严格规则阻止通过。读者邀约不能当成作者本人计划；明确亲历仍需原文依据。未发现需要放宽这些标准的证据。

## 通用生产改动

- `planning/materials.py`：`natural_names`、`activities` 修正明确地点标签的边界和排序，不增加目的地词表。
- `planning/activity_content.py`：`explicit_subject`、`content_references` 仅关联已审核、同来源同版本同文档且主语明确的体验；名称提及、待审、跨版本、路线链、混合已知主体及整体背景不会升级。`travel_conditions`、`presentation`、`source_contexts` 保留性质和完整前提。
- `planning/private_payload.py:payload`：在原过滤、来源许可及长度限制内保留明确地点内容；`planning/advisory.py:payload` 增加 `content_citation_ids` 和用途说明；`planning/arrangements.py:required_citation_ids` 将它们纳入必需引用。缺引用仍拒绝该方案，其他独立合格方案继续保留。
- `planning/guide_assessment.py:materials`、`planning/guide_view.py:project/export`：页面和导出共同显示实际引用文字、原性质及前提入口，不能仅换标签冒充内容改善。旧 SOURCE_MENTION 不升级。
- `research/service.py:run/query_gaps/selections`、`research/planning.py:CandidateSelector.select`、`research/material_eligibility.py:skip_reason`：保持住宿单目标用途、解决后停止；另修复叙述型玩法不含“建议/适合”等措辞时的便宜过滤误拒。足量正文、图片边界和下游严格审核继续执行。
- `providers/llm.py`、`research/extractor.py`：未来提取优先明确缺口；独立住宿片区选择应为 TRADEOFF，车站便利不能自动变成已核实交通。路线不能占满住宿候选槽位，邀约不等于作者经历。提取提示版本 `reference-selection-v1.1`；本阶段没有派发模型。
- `apps/web/src/components/AdvisoryGuide.vue`、`planning-api.ts`：同一正常入口消费上述只读视图；前端新增直接内容、本站限制、完整上下文和未关联前提展示。

建议规则版本为 `advisory-guide-1.8`，材料评估投影为 `advisory-assessment-1.2`。只读视图增加 `source_contexts`、`unlinked_source_conditions` 及活动的 `travel_conditions/content_references`。无数据库迁移、旧数据修补或旧模型判定改写；原文、引用依赖、片区背景及历史作用范围保留。没有按城市、景点、来源、旅行或测试编号写生产特判。

## 回归与实际本地检查

- 最初继承的未完工改动上，自编回归实际得到 **5 failed / 7 passed**，复现展示和住宿用途缺陷；另从基线读取旧解析模块，复现地点标签丢失体验绑定。
- 最终相关离线回归 **242 passed**：`test_content_pipeline`、`test_material_eligibility`、`test_candidate_material_priority`、`test_research_depth`、`test_guide_coverage`、`test_advisory_output_contract`、`test_scoped_context`、`test_research_service`、`test_advisory_guide`、`test_advisory_context`、`test_advisory_research_coverage`、`test_goal_research_budget`、`test_research_planning`。测试禁止外网，包含换目的区域、1/5 天、不同活动数量、混合主体、缺引用兄弟方案隔离、额度预留和独立恢复。没有重跑整个历史测试库。已有 Starlette/AnyIO 两项弃用警告保留。
- Ruff 检查通过；`npm.cmd test` 的 10 个前端测试组通过，含新增实际 SSR 展示断言；`npm.cmd run build -- --outDir ../../.local/content-pipeline-web-final` 类型检查及构建通过。构建隔离，旧静态目录完整保留。
- 只读构建真实生产 payload，禁止 sockets/DNS，未调用 provider：A 仍 5 项/v1，没有独立地点体验；B 仍 9 项/v2，只有 **1 项**能关联既有合格体验，其余 8 项仍无独立看点。A 的 15 条、B 的 51 条原活动前提原样保留，移动到完整引用上下文而非逐站当作限制。
- 正常停止原 8768 服务并部署 review 版；同一浏览器主入口刷新后，B 显示 9 项、1 处明确的 GUIDE_SUGGESTION 体验及完整前提展开。旧“来源条件”逐站误挂展示为 0。这不是新模型生成，也不是每站玩法均已改善。
- 独立进程以 `PRAGMA query_only=ON` 并拒绝所有 sockets/DNS，恢复 A/B 的非空草稿、采用版和导出。54 张非派生业务表共 4425 行逐表内容哈希不变，采用版逐字不变，当前任务 0。原下载两份文件与三份 T03 报告哈希不变。新的 review 导出另存本机，不覆盖原导出、不增加采用版本。
- `/health` 为 200，服务首页与当前静态 index 完全一致。review 静态资源为 `index-Dg0QOjwq.js`、`index-C6trEabO.css`；旧静态目录为 `.local/workbench-web-before-content-pipeline`。

实际执行的最终相关回归：

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_content_pipeline.py tests/integration/test_material_eligibility.py tests/integration/test_candidate_material_priority.py tests/integration/test_research_depth.py tests/integration/test_guide_coverage.py tests/integration/test_advisory_output_contract.py tests/integration/test_scoped_context.py tests/integration/test_research_service.py tests/integration/test_advisory_guide.py tests/integration/test_advisory_context.py tests/integration/test_advisory_research_coverage.py tests/integration/test_goal_research_budget.py tests/unit/test_research_planning.py -q --basetemp=E:\workSpace\travel-agent-project\content-pipeline-delivery-host
```

## 网络、使用与停止

本阶段小红书 connect/search/detail/browser = **0/0/0/0**；模型、高德、embedding、报价 = **0**。部署/页面查看/恢复期间，进程审计 `model_http/amap_http/external_dns/external_socket/blocked_external` 增量全为 0，原操作账本及任务数不变。底层浏览器站点 HTTP 总数不是本阶段新增测量项；未打开小红书浏览器。Git 开发同步与旅行业务计数分开。

继续使用同一入口：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

地址 `http://127.0.0.1:8768/`。服务已运行时，上述命令只为原服务打开正常本机入口。

仍缺 A 的独立具体玩法、住宿与非自驾区域衔接；B 仍缺多数单站玩法、合格住宿片区、停留/交通/季节依据及当前可行性。本阶段只证明通用链路与已有内容恢复；修复后新的真实提取及建议质量 **NOT_MEASURED**。不得自动新开实站轮，不重开旧许可、不自动重试。停止主动开发，等待独立核对后再决定下一轮。

Git diff 摘要（补充本段前的暂存统计）：18 个文件，478 行新增、37 行删除；包含一个新生产辅助模块、一个脱敏回归模块和本报告。没有暂存私人运行目录或原三份 T03 报告。
