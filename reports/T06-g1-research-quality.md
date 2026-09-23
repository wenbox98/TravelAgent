# T06：G1 研究质量与持久缓存

执行日期：2026-09-24。**离线实现与合成验收 PASS；真实 G1 = G1_LIVE_LLM_BLOCKED，未通过。G0 保留此前 PASS。** 本轮没有打开真实浏览器、连接小红书或调用真实模型，没有进入地图、酒店、报价、最终行程和 Electron。

## 1. 分支与基线

分支 `feature/xhs-research-quality`，基于 `365c5804efd7ce4c9b24e469665f69a9f48cfd9e` 新建。起始 log 包含全部指定 T05 提交：`3b743d1 / edd8a0c / 0210eb4 / 365c580`。

起始仅有三个旧未跟踪报告：`T03-login-smoke-test.md`、`T03.6-windows-chromium-diagnosis.md`、`T03.7-implementation.md`。原样保留，不纳入 T06 提交。完整阅读根 AGENTS.md、CODEX_START.md 和本轮请求，以用户新授权的 T06 范围为准。

## 2. 本地提交

| commit | 内容 |
|---|---|
| `da4969c076c4c6bdca8ceb4d381a20761a5688e8` | 区分请求尝试、阻断、放行、完成、失败及未测实际流量 |
| `a91fa477ee037c531c531574ed50b0d86f87123f` | SQLite v4 持久层、研究约束/报告元数据与显式质量契约 |
| `1c030a101cda7ca3a85812cc227253ccdfab87f4` | canonical 正文、严格 grounding、离散置信度、环境模型配置 |
| `d5a3202d386dcded27dd2125425c6bf597ab792d` | freshness、来源/冲突、方向关联、coverage 与可读报告 |
| `7a590e616c9a620418137aa95d920c93a114cb3b` | 24 场景 benchmark、跨进程验收、本地 CLI 和合成示例 |

本报告及设计/门禁文档另外作收尾文档提交；其 SHA 见最终交付和 git log，避免文档自引用自身哈希。没有 push、PR、merge 或修改旧提交。

## 3. Diff 摘要与主要符号

五个功能/测试提交相对 T05：43 files changed，3111 insertions，155 deletions。最终含文档相对基线的 diff stat：49 files changed，3328 insertions，169 deletions。

- `LiveNetworkObserver / LiveNetworkSnapshot / ResourcePolicyController`：八类资源的独立事件与本地策略计数、晚到结果归属、临时重复资源候选。
- `Database / EvidenceRepository / EvidenceStore`：v4 migration、`claim_metadata` 往返、`load_report` 策略复核、`clear_research_cache` 按 scope 事务删除。
- `canonicalize / BodyBlock / EphemeralSourceContent / EvidenceExtractor`：单一正文、带版本定位、限时原文引用、严格 schema/逐字引文、同源去重、旅行日期独立字段。
- `assess_freshness / evaluate_coverage / source_independence / evidence_conflicts / SufficiencyEvaluator / CandidateSelector`：时效、不同来源和条件、缺口、标题多样性。
- `ResearchReport / build_directions / render_material_report / ResearchService`：可追溯候选方向、缓存先于登录、增量 revision 保留材料。
- `QualityBenchmark / scripts/research_quality.py`：纯合成 benchmark、无访问的模型预检、独立研究缓存清理命令。

契约是 additive：`EvidenceBundle.claim_metadata` 可选；新增 `ClaimAssessment` 和运行时跨字段检查。数据库从 v3 升至 v4，旧初始 database.sql 仍为 v1，由迁移顺序升级。sidecar HTTP/OpenAPI 不变。技术设计见 [T06 设计](../docs/architecture/t06-research-quality.md)。

## 4. 实际测试与命令

Windows 本地 `.venv`，Python 3.14 系列；保持原依赖锁，未安装新依赖。

| 实际执行 | 结果 |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | **722 passed，0 failed，0 skipped**；2 条既有 Starlette/httpx/anyio 弃用 warning |
| 定位夹具和报告标点最后微调后的相关 4 文件重跑 | **63 passed** |
| `.venv\Scripts\python.exe -m ruff check .` | PASS |
| `.venv\Scripts\python.exe -m mypy` | PASS，37 source files |
| `.venv\Scripts\python.exe tools/validate_pack.py` | 12/12 文档/契约检查；最终链接数量见生成报告 |
| `.venv\Scripts\python.exe scripts/research_quality.py benchmark` | **24/24 PASS**；92 claim instances，unsupported=0，locator=100%，live=0 |
| `.venv\Scripts\python.exe scripts/research_quality.py live-preflight` | **G1_LIVE_LLM_BLOCKED / LLM_NOT_CONFIGURED**；退出码 2 是预期阻塞状态 |
| `git diff --check` 与各提交 staged diff 检查 | PASS |

过程中曾发现 legacy 无定位的测试期望遗漏 CLAIM_DIVERSITY，修正期望后全量通过；没有降低质量规则。某些低权限测试临时目录遇到 Windows ACL setup error，改正常用户权限执行同一离线测试后通过。所有测试默认禁外部网络；独立子进程另装 socket audit guard，禁止 connect/DNS/bind/sendto。

