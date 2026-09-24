# T06.1：私人本地正文缓存与真实研究验收

本次用户明确将项目定位为当前用户本人的私人、本机旅行研究工具，暂不公开发布或服务多用户。PRIVATE_LOCAL_RESEARCH 是用途决策，第三方权利 basis 仍为 UNKNOWN，不代表作者授权、平台授权或合规认证。原 UNKNOWN 禁止持久化的规则仍适用于未声明私人模式的旧策略。

## 明确的契约变更

SourcePolicy 增加 usage_mode、local_account_scope、source_content_retention。私人模式必须绑定一个本地账号范围和已记录的策略时间，禁止公共 export/embedding；当前实际不构建向量库。外部模型只接收研究正文块，不能接收浏览器会话或访问定位材料。

外发前再缩减输入：每篇最多 6,000 个规范文字字符、120 个原始块；包含链接、邮箱、手机号、身份证号或联系方式/住址标签的整块不发送。保留原始 block index 和 offset，不把替换后的文字伪装为原文引文。模型引用未发送的块会被拒绝；有省略时记录 MODEL_INPUT_MINIMIZED。外发字段仅为正文块及其 index/origin/truncation_risk、完整度和研究缺口，不附作者、账号、标题、source ID、图片或页面链接。检测是保守规则，不声称完整匿名化；不明示的姓名、个人经历仍可能在普通正文中出现。

默认正文保留 PERSISTENT；7_DAYS/30_DAYS 从快照首次 retrieved_at 算过期，读取前逻辑清理过期原文及正文块。EPHEMERAL 不写原文，但派生 Evidence 的保存仍由独立开关控制。期限到期或删除不声称清除了 SSD、备份的历史字节。再次读取同样内容只更新 last_retrieved_at，不偷偷延长原版本期限。

新增 SourceContent / SourceBodyBlock 内部契约，SQLite v5 通过 005_private_source_content.sql 增加 source_contents、source_body_blocks、research_run_contents。初始 database.sql 保持 v1 结构，依次迁移至 v5；OpenAPI 只补充边界说明，没有新增原文 HTTP 接口。迁移、契约、实现及相应测试共同提交。

## 数据流和版本

正常 detail、身份匹配 → 唯一 canonical 正文 → 有块定位的 Evidence → 事务写入正文快照、块和 Evidence。必须存在同一研究运行已预留的 DETAIL 操作；只拿到搜索候选、摘要或身份不一致不能保存原文。敏感材料在送模型前拦截，写入边界再校验；任何存储失败回滚整个 detail 的正文和证据。

raw_text 是 state 原文，dom_text 是存在时的 DOM 原文；normalized_text 是按现有保守规则选择的唯一正文，不拼接两份内容。保留 BodyBlock、origin、完整度、采集/发布时间、正文 hash 和 normalization_version=1，便于未来离线重新规范化。图片只保留数量和 IMAGE_NOT_ANALYZED，不保存图片 URL、图片字节或图像缓存。

内容 hash 基于两份原始文字表示；同 source/scope/hash 复用快照，不同 hash 新建快照，原文不覆盖。既有来源 Evidence 仍按 T06 规则保留，后续内容快照不会静默改写其旧定位或观点；显式重提取/重新评估是后续任务。定位审核按 hash 寻找对应的历史正文，不把最新版本文字套到旧 offset。

查询缓存仍在 connect 前。PRIVATE_LOCAL_RESEARCH 且需要保留原文时，恢复 Evidence 同时校验正文与正文块；新进程可独立恢复 report metadata、Coverage、正文与 Evidence。clear research cache 事务清理相同 scope 的研究记录、正文、块、证据、派生报告及现有 FTS 数据，不引用 ProfileStore 或 disconnect。

## 本次真实验收入口

模型已通过合成正文真实调用，不重新发送连通性探测。使用已验证的 json_object 配置，显式执行 scripts/private_research_smoke.py --live 才允许真实读取。固定问题“国庆从成都去川西玩”，预算最多 1 search / 3 detail，默认 OBSERVE_ONLY；充分即停止。具名独占账本 .local/t06.1-private/attempt.json 防止重启自动重试或重置访问预算。

正常登录需要人工操作时在同一 BrowserSession 等待，不重新导航；验证或访问限制直接停止。模型/输出 schema 失败停止继续实站读取，业务服务仍保留安全的本地摘取降级行为，但降级不能满足真实 G1。

SQLite 位于 .local/t06.1-private/research.sqlite3，原文、图片、认证数据不进入 Git。正常关闭保留 profile 和研究库。独立的 tools/private_cache_probe.py 不导入浏览器模块，并通过 Python audit hook 禁止网络；它以 0/0 预算恢复第一轮并验证五天/不自驾增量。原文不公开输出；提交的可读报告仅含少量有来源的短引文。

## 验证映射

tests/integration/test_private_source_content.py 覆盖 P01–P14 的私人持久化、候选限制、敏感材料、跨进程、缓存先于 connect、版本去重、变更快照、删除隔离、图片边界、定位、幻觉拒绝、malformed fallback、增量保留。既有 benchmark 继续检验矛盾、UNKNOWN、时效和候选关联边界。真实 G1 只按实测结果判定，不能用离线通过替代。
