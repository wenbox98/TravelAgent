# T06：有依据的研究结果与持久缓存

本阶段范围以本轮用户任务为准：G0 已通过，补足 G1 离线质量与持久缓存。没有模型配置时为 `G1_LIVE_LLM_BLOCKED`，合成 benchmark 不替代真实验收。不进入地图、酒店、报价、最终行程或 Electron。

## 数据与契约

SQLite 运行时迁移至 v4，初始 `contracts/database.sql` 仍是 v1 基线，后续升级必须依次应用 migrations。新增 `research_constraints`、`research_reports` 和 `sources.claim_metadata_json`；来源、证据、定位、研究问题、运行、缺口沿用既有表。没有引入向量库。

`EvidenceBundle.claim_metadata` 是可选的 additive 契约字段，以 claim ID 关联 `ClaimAssessment`：块编号、块定位、正文来源、提取方式、简短依据、离散置信等级、原文条件、canonical 关系、截断风险。运行时另核验 ID 归属、引用范围、同一正文哈希、等级与兼容数值一致性。旧记录没有这些字段仍能读，但不能冒充新评估证据或关闭 coverage gap。没有 locator 的新结论拒绝进入研究 store。

来源 ID 是长期身份，访问所需 locator/token 不成为身份或持久缓存字段。存储的是短引文与其哈希/字符定位、可审查来源条件和元数据，不是原始正文。图片、Cookie、会话、带 token 的 URL 不进入 SQL、模型、报告或普通日志。原文只在本轮内存中用于抽取；`EphemeralSourceContent` 最多 300 秒使用窗口，过期读取与 finally.close 释放所持引用。这是引用生命周期，不声称 Python 内存被安全擦除；抽取期间的局部字符串在调用结束后释放，不建立原文磁盘缓存。

SourcePolicy 在写入、查找、报告恢复及外部推理前分别复核。UNKNOWN 不因登录成功而获得持久化或外部模型权限；合成资料用 SYNTHETIC 策略。策略撤回/到期后，旧报告内容不能绕过证据权限直接复活。保存的报告是匿名摘要、研究请求与 source/claim handles，恢复时从当前允许的 Evidence 重建正文、freshness、coverage，而不是信任旧充分性结论。

`clear_research_cache(account_scope)` 事务删除研究运行、问题、约束、缺口、操作、snapshot、证据、来源、派生报告及关联 chunks/FTS/lineage。其他 scope 不受影响。保留策略审计定义；浏览器 profile 的目录和 API 完全不在该调用中，登录生命周期仍由 disconnect 管理。这是逻辑删除，不宣称删除备份或进行磁盘取证级擦除。

## 单一正文与抽取

state/DOM 先 NFC、换行/空白标准化，再比较 EQUAL、单侧存在、包含、OVERLAP、CONFLICT。包含时选择包含另一方的正文；部分重叠或冲突时保留 state 单一候选，不拼接两份正文。字符更长不是 FULL_TEXT 的证明；不确定时降级 PARTIAL_TEXT。此阶段不增加展开、滚动或网络请求。

`BodyBlock` 含 block index、normalized text、origin 与 truncation risk。新 locator 为 `note-body:v2:<origin>:<sha256>:chars:<start>-<end>`，指向当时唯一 normalized body，不能拿后来网页文本套用旧 offset。仅保存短引文和块范围，因此离线可审核引文与提取记录，不能重建已丢弃的整个正文。

