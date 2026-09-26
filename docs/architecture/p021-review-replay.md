# P02.1：审核时间契约与本地回放

## 字段真值表（实现前确定）

| 来源与候选 | duration_scope | 日序/对象 | 来源性质 |
| --- | --- | --- | --- |
| ROUTE：Day4 甲地到乙地 | NONE | 已发送的 Day4 原文锚点；对象可为 SEGMENT | 按上下文判定，不能默认为亲历 |
| EXPERIENCE/TRANSPORT：Day4 湖边散步/骑车 | NONE | 同源日序锚点 | 按上下文判定 |
| DURATION：全程实际用了五天 | WHOLE_TRIP | 全程对象锚点 | AUTHOR_RECORDED_TRIP，保留条件 |
| DURATION：打算全程安排五天 | WHOLE_TRIP | 全程对象锚点 | AUTHOR_PROPOSED_PLAN，不能当实测 |
| DURATION：Day4 在甲地走两小时 | DAY_SEGMENT | 第四日段；两小时才是局部耗时 | 按上下文判定 |
| DURATION：只有 Day4 标签 | 不足以证明耗时 | 可保留日序，不能推导四天/一天耗时 | 待核实 |
| 没有明确时间 | 不制造时长 | 未知 | 未知 |
| 用户要求五天 | 不进入来源时长字段 | 用户偏好 | 不是 Evidence |

对象范围与经过时长独立。新审核协议 v2 对非 DURATION 只允许 NONE，topic 由程序从原候选取得。旧 v1 按原输入格式校验摘要；历史结果不可变。提取协议仍为 v3。

本地兼容仅针对已存 v1 的 REFERENCE、非 DURATION、DAY_SEGMENT：同源同快照已发送锚点能够唯一确定日序，且陈述不包含耗时/全程量时，记录 DAY_SEGMENT → NONE 及原文锚点。转换不代表接纳，继续上下文、政策、grounding、对象依赖与仓储检查。

新判定标记 LOCAL_REVALIDATION，关联原模型审核、输入摘要、来源快照、候选、规则版本、代码 SHA；不新增模型调用，也不改为 Work 人工审核。EVALUATION 只保存对照；运行时只新增旧程序待审且全部复核通过的证据。发布为新的研究快照，用户显式采用之前保持原选择与证据集合。

隔离数据库与静态目录；不安装外部任务执行器；操作只允许 loopback。只读展开和刷新不产生判定。模型审核和本地校验均不等于外部事实已核实。
