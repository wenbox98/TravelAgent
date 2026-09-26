# P02：本机有限研究工作台

执行日期：2026-09-26。指定基线 `a3e047492dff25345902e8094bab70576e50b127` 已核实为祖先。功能分支 `feature/g1-live-llm-validation`；没有合并 master。P02 受控开发预览已运行，真实新增非空材料闭环通过；资料质量仍为 PARTIAL，历史 **G1 NOT PASS** 不变。

## 分项结论

| 子项 | 实际结果 |
|---|---|
| P01 保护、独立副本与 v12 迁移 | PASS：原库/P01 全表摘要一致，旧 25 条/3 来源/73 块及选择保留 |
| 普通新资料 v3 接线 | PASS：页面 → API → worker → ResearchService → 监督提取实际使用 v3 |
| A 两篇缓存自动审阅 | PASS（仅本批有限门槛）：11 条条件参考、13 条待审；五类旧风险未放行 |
| B 页面主动研究 | PASS：一次页面动作，connect/search/detail 各 1，提取/审核各 1 |
| B 自动审核后的材料质量 | PARTIAL：12 条定位通过；4 条独立参考入库、8 条待审、0 条拒绝；未新增可执行路线 |
| 自动入库、提示与显式采用 | PASS：无需 Work 写 ACCEPT；页面 25→29 条、3→4 来源 |
| 预览/取消/确认/刷新 | PASS：实际浏览器操作，最终恢复原兴趣；5 天、不自驾保留 |
| 非空跨进程恢复 | PASS：29 条、4 条模型审核引用及条件、选择和账本一致，外部尝试 0 |
| 预算及清理 | PASS：模型 4/4、搜索 1/1、详情 1/1、connect 1/1；关闭许可，profile 保留 |
| 完整五天非自驾行程/当前可行性 | NOT PASS：仍有交通、时长、季节、图文和对象关联缺口 |

## 实现与契约

- `research/extractor.py::EvidenceExtractor` 普通默认改 v3；`recovery.py`、`retry.py`、`scripts/retry_extraction.py` 沿用已保存协议版本，历史 v2 不重解释。历史工具和 fixture 显式固定 v2，未运行额外真实连通性检查。
- `research/context_review.py::{build_input,check_decision,reserve_review,run_review}`：独立 schema/任务；模型只提出片段 ID、角色、时间范围、关联、依赖和简短审核依据。程序重建引文/定位，检查同源/快照/scope、必要条件、父段前提、revision、策略和重要事实边界。正文去重过滤，最多 6000 字，不发送历史 Work 标签/理由/统计答案。
- `research/candidate_review.py`、`quality.py`、`persistence/repositories.py`、`preview/service.py` 增加绑定审核流水的 `MODEL_CONTEXT_REVIEWED`。历史 `WORK_REVIEWED` 保留；待审、拒绝和无有效审核链记录不展示为可用材料。运行时逐条提交，独立合格项不因其他失败丢失。
- `research/bounded.py::BoundedBudget` 复用 continuation 账本，统一限额、来源去重、scope/供应商/数据库路径绑定。失败消费保留，重启不重派，同许可第二个幂等键也不能创建第二个研究任务。
- `preview/jobs.py::JobService`、`workbench_api.py`、`worker.py::run_job`、`scripts/live_workbench.py` 提供主动任务、取消、恢复和显式采用。源正文先落库；单次模型复用原 120 秒 HTTP 等待、180 秒总截止和独立监督子进程。
- Vue `ResearchPanel.vue` 展示用途、预算、任务、部分结果、待审数及采用动作；`EvidenceList.vue` 可展开区分历史 Work 与模型审核。GET/状态/刷新/条件与兴趣修改只走本机，保留 Host/Origin、HttpOnly、CSRF、scope、revision 和幂等校验。
- SQLite migration 012 泛化原 continuation 表并原样复制旧行，增加 `context_review_runs` 与 `preview_jobs`。ClaimAssessment、工作台/任务 DTO、审核 schema、OpenAPI 同步；71 个 schema 定义、28 个 HTTP operation。详见设计文档。

## A：真实缓存对照

