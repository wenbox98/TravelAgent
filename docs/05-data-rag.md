# 05｜数据模型、RAG 与资料生命周期

## 当前私人本地用途更新

用户已明确选择 PRIVATE_LOCAL_RESEARCH：当前本人私人旅行研究允许在本机保存实际精读的少量原文、规范文本、正文块和派生证据，默认 PERSISTENT；允许配置的模型处理必要正文。此用途决策不声称作者或平台授权，basis 仍为 UNKNOWN。具体契约、保留期限、清除与版本见 [T06.1 私人数据策略](architecture/t06-private-local-research.md)。下文旧的 UNKNOWN 限制适用于没有明确私人用途模式的策略。当前不公开发布、不共享数据、不上传自有服务器、不缓存原图、不向 Git 提交真实正文或数据库。

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

## 当前入库与知识主体（P08）

原文型 Evidence 继续使用原准确定位、上下文审核及最新策略。日常复用主体改为版本化 KnowledgeCard：SOURCE_REFERENCE 保留原审核角色、条件和完整度；PLACE_LEAD 只证明公共名称被定位；PLAN_PATTERN 只表示曾采用的安排和 AI/用户时间建议。开发测试资料默认排除，显式选择才复用。

规则整理前核对当前原文，保存有限条目和历史核对摘要后，正常知识读取只依赖卡片、来源元数据、历史依据及最新策略。原文存在/显式清理/意外损坏分别处理；显式清理后为 HISTORICAL_ATTESTATION，不声称当前原文重验或外部事实已证实。

## 本地关键词检索（已实现范围）

- 先过滤账号、目的地、类型、测试属性、日期、删除/撤销和策略，再在最多250个候选中有限排名，最多显示60项；超过范围明确提示缩小查询。
- SQLite FTS5 保存经过编码的中文二字词，BM25 排名；查询作为参数化文字，不执行用户FTS语法。FTS能力由本机创建检查，无网路探测。不可用时明确 LIMITED_TERM_INDEX_FALLBACK，保留有界词索引查询。
- 同源多个卡片按 source_id 去重；命中不自动 sufficient。交通、季节条件同时展示，不平均冲突。精确地区无匹配时保持空结果。
- 只有用户选中的卡片及当前约束进入现有规划模块，绑定 ID/version/hash；沿用普通页面许可。SQL授权器在实际输入构建中拒绝原文、块、候选和旧模型输入读取。
- embedding、向量语义检索、RRF融合与模型重排本批 **NOT_IMPLEMENTED**；向量是未来可选检索方式，未配置不会阻塞当前关键词辅助规划。

原“全文分块350～700字并默认向量化”仅保留为历史设计，不是当前默认产品流程。详细生命周期见 [知识资料库架构](architecture/knowledge-library.md)。

## 新鲜度
玩法经验可以检索旧资料，但显示年份/季节；价格和库存不能仅因“刚入库”就视为当前。取 fetched_at、source_published_at、travel_occurred_at、valid_for 四类时间，不能合并成一个 updated_at。

没有可证明的新鲜数据时，模型必须说“历史参考/本次未核实”。对于高德返回数据的保存和派生用途遵从具体许可，不把地图结果默认写入 RAG。[S15]

## 删除与权限变更
立即打 tombstone 使检索和展示不可见；取消引用该 source 的进行中任务；按 lineage 清理 chunk、embedding、FTS 行、派生摘要、索引缓存和可再现的 checkpoint 片段。保留不含内容的删除审计。

SQLite WAL、备份、导出可能有历史副本：应用应执行合理的 checkpoint/清理并轮换受控备份，但不能声称对 SSD/用户已有副本完成物理不可恢复擦除。默认备份不含原文/profile/密钥；用户导出的文件需自行管理。

## 核心表
`contracts/database.sql` 提供初始可执行 SQLite 草案。trip_revisions 存选择快照；jobs 存调度；operations 存上游尝试与幂等；sources/claims/chunks 存证据；quotes/budget_lines 存费用；choice_events 存“为什么选/为什么取消”。

退出账号不默认删除用户自己的旅行计划，但必须删除身份和 locator。外部资料能否在退出后继续使用仍由 source policy 决定。不同账号不共享受限的检索结果。
