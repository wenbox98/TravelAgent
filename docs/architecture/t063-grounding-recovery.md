# T06.3：逐条 grounding、上下文审核与部分恢复

本次显式调整 T06.2 的整批接纳规格，SQLite v6 → v7、提取规则 v1 → v2，正文规范化仍为 v1。原 `FAILED` 尝试及其计数不改写。历史未保存的模型输出无法恢复；本轮新请求的结果单独记录。

## 严格定位与上下文分开

`grounding.check_grounding` 返回候选索引、pass/fail、稳定原因、原块号和规则版本。保持 `claim == quote`、指定块内精确子串、条件逐字匹配及引用块集合一致；未发送块、重复或多余块分别拒绝。Unicode/空白仅使用既有 canonical 规则，不做模糊匹配、数字或标点替换。过滤不会重编号。

定位通过只表示片段存在。新 source-first 提取全部进入候选区，不能直接进入 Evidence/Coverage。明显截掉否定前缀的片段提前拒绝；其他片段仍须 Work 对主体、否定、假设、时间、交通、范围、来源类型、图片八项显式核对。此小型检查器不能普遍证明语义正确，Work 核对也不是用户人工验收。

`candidate_review.review_candidates` 接纳时再次校验原账号范围、revision、策略、content_id/hash、规范化版本、定位和全部来源关系。可添加原文中逐字可定位的必要上下文条件，不能删掉模型原条件。与被拒条件共享块的候选，默认隔离；只有 Work 明确确认独立后才能接纳。不能确认的条目保持 PENDING 或拒绝，不生成可行性结论。

## 状态和事务

| 状态 | 意义 |
|---|---|
| PENDING_REVIEW | 有待审核候选，尚无接纳证据 |
| PARTIAL_SUCCESS | 有独立合格证据，仍有拒绝或待审候选 |
| SUCCEEDED | 本次所有候选已接纳；不等于 Coverage 或 G1 通过 |
| NO_ACCEPTED_EVIDENCE | 候选全部拒绝，没有可用证据 |
| FAILED | 顶层 JSON/schema、策略、敏感污染或快照等整批错误 |

来源先持久化，再提交尝试额度，最后发送模型。v7 新增 `extraction_candidates` 私人审计表，保存必要候选 claim/quote/conditions、枚举定位结果和审核决定；不保存响应包、reasoning、headers 或自由异常内容。其生命周期由原 source_contents → extraction_attempts 外键级联管理，清研究缓存连同私人候选删除，不涉及浏览器 profile。本轮不清真实快照，仍为 PERSISTENT。

Evidence、完整来源/条件关系、候选接纳状态和 attempt 结果在同一个事务提交。报告生成与保存随后执行，不能回滚已经接纳的 Evidence。被拒条件导致整条候选拒绝，不能只删条件后保存结论。重复接纳保持 claim ID 幂等；改写已审核决定不被允许。

批次尝试编号不再按 extraction_version 分组：同一 content_id 不能切换批次，原批次上限与最多一次额外重跑持续生效，升级规则或新建研究 run 不能重置。PARTIAL_SUCCESS/PENDING_REVIEW/SUCCEEDED/NO_ACCEPTED_EVIDENCE 重放直接恢复，不自动重跑被拒项。

## 仅模型与仅审核入口

沿用 `scripts/retry_extraction.py --live --database ... --attempt-id ... --fix-commit <完整SHA>`，只接受已配置的 api.deepseek.com；脚本 DNS/connect 限定该主机的 HTTPS 地址，禁止 XHS/Playwright 导入。程序记录实际派发次数和安全诊断；这些不是抓包或服务器接收量。

`--review-stdin --account-scope ...` 从标准输入接收受控审核决定，不初始化模型，禁止全部网络。候选正文仍在私人 SQLite 中，标准输出只含枚举、数量、块号和本地标识。审核决定可附必要逐字上下文，写入同一受管审计表，不另建无限期原文副本。

领域契约分别记录 generated_candidates、locator_passed_candidates、rejected_candidates、context_review_pending、persisted_evidence。报告另计 published_important_claims、unsupported_published_claims；空发布的 unsupported 为 null。旧 LLMDiagnostic 的 accepted_claims 是定位通过数，不是最终 Evidence 接纳数。PARTIAL_SUCCESS 必须与 Coverage 同时看，不能被等同完整通过。

本轮不重写旧直接 extractor 的定位结果接口；新 source-first/恢复路径必须经过上下文审核才能发布。旧的合成直接调用仍只用于定位测试，不能据此宣称自动语义审核通过。

## 恢复及边界

独立进程禁止网络，验证非空 Evidence ID/hash/引文/条件、源快照和块完全复用。增量“五天、不自驾”仍保留历史材料，同时显式形成时长与交通缺口；保留自驾经历不表示不自驾方案成立。材料视图标明新增条件的适配尚未确立，私人输出提醒原文只是作者经历。

全量测试采用自编材料，覆盖部分成功、整体拒绝、依赖、否定、规范化、v6 迁移、跨进程恢复、原子回滚、过期 revision、账号隔离、缓存删除、安全诊断和原批次额度。本轮真实验证只允许缓存的那一篇、最多一次模型提取；XHS、浏览器及模型连接测试均不执行。实际结果见随后独立提交的 T06.3 报告。