| 匿名来源 | 必要正文字符/片段 | 定位合格候选 | 评估接纳 | 待审 | 拒绝 | 新增 Evidence |
|---|---:|---:|---:|---:|---:|---:|
| S2 | 685 / 23 | 12 | 3 | 9 | 0 | 0 |
| S3 | 1013 / 38 | 12 | 8 | 4 | 0 | 0 |

两次均为隔离 EVALUATION，不改写旧候选、25 条 Evidence 或历史拒绝记录。评估接纳数不等于运行时已入库数；实际采用仍须通过仓储依赖检查。Work 只比较和记录门槛，没有给新候选写审核决定。

S3 保留四个条件明确的攻略日段和低风险观景参考；保留季节、自驾、日段/地点关系，角色为攻略建议，未确认作者亲历。S2 保留计划性质和电车前提。五类旧风险——混合过去/未来交通经历、天气提问、宽泛季节保证、运营接驳指令、绝对医学建议——全部仍不可采用；模型本轮选择待审而非拒绝，不改写历史拒绝。

已解释的差异：S2 四条 ROUTE 被模型填为 DAY_SEGMENT，与当前仅 DURATION 可填写该字段的程序契约不符，保留待审；另外三条因未解决的路况/天气/拥堵提问而更保守。S3 一条景观因接驳依赖待审；一条日序评估提议关联的对象没有独立 ROUTE 锚点，若用于运行时仍会被仓储依赖检查拦截，不能把评估计数当作可入库数量。局部短线/返程的条件较旧 Work 增补范围窄，但对应日段对象保留总体季节/自驾条件；没有升级为当前运营保证。

A 达到附件最小安全与可用性门槛后才开启 B。这是两篇已见资料的有限对照，不是全域准确率或独立权威事实核验。

## B：真实页面与新材料

实际在 Edge 的 `http://127.0.0.1:8766/` 点击一次“补充研究（最多读一篇）”，API 创建唯一任务，后台自动执行。根据原已选方向及五天、不自驾条件生成一次缺口查询，不将不自驾等同仅公交。

正常 profile 复用，无扫码/verification/拒绝/限流阻断；创建 1 个 BrowserSession。OBSERVE_ONLY；取得 20 个搜索候选，确定性选择 1 篇新的公开图文攻略，正文过滤后 663 字、24 片段。完整度仍 PARTIAL_TEXT，图片未分析。模型提取生成 12 条，全部定位通过；独立模型审阅及程序复核后：

- 4 条景观/兴趣参考独立入库，角色 GUIDE_SUGGESTION，未确认亲历；原季节与相关路面条件保留，不能据此确认当前到达方式或活动开放。
- 6 条路线/日序候选因 DURATION_SCOPE_MISMATCH 待审。
- 2 条因 UNVERIFIED_IMPORTANT_FACT 待审。
- 没有新增合格路线/整程耗时/非自驾可行性依据，没有 Work 后台人工 ACCEPT，没有重新模型提取或审核。

任务 PARTIAL，页面自动显示新增 4、待审 8、拒绝 0。点击“采用新材料”后，通过真实 API 投影得到 29 条/4 来源，保留原有 5 个草案/日段对象；新条目在“其他兴趣线索”中，不跨来源拼接路线。展开引用审核可见“模型上下文审核 + 程序引用复核；未核实当前事实和可行性”。

实际操作：采用 → 展开新资料审核/条件 → 预览另一日段 → 取消（原兴趣不变）→ 再预览并确认（保存新兴趣）→ 再确认恢复原兴趣 → 刷新 → 替换 P02 服务进程 → 刷新恢复。最终原兴趣、5 天/不自驾、未知预算/人数/包车偏好均保留。未触发第二次研究。

## 持久化、恢复与进程

原库 `.local/t06.2-live/research.sqlite3`、正在使用的 P01 `.local/p01-preview/preview.sqlite3` 全表行数及摘要与开工一致。P02 从当前 P01 工作副本 online backup，并保留 `.local/p02-preview/before-v12-from-v11.sqlite3`；只迁移 P02 到 v12，不每次启动覆盖。42 张历史业务表的既有行原样保留，旧预算、失败、审核不重置。

