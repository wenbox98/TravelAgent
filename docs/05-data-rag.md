# 05｜数据模型、RAG 与资料生命周期

## 原则
个人资料库是旅行研究的复用层，不是小红书镜像。使用权、保存权、发给外部模型的权限、分享权分别判断。开源、个人登录和点击同意均不是一张覆盖第三方内容全部用途的许可证。

## 数据分类
1. 用户自己的需求、偏好和选择：正常保存，可导出/删除。精确地址最小化，默认只用地铁站/地标。
2. 外部元信息和研究内容：根据来源策略决定是否临时使用、保存摘要、保存原文、向量化。
3. 报价、库存和临时规则：带查询时间及适用日期，复用只作历史参考；最终确认重新查。
4. 身份与短期访问材料：Cookie、二维码、xsec_token、会话地址，不进知识库或模型。

## SourcePolicy
字段定义见 `contracts/domain.schema.json`。策略至少包含 allow_read、allow_persist_metadata、allow_inference、allow_external_model、allow_persist_raw、allow_persist_derived、allow_embed、allow_export、basis、reviewed_at、expires_at。

策略未知时不持久化原文/派生摘要/向量；source policy 的“允许”要有明确适用依据或审核记录，不能由 LLM 根据“开源不商用”自行设置 true。用户同意外部模型处理只是知情同意的一部分，不替代来源用途依据。

开发和自动测试使用明确可使用的合成数据。真实 XHS 连接作为实验功能单独启用；上线前核实适用条款与使用方式。无法确认长期保存条件时，允许符合适用规则的本次临时研究，保存用户自己的选择；不要声称真实 XHS RAG 已完整可用。这个限制必须在资料库 UI 可见。

## Evidence 结构
一条结论包含 source_id、claim_id、主题、正文/图像定位、发布时间、旅行发生时间、适用日期、观察到的事实或作者意见、提取状态和支持程度。日期缺失为 null。

v1.1 统一正文完整度为：`FULL_TEXT`（当前可访问正文已完整取得）、`PARTIAL_TEXT`（只取得正文的一部分）、`SUMMARY_ONLY`（只有摘要/结果页片段）、`METADATA_ONLY`（只有标题等元信息）。`SUMMARY_ONLY/METADATA_ONLY` 不能支持“读过原文”；图片是否处理由 `source_locator`/提取记录单独表达，不因读到正文就声称图集或视频已完整理解。

结论类型分 OBSERVATION、AUTHOR_OPINION、OFFICIAL_FACT、ESTIMATE、ASSUMPTION。模型推断必须使用后两类或注明推断，不能升级成 OFFICIAL_FACT。

## 入库
权限检查 → 文本归一化 → 来源/近重复聚类 → 结构化提取 → 按路线/片区/项目语义分块 → 每块携带父级关系 → 预分词和向量 → 保存来源引用。

建议初始分块目标 350～700 中文字符，仅作为设计参数；路线清单不拆散地名与天数关系。图像提取结果带 image_index 和区域说明，数值未核实不能作为当前报价。删除转载内容时不把另一个独立来源误删。

## 本地检索
- 先按 source policy、用户范围、目的区域、适用时间、删除状态过滤。
- 对过滤后候选分别进行中文预分词 FTS5 检索和向量相似度计算。
- 以 Reciprocal Rank Fusion 合并，初始 k=60；返回有限候选并重排。k 为设计参数，不是保证最佳效果。
- 若 embedding 不可用，显示“关键词检索降级”，不把 FTS 称为向量 RAG。
- embedding 模型/维度不同不可混算。更换模型重建对应索引，不拿不同空间向量直接做余弦。

小规模本地库以精确向量计算换部署简单，使用前置过滤、限定候选和测量内存。原始向量存 BLOB，同时保存 dim、model_id、normalization 和 content_hash。

## 新鲜度
玩法经验可以检索旧资料，但显示年份/季节；价格和库存不能仅因“刚入库”就视为当前。取 fetched_at、source_published_at、travel_occurred_at、valid_for 四类时间，不能合并成一个 updated_at。

没有可证明的新鲜数据时，模型必须说“历史参考/本次未核实”。对于高德返回数据的保存和派生用途遵从具体许可，不把地图结果默认写入 RAG。[S15]

## 删除与权限变更
立即打 tombstone 使检索和展示不可见；取消引用该 source 的进行中任务；按 lineage 清理 chunk、embedding、FTS 行、派生摘要、索引缓存和可再现的 checkpoint 片段。保留不含内容的删除审计。

SQLite WAL、备份、导出可能有历史副本：应用应执行合理的 checkpoint/清理并轮换受控备份，但不能声称对 SSD/用户已有副本完成物理不可恢复擦除。默认备份不含原文/profile/密钥；用户导出的文件需自行管理。

## 核心表
`contracts/database.sql` 提供初始可执行 SQLite 草案。trip_revisions 存选择快照；jobs 存调度；operations 存上游尝试与幂等；sources/claims/chunks 存证据；quotes/budget_lines 存费用；choice_events 存“为什么选/为什么取消”。

退出账号不默认删除用户自己的旅行计划，但必须删除身份和 locator。外部资料能否在退出后继续使用仍由 source policy 决定。不同账号不共享受限的检索结果。