真实 provider 使用环境中的 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`，兼容原 `TRAVEL_LLM_*` 与 `OPENAI_*`；不读取 `.env`、不打印 key。一次请求使用 JSON Schema structured output，无自动 HTTP 重试，无 ambient proxy 或重定向。外部模型仍需 SourcePolicy 允许。

每条模型结果必须有 claim、quote、topic、kind、source_block_ids、条件引用、LOW/MEDIUM/HIGH 与简短 extraction_basis。沿用现有 `kind=AUTHOR_OPINION` 表示 claim_type，不能把作者观点升格官方事实。claim 必须等于原文短引文，并在指定块中逐字出现；条件也必须有逐字引用。无效 block、正文没有的时长、图片中的猜测及无来源条件均拒绝。模型给出的依据不原样存储，程序生成短核验说明；不保存隐藏推理。

置信度固定映射 LOW=0.25、MEDIUM=0.6、HIGH=0.8，只为兼容既有数值契约，不是概率。模型只能提出等级，程序施加上限：本地摘取/明显正文冲突 LOW，PARTIAL_TEXT 至多 MEDIUM，FULL_TEXT、无截断风险且条件有引用才可能 HIGH。点赞不参与真值置信度。模型不可用仍可保守本地摘取，但不会通过 G1。

同源用保留否定和条件的标准化键去重，包括五天/5天；跨源仍保留每个 claim 的身份，通过 ClaimCluster 对照。不同笔记 ID 不证明独立，`confirmed_independent_sources` 默认 0；大量相同引文只标可能转载。对相同明确路线/时间的相反体验产生 POTENTIAL_CONFLICT，不平均成中间结论。此规则只覆盖可解释的有限词法模式，不宣称识别所有语义冲突。

## 时间与充分性

旅行日期、发表日期、采集日期分别保存。仅独立字段行 `旅行日期：YYYY-MM-DD` 的唯一合法日历日期可以自动归一化；使用契约 date-time 的 UTC 零点承载日粒度值，不代表观测到具体时刻或时区。发布日期绝不充当旅行日期；其他时间表达仍需后续受引用约束的解析。

| 类别 | 当前语义 |
|---|---|
| STABLE_EXPERIENCE | 稳定路线/风景参考；采集后 180 天是应用复核间隔，不保证事实 180 天不变 |
| TIME_SENSITIVE | 交通/季节/拥堵等有实际旅行日期时只能作为历史体验；未知日期不能证明当前适用 |
| HIGHLY_DYNAMIC | 票价、营业、预约始终需当前核验；作者写了有效期也不代表供应商已核验 |

Q1 路线、Q2 体验、Q3 时长、Q4 限制分别标 SUPPORTED/PARTIAL/UNSUPPORTED。SUPPORT 表示该研究问题有可定位的直接材料，不表示行程可行或真实事实已被独立证实。充分性要求四项核心 coverage、至少两个没有被已知重复规则合组的来源、至少三类 grounded 主题、没有关键图片/冲突/追加条件 gap；两篇或六条本身不是充分条件。来源独立性未知仍在报告公开，不夸大成“多方证实”。预算不足则保留 gap。

候选仅使用实际得到的 title/type/identity/detail availability；没有摘要就不制造摘要。先确定性相关性排序，再用标题相似度选出多样候选。可选模型排序输出非法时退回同一确定性结果。

候选方向只从 grounded ROUTE 引文产生，不强凑三项。体验/时长/限制只在明确方向文字一致或同一无歧义正文块时关联；同段出现多个方向时不把全部体验分配给每条路线。报告每个重要材料结论带 source、claim、block、locator、完整度、条件与时间；派生 coverage、冲突与缺口另标。未提供预算不阻止粗略研究。五天/不自驾只新增适配性问题，不把用户愿望变成证据。

## 缓存与本地入口

`ResearchService.run` 顺序为 begin/策略复核 → EvidenceStore.lookup → 当前时效与充分性计算 → 必要时才 connect。缓存足够即使正搜索预算也不连接；零预算无论是否充分都不连接。新进程从 SQLite 恢复证据与质量记录，增量 revision 保留已有证据。

开发者本地入口为 `scripts/research_quality.py`：benchmark 使用合成资料；live-preflight 仅检查配置与门禁，不打开浏览器；clear-cache 按指定 SQLite/scope 删除研究缓存。实际参数见 `--help`。真实 smoke 未授权绕过来源策略，不能把合成演示当真实攻略。

T06 的 network 口径见 [专页](t06-network-metrics.md)：attempted、应用 blocked/allowed、completed/failed 分离，wire/bytes 未测保持 null。默认 OBSERVE_ONLY；历史 request events 不支持“TEXT_FIRST 增加实际网络访问”的结论。

执行结果、Q01–Q22 映射和未验证项见 [T06 报告](../../reports/T06-g1-research-quality.md)。