P02 最终 `.local/p02-preview/preview.sqlite3`：29 条 Evidence、4 份正文、97 个 BodyBlock；其中原 25/3/73 原样存在。新模型审核 4 条均有原文定位、片段引用与条件。真实来源、模型提议、对照详情、完整 API 投影与本机票据只存 `.local/p02-audit` / `.local/p02-preview`，不进 Git。

研究完成、浏览器关闭后，验收中仅停止并替换已核实属于本轮的 P02 服务进程；这是服务进程重启，不是 disconnect，未删除 profile。两个独立恢复探针进程核对完整投影、审核记录、任务和账本相等，并禁止 socket/connect/DNS：外部尝试 0。实际页面重启恢复非空新材料；没有自动任务重派。

保留用户原 P01 listener PID 26740（8765）；本轮 P02 重启后 listener PID 27100（8766，parent 43312）。模型/研究 worker 与 XHS 浏览器均结束；明确保留这两个 loopback 页面服务供查看，不宣称所有进程为 0。profile 仍存在，本轮没有 disconnect。

## 调用与测量范围

环境：Windows 11 build 26200，Python 3.14.7，Playwright 1.63.0；未改变浏览器配置/版本。既定接收方 `api.deepseek.com`，请求模型 `deepseek-v4-flash`，响应模型（已保存成功诊断）`deepseek-flash`；json_object，本轮未换模型。HTTP 等待 120 秒，单次外层 180 秒。

| 操作 | 实际派发 / 上限 | 剩余 |
|---|---:|---:|
| XHS connect | 1 / 1 | 0 |
| XHS search | 1 / 1 | 0 |
| XHS detail | 1 / 1 | 0 |
| 模型：缓存上下文审核 | 2 | — |
| 模型：新提取 + 新审核 | 1 + 1 | — |
| 项目外部模型合计 | 4 / 4 | 0 |

四个模型 HTTP attempt 均各 1，HTTP 200，retry_count 全为 0。完整正文读取耗时依次 99.4311、117.4642、34.3305、85.9171 秒；相应 response bytes 为 96601、115873、33380、89447，这是 provider 实际读取的响应载荷大小，不等于 wire bytes。未保存原始模型响应或隐藏推理；只保存结构化审核提议、白名单诊断及候选。没有额外连通性、排名、总结、embedding 或审稿调用。

S2 首次审核暴露诊断落盘遗漏：最后 transport checkpoint 在 envelope/schema 完成前，导致默认 INTERNAL/UNEXPECTED_ERROR 与 COMPLETED 结果不一致。已修复最终诊断保存并回归，后续三次诊断正常。S2 原记录未改写，最终 finish_reason/response_model/最终 provider elapsed 是 NOT_MEASURED；完整读取时间、HTTP 次数、响应 bytes 和完成审核结果有实际记录，不凭空回填成功字段。

| 站点观测窗口 | 导航请求事件 | 请求事件 | 完成 | 失败 |
|---|---:|---:|---:|---:|
| LOGIN | 1 | 194 | 194 | 0 |
| SEARCH | 3 | 180 | 152 | 26 |
| DETAIL_1 | 1 | 191 | 183 | 8 |
| OUTSIDE_WINDOW | 0 | 35 | 35 | 0 |
| TOTAL | 5 | 600 | 564 | 34 |

以上来自既有 context request 事件观察器；导航事件不是业务搜索调用数。TOTAL 还有 2 个未结束请求事件，未算成功/失败。OBSERVE_ONLY 未阻断请求；真实发送次数、wire/transfer bytes 为 NOT_MEASURED，不能把 600 当实际出网次数，也不宣称低请求策略已达成。浏览器在模型等待期间仍有 OUTSIDE_WINDOW 事件，不能说研究任务等待期间整机零网络。只读业务没有点赞、评论、发帖或私信；页面自身 POST/分析请求不能混称业务写入，也不能谎称全部 HTTP 为 GET。

缓存浏览、状态查询、偏好/选择操作、采用、刷新和恢复均不派发新业务外部调用；计数和额度保持不变。离线测试的模型 HTTP 是合成本机 stub，不计入真实 DeepSeek 四次。GitHub 同步是项目外独立网络行为。

