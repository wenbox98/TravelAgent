# T06.2：安全诊断与正文先保存

本次是显式契约变更：领域 schema 新增 `LLMDiagnostic`、`ExtractionAttempt`；SQLite 从 v5 升至 v6，保留旧表，新增提取批次和尝试记录。OpenAPI 仅注明内部持久模型变化，没有新增公网接口。历史 T06.1 的 961 字正文已经丢失，根因仍为 UNKNOWN，不从报告重建。

## 事务边界

`ResearchService` 先用 `EvidenceStore.save_source` 独立提交来源元信息、SourceContent 和 BodyBlocks。空 claim 的来源占位记录不会进入 Evidence 查询。保存失败立即停止，模型不调用。再由 `ExtractionRecovery.execute` 独立提交 PENDING、RUNNING，调用模型后校验 final content、schema、grounding；全部通过才保存 Evidence 和 SUCCEEDED。失败保存 FAILED 和安全诊断，已提交正文不回滚；报告失败也不影响前面的来源和 Evidence 事务。

取消记 INTERRUPTED；硬退出可能留下 PENDING/RUNNING，这些状态仍计入额度，不能当作未派发而自动重试。旧 revision 晚到结果只能记 OBSOLETE，不保存 Evidence。完整度和 normalization_version 随原快照保留，不因模型成功升级。

## 仅重跑模型

`scripts/retry_extraction.py --live --database <本地库> --attempt-id <已保存尝试> --fix-commit <完整修复SHA>` 从旧尝试定位原 content_id、source/hash、规范化版本、提取版本、账号范围、当前策略及批次额度。仅接受仍有效的原 revision。没有 XHS/browser 导入、connect、search 或 detail，也不需要原访问 token。

批次额度存于 SQLite，重启不可改变；全批次最多一篇重试一次，必须给出已记录修复的完整 SHA。已成功内容直接命中，不重复造正文版本或 claim。操作者负责确认该 SHA 确实对应原因明确的修复；程序校验其格式并记录，不替操作者声称已做代码审查。

## 安全诊断

兼容原简短 LLMError code，同时传递 Diagnostic 到 Extractor、Recovery、ResearchReport。状态/原因/finish_reason/validator 均使用允许名单；schema 路径只保留可信 schema 的属性和整数索引。服务器 request id 和模型名额外受格式约束。未知字段为 null，不打印异常文本、ValidationError、请求/响应、headers 或 reasoning_content。

`provider_called` 表示进入 provider，`http_attempts` 表示调用 HTTP opener 的派发尝试，不等于线上的请求或服务器接收计数。schema 和 grounding 分开记录；零合格 claim 时定位覆盖率为 null，质量不算通过。生成/逐字审核/拒绝/接纳为程序检查数，不代表用户人工审核。

## 验证边界

T06.2 合成样本文字自编，1379 字/16 块，经同一 SourceContent、真实 extract_evidence、schema 和 grounding 路径，固定账本最多两次；第二次须明确修复。真实资料入口 `private_research_smoke.py --live --t062` 必须先检查合成验证通过，独立保留历史失败记录。固定 1 搜索/3 详情/4 模型尝试，每篇落库并成功提取后暂停，Work 逐条复核后才能继续既有候选。失败停止后续读取，正常关闭保留 profile/研究缓存。

本地 HTTP/跨进程回归用合成内容，显式禁止外网；真实测试只用现有 DeepSeek 配置。当前 [DeepSeek Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/) 列出 text/json_object；json_object 只保证 JSON 格式，仍须提供 schema 并在本地校验。T06.1 当前代码在失败前已用 json_object，不能把更早 json_schema 实现认定为历史实测根因。