### Q01–Q22 对应覆盖

| 要求 | 主要执行证据 |
|---|---|
| Q01–Q02 跨进程/先缓存后登录 | `tests/integration/test_research_persistence.py`：独立 A/B PID，真实 SQLite，B 正预算仍不 connect |
| Q03 无 locator 拒绝 | `test_research_locator_boundary.py`、`test_claim_assessment.py`、`test_research_quality.py` |
| Q04 模型补造结论拒绝 | `test_evidence_extractor.py`；benchmark hallucinated_claim |
| Q05–Q06 canonicalization/完整度不升级 | `test_canonical.py`、`test_evidence_extractor.py` |
| Q07–Q09 同源去重/跨源/冲突 | `test_evidence_extractor.py`、`test_research_quality.py`；benchmark 重复与两类冲突 |
| Q10–Q11 PARTIAL/预算保留 gap | `test_research_planning.py`、`test_research_service.py`、`test_research_associations.py` |
| Q12–Q13 多样性/失败 fallback | `test_research_planning.py`、`test_research_quality.py` |
| Q14 无真实 LLM 可离线运行 | `test_llm_provider.py`、`test_research_benchmark.py` 与实际预检 |
| Q15 重要结论 lineage | `test_research_quality.py`、`test_research_associations.py`、benchmark quote/offset 逐条核验 |
| Q16–Q17 五天/不自驾增量 | `test_research_service.py`、独立进程 B 与 benchmark |
| Q18–Q19 清缓存/保留 profile | `test_research_store.py`：事务回滚、scope 隔离、profile 哨兵保留 |
| Q20–Q22 网络语义/blocked/未知 bytes | `test_live_observability.py`、`test_resource_policy.py` |

24 场景是可执行 expected/observed 断言，涵盖多方向、时长/交通冲突、源重复、缺时长、图片、单源概括、五天、不自驾、组合约束、缓存、零预算、幻觉、无块、日期分离、价格、陈旧材料、DOM 包含/冲突、多样性、模型排序失败、清理及 UNKNOWN 权限。不是把 24 个 prompt 计为质量通过。

## 5–6. 持久缓存与登录顺序

**PASS（合成、真实进程/SQLite）**：进程 A 使用完整 ResearchService + FakeReader/合成 extractor 完成 1 connect / 1 search / 2 detail，写入 2 sources / 8 claims 及完整质量元数据，正常关闭数据库并退出。这里的 connect/search/detail 是 Fake 调用，真实 XHS 为 0。

随后启动不同 PID 的进程 B：证据与 claim metadata 完整一致；正预算 1/2 和零预算 0/0 都恢复 EVIDENCE_SUFFICIENT、Report metadata 与 Q1–Q4 coverage，connect/search/detail 均 0。正预算用例证明阻止登录的是充分缓存判断，不只是零预算短路。B 再追加五天/不自驾，原证据仍完全一致，产生相应 gaps，仍 0/0/0。

读取原文和访问 locator 不参与持久缓存。跨进程验收只使用明确允许的合成来源，不声称真实小红书内容已取得持久化权利。

## 7–8. 真实模型与真实访问

本机 Process/User/Machine 三个环境范围内，`LLM_* / TRAVEL_LLM_* / OPENAI_*` 对应 base URL、key、model 的存在性均为 false。仅检查布尔存在性，没有输出值、读取 `.env` 或写入密钥。

真实模型请求 0；本轮 XHS connect/search/detail 全部 **0/0/0**，没有实际 query，没有扫码、浏览器导航或新 profile 操作。真实 smoke 因配置缺失没有启动，不使用 Mock 宣称通过。即使未来配置模型，UNKNOWN SourcePolicy 仍不能自动授权外部模型和持久化；本地预检会单独暴露该门禁。

真实最终 smoke 仍应另行继续：OBSERVE_ONLY，首次最多 search=1/detail=3；记录实际 query，挑战/限制即停止；增量及跨进程复用先用 0/0。历史 T05 CLI 仍保留其显式 TEXT_FIRST 测试用途，不能当作默认 T06 质量验收入口。

## 9–13. Evidence 与质量指标

| 指标 | 本轮真实数据 | 合成验收 |
|---|---|---|
| 新 Evidence | 0（未实测） | 示例 2 sources / 8 claims；24 场景共 92 次 claim 评估，非 92 个独立来源证据 |
| locator coverage | NOT_MEASURED | 100%，逐条短引文与 canonical body offset 核对 |
| unsupported claim | NOT_MEASURED | 保留结论 0；补造/错误 block 输出被拒绝，不计为合格证据 |
| contradiction | NOT_MEASURED | 示例 0；时长、交通两个专用场景各检出 1 对，保留双方，不取平均 |
| Q1/Q2/Q3/Q4 | NOT_MEASURED | 完整示例均 SUPPORTED；缺项、弱材料、跨方向错配、陈旧/未定日期保持 PARTIAL/UNSUPPORTED 和 gap |
| 来源独立性 | NOT_MEASURED | 两笔记仍为 UNKNOWN，confirmed independent=0；同源重复不多算票 |

