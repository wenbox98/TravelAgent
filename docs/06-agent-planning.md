# 06｜Agent 工作流、行程校验与版本修改

## 责任边界
模型负责理解模糊需求、提出研究问题、抽取证据和解释方案。程序负责权限、请求预算、时间计算、费用、版本和任务恢复。模型不获得任意浏览器执行权。

## 流程
```text
INTAKE → RESEARCH_OVERVIEW → DRAFT_OVERVIEW → WAITING_CHOICE
 → REFINE_CONSTRAINTS → RESEARCH_DETAILS → BUILD_PLAN
 → CHECK_PLAN → PREVIEW → CONFIRM
修改 → DIFF_AND_RECOMPUTE → PREVIEW
```

每个 WAITING 节点只中断和显示已计算结果；网络工具放在独立节点。LangGraph 恢复可能重跑节点前部，付费/网络调用必须由 operation ledger 约束。[S08]

状态中保留原始时间表达，用户未指定年份时不要自动写成已确认日期。内部可以带 `assumed_year` 辅助研究，但 UI 显示暂定、查询真实票价前确认实际日期。时区默认 Asia/Shanghai，这是产品面向中国旅行的设计；跨时区场景暂不作为首版保证。

## 条件来源
每个条件附 provenance：USER、ASSUMPTION、DERIVED、UNKNOWN；另有 strength：HARD、SOFT、UNSET。示例：
- “周日 21 点前到家”：USER/HARD。
- “不想太累”：USER/SOFT，后续用具体步行/出发时间选项澄清。
- “按 5 天示例先比较”：ASSUMPTION/UNSET，不可混入确认条件。
- 人数没给：null/UNKNOWN，不默认两人。

## 粗略攻略输出
2～3 个有依据的方向；每个包括 region_ids/显示地名、代表体验、建议总天数范围、粗略停留分配、交通依赖、取舍、证据引用、未核实项。证据不足时可只给一个或返回缺口卡，不凑固定数量。

同时最多问两个问题，按对后续安排的影响排序。例如先问可用天数或偏好方向，再问交通，不先问酒店颜色。每个问题至少给两个可理解选项和建议；支持“没想好，先帮我比较”。

## 具体计划与可行性
活动节点包含 location_id、入口、duration_min/max、open_intervals、reservation_status、estimated_cost、evidence。交通边包含 mode、duration_range、source_status、fetched_at。

确定性规则：
1. 下一个活动开始 ≥ 上一个结束＋转场＋显式缓冲。
2. 开始、结束及最晚入场满足开放约束；预约未知不等于已预约。
3. 从用户出发点离开直到回到用户终点计算整体时间。
4. 数量、天数、时间区间不能为负；结束早于开始立即拒绝。
5. 已锁定项目位置、酒店、返程条件不自动修改。
6. 未来节假日交通耗时采用清楚标记的假设区间，不能拿当前路线数据保证将来准时。

初版先用有限候选顺序搜索和确定性校验，暂不引入大型优化器。输出结果区分 FEASIBLE、SOFT_CONFLICT、INFEASIBLE、UNKNOWN。`INFEASIBLE` 只能用于给定活动组合和约束确有冲突；有限搜索未找到路线用 UNKNOWN 或“当前候选未找到”，不宣称不存在任何解决方案。

## AC→ABD 合成算例
见 fixtures/itinerary-case.json。可用时间 09:00—18:00 共 540 分钟；休息 60、每段交通 20；从起点到活动并回终点共 n+1 段。
- A=120、B=90、C=270、D=120 分钟。
- AC：390＋60＋3×20=510，可行，余 30 分钟。
- ABCD：600＋60＋5×20=760，超出 220 分钟，不可行。
- ABD：330＋60＋4×20=470，可行，余 70 分钟。

这些是算法测试数值，不是现实景点耗时。禁止删除 C 之后仍沿用 AC 的旧交通边数。

## 费用计算
金额用整数分；unknown 为 null，不为 0。费用项目为单价×数量，并带单位、人/房/夜/程、共享规则、计价状态、是否含于套餐。

例如合成测试：交通 18,000 分×2人×2程=72,000；房费32,000×1间×2夜=64,000；当地交通20,000～30,000；餐饮40,000～60,000；活动12,000×2=24,000；预留20,000。全程含预留=240,000～270,000 分，人均120,000～135,000 分。

预留不是已发生消费，押金不是净支出；套餐内费用去重；退改条件不一致的产品不能当作完全相同的报价。至少一笔未知时总计完整度为 PARTIAL，单列未知项，即使已知项金额很小也不能称“全程总价”。

## 版本规则
UI 提交 `expected_revision` 和结构化 choice patch。API 检查版本，不匹配返回 409；提交确认生成新的 confirmed revision。预览 patch 生成 proposal，不直接覆盖当前确认版。

依赖图：选择→活动→交通边→日程→住宿片区→报价与预算。仅重算受影响节点；已有且仍有效的合规资料可复用。每个外部结果绑定 job_id、trip_id、revision、generation。老结果到达后标 OBSOLETE，不更新前端当前版。

取消原因分类：TIME、BUDGET、PREFERENCE、UNAVAILABLE、OTHER。取消 C 因时间不够，不生成“用户不喜欢 C”的长期偏好。

## 恢复与 operation ledger
调用前写 RESERVED，实际发出后标 DISPATCHED，结果成功存允许保存的内容后标 COMPLETED。进程在 DISPATCHED 后崩溃，状态为 UNKNOWN_OUTCOME，不假设未调用；可重试须扣预算、记录可能重复，或给用户部分结果。

预算上限不会因崩溃清零；过期 lease 恢复前先检查取消和最新 revision。所有对话续写均从持久化选择恢复，不只从聊天摘要猜测。
