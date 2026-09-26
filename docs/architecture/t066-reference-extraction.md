# T06.6：片段选择、程序物化与独立上下文审核

基线 df9ab5e9f0e8e82e25a12950c0bd379f20b30aba。仅处理原 T06.5 两个缓存快照；小红书与浏览器零调用。旧 extraction v2、失败、审核与六条 Evidence 不重写。

## 协议和定位

`references.catalog` 复用 canonicalize/BodyBlock，先执行 outbound_blocks 的原过滤、6000 字/120 块上限，再按句界切分，不静默截断。每片最长 120 字，足以适配既有条件上限；长句分片保留父段绝对范围与 context_required。原文只外发一次，父段原文不重复发送，省略块无 ID。完整块未发送时，不通过父段上下文补发。原 BodyBlock 编号、normalization v1 和快照 hash 不改变。

span ID 绑定 source/content/hash、canonical hash、版本、块号和准确范围；程序保存本次目录摘要与所选映射。`extraction_version=3`、`prompt_version=reference-selection-v1`、`reference_version=1`；既有逐字规则仍为 grounding v2。模型仅返回 topic、statement_span_id、condition_span_ids、proposed_reference_kind，最多 12 项。runtime 按任务选择新指令，不再套用 claim=quote 的旧模型提示。

`materialize` 严格匹配白名单，从 snapshot 精确切片并推导引用并集。陌生、跨源、跨快照、未发送 ID 逐条拒绝；schema/传输异常不能通过降级回填变成成功。条件并集合法只证明机械一致性，随后仍进独立 Work-assisted 上下文审核。重复原文使用已选 offset；build_claim、审核、落库及 audit_grounding 都验证权威映射，不回退到首个 index。新增审核条件和路线对象也只允许目录 ID。

ClaimAssessment 新增可选 reference_selection、duration_scope，并扩展 reference_scope。proposed_reference_kind 永不自动成为 reference_scope；明确核对主体、否定、假设、时间、交通、scope、来源性质和图片后才能接受。保留已拒依赖检查。AUTHOR_PROPOSED_PLAN、GUIDE_SUGGESTION、UNKNOWN 均不证明实际行程/当前可行性，不能让既有 Coverage 自动变绿；DAY_SEGMENT 不作为总天数。AUTHOR_RECORDED_TRIP 仍需确有作者已完成经历的原文锚点。G1 定义不改。

## 追加额度、兼容与恢复

SQLite v10 只扩展既有 extraction_authorizations 的固定 ID 约束，容纳本次两条各一次、绑定原 content_id/hash/normalization/修复 SHA/原配置的追加授权；没有新增业务表或泛化权限框架。迁移在单事务中保全旧三张相关表的全部行与外键。授权原机制 reserve_extra 原子消费，attempt_number=3、extraction_version=3；不改变普通批次上限、旧已用额度或 T06.4 追加记录。重复启动/换 run_id 不恢复额度。

入口仍是 retry_extraction.py：`--grant-extra --reference-source S2|S3` 只在本地登记，`--live --extra-authorization --reference-source S2|S3` 才预留并派发。原 DeepSeek host、模型、json_object 和配置须与 T06.5 一致，120 秒传输等待/180 秒监督截止。自有 worker 正常退出或截止后回收；网络、策略、存储失败或前一篇未完成审核会阻止下一派发。最多两请求，每篇一次；无连通性探测/模型审稿/报告请求。

沿用已有研究、候选区和 SourceContent，没有为新阶段复制真实来源成新批次。新尝试另存，严格同源、同定位、同文本与条件/角色/关联的重复证据可复用旧对象；新候选的映射和审核仍留下，旧证据不覆盖。同源抽取多次不增加独立来源票数。

跨进程禁网恢复沿用 private_cache_probe，重新检查非空 Evidence、片段和定位、条件、角色、审核以及报告。追加五天/不自驾只更新偏好，不能改写作者计划，也不补造公共交通或实际天数。真实正文、数据库、模型候选和私人可读内容不提交 Git。