这些指标验证逐字引用与来源关联，不声称已经证明作者内容真实、涵盖全部语义冲突或实际旅行可行。PARTIAL_TEXT 不因字符更长而升级 FULL；来源条件未写时明确未说明。旅行日期只有明确字段才提取，发表/采集日期各自保留；未来旅行日期不是历史经历。日粒度日期通过 UTC 零点承载，不假装实际时区/时刻已知。

## 14. 可读的大致研究输出

已生成 [完整合成研究示例](T06-synthetic-research-example.md)，每条材料都含 source/claim/block/locator、提取方式、置信等级、完整度、条件与独立时间字段。只输出资料支持的两个方向：

| 虚构方向 | 原文体验与时间线索 | 尚不能据此断言 |
|---|---|---|
| 青岚环线：雾谷、镜湖 | 湖畔步行；作者安排五天；历史材料提醒出发段需包车 | 对当前用户五天可行、不自驾已解决 |
| 苍原区域：溪台、草甸 | 草甸露营；作者停留两天；需核对班车 | 当前班次存在、用户交通已安排 |

每个方向只有一篇合成资料支撑，MEDIUM、PARTIAL_TEXT，独立性未确认。不凑第三项；未知预算不阻止先看方向。这不是川西真实攻略，本轮未生成任何未经真实模型和来源验收的川西建议。

## 15. 第二轮“五天、不自驾”

保留相同 2 sources / 8 claims，新增 `DAYS_FIT` 与 `NON_SELF_DRIVE`；本轮 0/0 预算以 BUDGET_EXHAUSTED 返回缺口，正文完整度提示仍保留。不会把某作者“五天”替换为“该路线适合用户五天”，也不会把包车/班车提及当成当前可用交通。独立进程 B 同样验证了这个行为。

## 16. TEXT_FIRST 修正后结论

**只能得出：TEXT_FIRST 尚未证明减少实际网络成本。不能由 request events 更多推断实际网络访问增加。** 默认继续 OBSERVE_ONLY。

attempted、blocked、allowed、completed、failed 均按 document/xhr_fetch/image/media/font/script/stylesheet/other 统计。allowed 表示应用没有拦截或 continue 成功，不保证实际到站。blocked 仍可出现在 attempted，不能算 allowed/completed。wire sent 和 transferred bytes 都为 null / NOT_MEASURED，无法从历史事件反推。

- **CONFIRMED（离线）**：上述事件/策略先后关系、blocked 进入 attempted、晚到完成归属、同请求去重均有 Fake 事件测试。历史不同页面/窗口非严格配对。
- **LIKELY**：本轮没有新的实站依据将任何资源原因升级为该等级。
- **UNKNOWN**：真实 retry、lazy-load fallback、额外 xhr/fetch 因果、Service Worker、实际 wire 与 bytes。临时 HMAC 重复资源候选只是 DERIVED，query 被排除，不等于确认重试。

本轮没有进行后续实站资源成本实验，原因是用户要求真实 G1 等待真实 LLM；该项标 BLOCKED，不能记成已验证。详情见 [网络口径](../docs/architecture/t06-network-metrics.md)。

## 17–19. 门禁、风险与下一步

**G1：NOT PASS（BLOCKED，G1_LIVE_LLM_BLOCKED）；G0：仍 PASS（沿用已接受的 T05 实测，未扩大范围）。** 离线质量和持久缓存已通过，不据此标 D1 或真实 G1 PASS。

本轮修复的新问题包括：动态信息有效期误当核验、UNSUPPORTED 进入方向、DOM-only 内容边界、未来旅行日期误判、不同路线借时长、共享条件块错当主引文块、legacy 证据误计主题覆盖。对应回归已通过。

仍有明确限制：词法关联/冲突规则有限；真实页面 canonical 差异尚未重新实测；旧 source immutable 缓存没有自动刷新接口，过期后会保留 gap，不能把旧资料重新标新鲜，需要未来设计有版本的刷新；180 天仅为稳定资料复核策略；clear-cache 为逻辑删除，不是备份/取证擦除。未知用途权利不会被代码补造。

安全检查：完整 security 测试通过；新抽取、metadata、store、provider 测试拒绝敏感 sentinel/访问材料，未发现新增泄漏。本轮没有接触真实 Cookie/session/token、账号标识或二维码，也没有平台主动写操作。登录 profile 未读取内容、未删除，研究缓存清理通过独立哨兵验证不触碰 profile。

下一步应先在本机配置真实模型，并明确允许的来源用途，再执行一次 1/3 的受控 G1 人工质量验收、0/0 增量及真实允许资料的跨进程复用。资源成本配对实验仍待受控安排，不承诺 TEXT_FIRST 有效。**本轮到此停止，等待用户确认；不进入地图、酒店、报价或完整行程。**
