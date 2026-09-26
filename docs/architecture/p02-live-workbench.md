# P02：本机有限研究与运行时上下文审核

本轮从 P01 已保存的工作副本在线备份到独立 workspace；保留原研究库、P01、既有选择与旧额度。新工作库升级至 SQLite v12。G1 历史 NOT PASS 不变，实测子项见 [P02 报告](../../reports/P02-live-research-workbench.md)。

## 数据路径与版本

普通新建 EvidenceExtractor 默认 extraction v3 / reference-selection-v1。ResearchService 保存 SourceContent 和 BodyBlocks 后，ExtractionRecovery 创建已绑定 content/hash/normalization/protocol 的耐久尝试；页面 worker 显式 v3，并再次验证预留版本。历史恢复按 extraction_attempts.extraction_version 构造 extractor，不自动将旧 v2 重跑为 v3。历史 T06.1 连通性工具、T06.2 合成诊断和既定 benchmark 显式固定原 v2；它们不是页面新研究入口，旧额度不重置。

模型提取只选择提供的片段 ID，程序物化原文、字符定位、条件并集。独立 `review_evidence_context_v1` 每篇最多一次，不逐条调用。审核输入从原 candidate_json 与不可变正文重建，忽略所有 Work 标签和 review_json。正文按原过滤分片，总 text 字符数最多 6000；父段范围、前后片段只传关系，不重复原文。用户天数和驾驶意愿在独立 target_preferences 中。

模型提出候选结果、白名单原因、必要条件 ID、参考角色、日段/全程范围、对象 ID、依赖关系及简短审核依据。程序复核同 source/snapshot/scope、已发送引用、原条件、父段前提、逐字定位及当前 revision/策略；有效 ID 不等于语义已通过。计划不成为完成经历，日序不变实测天数，图片未知仍未知；重要当前交通、运营、天气保证和医疗断言不进入执行依据。有限规则和模型都可能漏判，不宣称全域正确。

审核记录与 Evidence 分开。历史为 WORK_REVIEWED；运行时只有绑定 COMPLETED/RUNTIME context_review_runs 并经程序复核的候选可标 MODEL_CONTEXT_REVIEWED。前端没有更改审核身份的 API。仓储写入、恢复读取与预览均复核模型审核链；PENDING/PENDING_REVIEW、拒绝及无审核链不能进入可信预览。旧 benchmark 的逐字定位兼容逻辑不是对无审核旧数据的自动可信授权。

逐条保存，路线对象先于依赖项；无效依赖保持 NEEDS_REVIEW，不回退为 Work 审核。审核失败、格式错误、超时保留正文和候选。模型审核只检查原文支持关系，不证明作者真实经历或当前交通可行。

## v12 契约变化

- 原 research_continuations 移除写死批次 ID，新增 limits_json/gate_json；原 continuation_operations 原样保留，仍使用 CONNECT/SEARCH/DETAIL/MODEL。旧行新增列为 NULL，全部旧消费/失败不改写。
- context_review_runs 绑定原尝试、scope、revision、输入摘要和模式 EVALUATION/RUNTIME，保存白名单结果、诊断及最终状态。EVALUATION 不修改旧候选或 Evidence。
- preview_jobs 保存用户动作、幂等键、条件快照、独立研究 ID、状态、取消标志和安全摘要。同许可最多一个页面任务；不同入口共享同一总模型额度。
- ClaimAssessment 增加 MODEL_CONTEXT_REVIEWED、context_review_id。新增审核 schema、工作台/任务 DTO，与 OpenAPI 一并导出。缓存 DTO 仅增加工作台可用标识及原兴趣待确认提示。

迁移只执行在 P02 副本，前置 online backup 保留 v11。回滚使用原程序及备份副本，禁止对已含新数据的库强行降级/重新复制覆盖。已登记许可绑定当前数据库路径摘要；普通复制不能重新获得许可。启动只恢复当前副本，不重复覆盖。

## 页面任务与预算

同源 `/api/v1/preview/workbench` 和 job GET 只读本地。POST jobs 经 HttpOnly cookie、Host/Origin、CSRF、scope、revision、幂等、许可和门槛后立即返回 QUEUED；独立后台进程运行 ResearchService。当前明确天数、不自驾和已确认方向构成一次缺口查询，不把不自驾限定为只乘公交。缓存未命中保留输入，只确认目的区域，不自动调用。

模型处理复用 `supervise_reserved`：HTTP 等待 120 秒，单次总截止 180 秒，超时终止并回收自有模型子进程，不通过取消 Playwright coroutine 实现。SQLite 等待网络期间没有长写事务。每次尝试前耐久计费，失败不回收；状态不明不自动重试。取消在各派发点与模型 HTTP 打开前再检查，已经发出的请求可返回允许保存的历史资料，但不更改页面当前选择。

后端恢复只将未完成任务标 INTERRUPTED，不重派。新结果提交到同一 P02 库，显式“采用新材料”后才更新预览关联。采用时使用当前偏好/兴趣，而非派发时旧快照；原对象或依据变动时保留原兴趣并要求重新确认。确认仍只是兴趣方向，非可行性。

授权由操作员命令登记，不由启动/页面自动创建。缓存 A 两篇各一次审核；外部对照评估后只能写 gate，不给候选写通过。A 未达安全和可用性门槛则 B 不开放。B 最多 connect/search/detail 各一次、提取/审核各一次。总模型四次；正文必要部分仅往既定供应商和模型发送。额度包含页面、脚本和 worker。验证后关闭本轮许可，未用次数如实保留，等待后续明确授权。

## 边界与验收

沿用 OBSERVE_ONLY 普通浏览器、现有 profile 和只读访问，不改浏览器版本或启动参数。登录需要用户正常操作时显示 WAITING_LOGIN；验证、拒绝或限流停止自动访问，不重试规避。

真实数据、审核原结果、页面截图、数据库、本机会话票据和模型 key 只在忽略目录/私有配置，不能提交 Git。公开报告使用计数和匿名分类。实际模型 HTTP 次数与预留额度分列；页面本机请求、站点事件、整机流量分别标测量范围。完整路线、地图、报价、KnowledgeCard 等不在本轮。