## 测试与已知问题

执行命令：`.venv\Scripts\python.exe -X utf8 -m pytest -q`；`-m ruff check apps/api scripts tools tests`；`-m mypy`（沿用仓库配置）；`npm run build`（apps/web）；`tools/validate_pack.py`；`git diff --check`。

离线测试覆盖普通 API/service/监督子进程 v3、历史 v2、片段/快照/scope/策略错误、计划/否定/提问/未亲历/过去未来/日序/重要事实、逐条保留、超时与原文保留、取消后的派发阻止、重复幂等/新键预算、旧 revision、模型审核身份不可伪造、条件及兴趣恢复。P01 与新 Vue e2e 使用合成来源、拒绝外网；新 e2e 经过真实独立提取/审核 worker 和本机 HTTP stub，验证新材料采用及重启。

全量回归曾出现 1 个旧页签文案断言失败（932 通过），因为 HTML 页签从“合成演示”改为同时适用私人模式的“本机研究”；已同步修正契约，相关 3 个测试通过。最终全量 **933 passed，2 个既有依赖弃用警告，42.44 秒**。Ruff PASS，仓库配置 Mypy 56 files PASS，Vue 类型/Vite 构建 PASS，文档验证 12/12 PASS。误将类型检查扩大到整个 apps/api 时发现 193 个不在当前配置范围内的注解/stub 问题；未通过关闭规则掩盖，亦未把该额外命令说成通过。

现存限制：模型对 ROUTE 的 duration_scope 填法与程序的严格契约存在摩擦，已观察到缓存四条、新材料六条进入待审。保留原结果，不放宽或改判来过门禁。模型语义审核仍可能漏判；本批通过不证明对任意来源正确。A 评估和运行时持久化依赖检查的计数层级不同，评估通过不能直接冒充入库。

Coverage Q1 路线、Q2 体验、Q3 时长、Q4 限制全部 PARTIAL。新增观景参考没有填上门到门时间、当前道路/运营、公共接驳及五天非自驾适配。来源独立性、图片内容、实际旅行时间保持未知；没有编造完整行程。

## 启动与使用

当前 P02 已运行：[本机工作台](http://127.0.0.1:8766/)。原 [P01](http://127.0.0.1:8765/) 保留。停止本轮服务后，可在普通 PowerShell 用以下命令恢复；已有服务运行时直接打开页面即可。

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\live_workbench.py serve --source-database .local\p01-preview\preview.sqlite3 --workspace .local\p02-preview --account-scope current-private-profile --continuation p02-live-workbench --port 8766 --open
```

`--open` 使用本机短时入口自动打开页面；不要分享终端中的票据。后续不复制 Cookie，不手工审核/复制 SQLite。现有前端已构建；源码重新构建可在 `apps/web` 执行 `npm run build`。启动仅恢复现有库，本轮许可已关闭、预算耗尽，研究按钮不可再次派发；缓存、条件、改选和引用仍可查看。

## Git 与停止

功能提交：`79ec8bd4888b06958ad8b85433c43351acdead9d`（v3/自动审核/账本/API 契约）；`25b82492978feb53bc768215fdf349e65917c4d4`（页面/worker e2e）；`35a8adfab39473bd50fd459f96202504c7eb0ce7`（最终诊断记录）。最终报告提交和远端完整 SHA 随交付核对返回。

完整基线到 HEAD 范围及明确暂存文件扫描模型 key、本机认证票据、profile、SQLite、真实正文片段、原始响应/调试数据。原三份未跟踪 T03 报告保留；不 force push、不关 TLS 验证、不合并 master。推送结果及最终完整 SHA 在交付消息核对返回。

本批 `git diff --stat` 汇总：59 files changed, 3478 insertions(+), 119 deletions(-)。

下一步建议仅处理审核输出字段契约与待审诊断可读性，并继续保留当前行程可行性缺口；新的真实调用需另行授权。本批停止，不进入地图、酒店、报价、KnowledgeCard 或其他新产品功能。
