# 建议攻略与旅行花费：v4契约变更

## 默认与兼容

日常新旅行使用 `PlanDraft.planning_mode=ADVISORY`，首项/结束属性默认FLEXIBLE，钟点为空。旧JSON缺失字段时仍按DETAILED/LOCKED读取，旧采用快照不重写。已有固定验收demo保留原义；新的GUIDE_MULTI_DAY只是明确自编测试入口，使用普通P07许可，不建立阶段预算常量。

模糊需求中的“十点左右开始”记录软偏好；明确返回时间记录硬截止。没有关联项目或上午下午不明确的预约保留hard_notes，在页面提示确认，不猜测时段。结构化预约由活动locked_start持有；模型无法改写首项钟点、交通、硬截止或锁定项。时间建议不是可行性保证。

## 复用生产路径

`suggestions.payload_for → advisory.payload → planning_advisory_v4 → advisory.validate → apply`复用原工作进程、120/180秒截止、耐久许可和调用账本。输入仍由private_payload/KnowledgeBinding过滤；知识路径不读正文。候选只来自当前提供且有效的活动/卡片。每方案独立结构、引用、上下文、城市范围和硬约束检查；一个被拒不丢弃其他合格项。UNKNOWN可以暂定，MISMATCH不会进入市区选择。

新 `GuideResponse/GuideProposal/GuideActivity/GuideContent` 分离建议内容；模型不能输出不可见的任意地点、商家、交通事实或报价。安全且有限的结构化响应沿用7天私人诊断，按v4规则本地回放；不保存推理、原始网络响应、模型输入到Git。

1.2规则补充：旧walking_allowed=false在新建议输入中解释为未选择，即null，不表达禁止步行；模型不得凭空声称步行不可用。已有明确人数/房间/天晚口径不能在预算条件中变为未知。版本或输入变动后，旧提议重新验输入与规则，历史计数保留但不代表当前可采用；详见P09两次实测失败记录。

## 组合、食宿与本地计算

组合使用持久activity_pool并逐次重验引用，preview_combination保存修改前草稿；取消恢复，采用前再验，修订失效/晚到任务不覆盖采用版。停留和日段可本地修改，AI停留一直保留建议性质。餐饮枚举只表示用餐策略，住宿枚举只表示取舍原则；区域名必须来自输入，人数、房间、晚数未知不补默认值。

复用初始契约的AmountRange/BudgetLine名字，显式增加basis、activity_ids、unit、paid_fen、locked、is_synthetic等字段。状态QUOTED/ESTIMATED/HISTORICAL/PAID/UNKNOWN与依据分别保留：AI_BUDGET_PROPOSAL/USER_BUDGET_TARGET是计划预留，OBSERVED_QUOTE必须有报价引用和查询时间，HISTORICAL_REFERENCE有历史引用；未知与不适用/自行安排分开。普通编辑不能制造外部报价，模型也不能写已付或实际报价。

TripBudget用整数分计算人数×天数、房间×晚数、一次性或每日项。备选活动未选不计，部分拆分不了的套餐变未知；被包含明细不双计，已付从预计剩余中扣一次。人数未知可单列每人项，房费不自动平摊。所有小计都称已计入部分；软目标只提醒，硬上限保留为用户约束，不自动删项。

这些结构存于原preview_sessions.state_json的PlanDraft；SQLite版本仍16，无数据回填、无budget_lines表删除或旧额度重置。旧SQL预算/报价表仍是早期草案，当前没有供应商接通。同步domain.schema.json与openapi.yaml，通过显式契约变更提交发布。

## 页面与导出

同一8768主入口加入AdvisoryGuide，现有研究、知识、地图能力保留。普通编辑只保存草稿；组合与模型替换预览后采用。额度耗尽、未配置仍可本地修改、算费用、折叠与导出。

`GET /api/v1/preview/planning/{session_id}/guide-export`沿用本机认证与同源防护，读取采用版，重验卡片/引用后生成转义Markdown。不导出全文、原模型输入、私址、诊断或临时地图值。刷新重启不派发外部请求，导出不是重新生成建议。

范围：关键词资料库继续可用，向量仍NOT_IMPLEMENTED；G1保持历史NOT PASS；不新增供应商、酒店抓取、自动预订或复杂求解器。
