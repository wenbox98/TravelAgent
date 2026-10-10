# TravelAgent｜私人本地建议型攻略助手

首次条件接收已改为逐字段类型契约，驾驶布尔兼容仅限有明确原话的极性一致陈述；非法值停止并显示失败字段和阶段，保留模型已执行、HTTP和用量记录。历史失败只读诊断，不自动重试或改写条件。真实全流程验收结果另行记录，不能以类型修复代替攻略质量通过。

当前新提交使用V4：首次模型理解、到达与当地交通区分、有界业务工具循环，并修复默认后续无法研究后生成及同查询只读一篇的限制。同一列表按每篇实际审核后的缺口择读多篇，先预留反馈和生成成本。旧V3许可、失败与采用版不改写。真实质量尚未实测，G1仍NOT PASS；见 [V4契约](docs/architecture/goal-directed-private-planning.md)、[预算与多来源修复](reports/P10-agent-budget-and-multi-source.md) 和[原V3报告](reports/P10-goal-agent-and-intake.md)。

2026-10-09 研究深度修复：正常页面增加带条件和审核性质的正文拆分点，可选为兴趣、排除和恢复；新规划派发保留这些点的必要引用。合格部分不会因后续单篇失败而隐藏。单篇空正文可在同一预算内跳过，验证或访问限制仍停止。见 [研究深度与部分保留报告](reports/P10-research-depth-and-partial-retention.md)。本批未增加真实外部请求，不能据离线结果宣布真实攻略质量或G1通过。

当前条件在首页单独展示，可本地修改、取消并恢复未提交草稿；旧消息和采用版另行说明。系统启动失败与资料缺口分开，空材料不再提供比较快捷操作或消耗问答模型额度。8768 已更新为普通本机权限运行，并通过零联网研究启动自检；这不表示新一轮真实小红书研究已通过。见 [启动与条件修复报告](reports/P10-research-startup-and-condition-clarity.md)。

当前8768版本按已证明的路线对象提供可选方向；同一来源可有多条路线，但仍只计一个来源。可分别选择、撤回、排除和恢复。主对话统一发送：明确条件直接落实后更新，问题或假设只做一次缓存问答，模糊解释可一次确认并更新。后续输入和必要查询带上当前取舍；不把路线参考当完整攻略。公共活动顺序确定后可独立核实一段路程。刷新、选择和本地导出不调用外部服务。契约见 [缓存会话与关键路段](docs/architecture/cached-conversation-and-key-leg.md)，本轮离线验证见 [方向与会话更新](reports/P10-route-direction-and-dialog-loop.md)。

最新“东北7天”真实研究消费连接1、搜索3、正文6、模型12，新增5条合格路线/时长引用；具体玩法与交通仍不足，未生成或采用完整攻略。真实问答和关键地图的新入口尚未追加实站验证，不能据离线测试宣称通过；G1仍NOT PASS。见 [真实验收报告](reports/P10-northeast-live-validation.md)。
## Codex 设计、开发与测试文档包 v1.1（小红书研究 PoC 强化版）

**编制日期：2026-09-22。交付状态：开发规格，不是已经开发完成的应用。**

目标：用户给出模糊旅行需求后，工具自动研究小红书等来源，先提供几个大致路线和停留时间，再通过带建议的对话确定交通、项目、住宿和预算。研究成果在权限允许的范围内进入个人资料库；修改选择后进行局部重算。

目标仓库是 `wenbox98/TravelAgent`，与 `devagent-lab` 学习仓库独立。项目许可证尚未确定，不在本次文档导入中代选。此压缩包是待导入材料，不表示已经写入远端仓库。

## 当前定位：私人本地研究

普通首页一次点击「查资料并生成旅行建议」：先模型理解，再由模型按实际反馈决定缓存复核、有限研究、正文审核、建议和停止。按钮旁说明本次用途；新V4首次按范围最多连接1/搜索2/正文4/模型13，三天及以上或跨区域最多连接1/搜索3/正文6/模型18；后续明确更新最多连接1/搜索1/正文2/模型8。理解、监督、提取、审核和建议共用该总额，正文派发先保留反馈决策与规划成本，成功生成后本地结束。旧V3页面及既有许可仍按原9/13或后续5次上限，不自动扩额。缓存足够的理解、监督和规划需3次；可跳过站点。默认不调用地图，可单独允许核实一段公共衔接。问题或假设只从缓存回答且不改条件。原采用版只在明确采用后更新。历史真实研究内容仍不足，见上方结果；[旧自动编排契约](docs/architecture/automatic-private-planning.md) 与[首次离线验收](reports/P10-automatic-research-flow.md)保留各自版本边界。

普通新旅行的本地选材入口已收尾：知识卡与历史采用组合并列可选，无外部许可也能预览、取消、采用、导出与恢复。历史建议不会标成新模型生成；测试资料默认隐藏。当前交付为本机私人试用候选，历史门禁与完整私人版未通过项不改写。最短操作路径见 [私人试用说明](docs/private-advisory-quickstart.md)，本轮证据见 [入口收尾与交接](reports/P10-private-trial-handoff.md)。

新旅行默认建议模式：先选玩法、停留区间和取舍，首项钟点、交通、休息可以未定。明确预约、返回硬截止和锁定项目仍保护；历史旅行保持原时间含义。已有知识卡可给出一个项目的有限建议，不能据此声称完整攻略或当前可行性通过。

同一主页面提供建议攻略、候选组合预览/取消/采用、食宿策略、旅行花费草案和采用版 Markdown 导出。旅行花费与外部调用额度分开；未知不当零，AI金额是预算预留而非市价。食宿先给选择原则，未接通报价供应商。详细时间视图按需展开，地图缺失不阻止建议。见 [建议攻略与费用契约](docs/architecture/advisory-guide-and-trip-budget.md) 和 [P09验收](reports/P09-advisory-guide-and-trip-budget.md) 与 [P09.1一致性收尾](reports/P09.1-context-consistency-and-acceptance.md)。

P10 整体验收 **PARTIAL，尚不具备完整私人建议版冻结条件**：A 原失败保留，零联网本地重新校验后可采用；B 冻结成果无回归。真实城市需求得到一个公园的有限建议，相关内容仍只有地点提及；真实周末需求可改选、计预算并恢复，但尚未形成第二天安排。不能用流程通过代替内容通过。见 [P10 分项验收](reports/P10-final-advisory-acceptance.md) 和 [交付候选检查单](reports/P10-private-advisory-candidate.md)。

后续通用修复已把当前天数/轻松节奏、资料用途、逐日覆盖接入模型输入、校验、改选、页面与导出。有限合法方案可保留，缺日与仅名称资料明确显示；具体休闲/自行安排可作为取舍，空白和用餐占位不算完整建议。该次修复只有离线回归和历史输入只读核对，见 [通用逻辑修复报告](reports/P10-general-advisory-logic-fix.md)。

2026-10-07 定向复验已实际更新同一8768：两日新建议有真实模型生成的第二天项目，预览、取消、采用、导出和重启恢复通过；城市新资料接纳两条 Evidence，但已审核片区体验尚未关联到所选活动，规划输入仍主要是路线名称，内容改善未通过。缺口识别与内容改善分别报告，私人建议版仍不可冻结，历史攻略和门禁保持不变。详见 [通用修复上线与定向复验](reports/P10-general-rollout-validation.md)。本轮两个新许可均已关闭。

当前普通主入口是日常私人工作台：独立新旅行、明确复用历史活动、页面授权与可见预算、研究/安排/改选/地图和本地采用恢复。无需阶段参数或命令行授权，不自动继承历史测试偏好。新旅行无外部额度；只有用户确认用途、接收方和次数后，明确点击操作才派发。追加记录关联旧许可，失败和旧消耗保留。详见 [日常工作台契约](docs/architecture/daily-private-workbench.md)。P06 改选协议和历史门禁保持原义，G1仍NOT PASS；地点线索、作者证据、范围与当前可行性继续分别展示。

本机已经构建好前端并安装依赖，唯一日常启动入口如下（8768 已运行则直接使用，不重复启动）：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

地址 `http://127.0.0.1:8768/`。默认沿用 `.local/p04-preview` 活动库；原数据库、profile和历史静态目录保留。模型/高德继续读取现有本机服务端配置，不探测Key、不进入前端。保存、浏览、复用、刷新和重启为零项目外部调用。

输入框会分别显示尚未提交、正在提交、已接收及任务进度。连接未就绪、空输入或未保存修改时，快捷键会说明原因。回复丢失时先“读取已保存状态”；仍未确认可手动“继续确认原提交”，沿用原文字和同一请求标识，不自动重试或重复任务。未提交想法和消息保留在当前浏览器。详见 [提交反馈与恢复验收](reports/P10-submission-feedback-and-recovery.md)。

日常使用：新建旅行 → 选择本机已有活动或主动研究 → 确认有限操作许可 → 生成安排/按意图改选/地图核实 → 预览、取消或采用。用途和累计用量可展开查看；关闭许可后仍能本地编辑。来源不足、未配置、未授权、耗尽和上游失败分别说明。地图临时值重启过期，不自动重新查询。

预览不会覆盖采用版；取消后可再次打开同一已存提议，不再请求模型。导出的是采用版，含引用、建议属性、预算不完整处和未计入项。本轮两个测试旅行的许可均已关闭；查看结果和资料库关键词检索不需要追加额度。测试资料需显式显示，不自动成为所有新旅行的偏好。

页面提示需要重新打开本机入口时，再运行同一 `serve --open` 命令即可；服务已运行时会由本机启动器为原服务签发新的五分钟一次性入口，不停止服务、不取消任务或恢复额度。也可执行 `.venv\Scripts\python.exe scripts\product_preview.py open`。输入想法后点击“查资料并生成旅行建议”，目的区域不清楚时可修正；未提交想法在当前浏览器本机保留。不要复制 Cookie 或清空数据库。地图临时值过期不影响已采用玩法。入口修复与仍未完成的体验项见 [入口恢复验收](reports/P10-entry-recovery-implementation.md)。

A 类旧失败只有在原安全诊断仍有效、原引用与当前条件仍可核实时，才能通过页面“本地重新校验”形成版本化派生结果；这不是模型重新作答。诊断过期时保留原失败，不从报告补造回答。是否纳入住宿和金额是否已知分别展示，未纳入不是免费，已付/锁定住宿不会被一日缺省覆盖。

仅开发更新前端时才需重新构建：先正常关闭本工作台并保留当前静态目录，再在 `apps/web` 执行 `npm.cmd run build -- --outDir ../../.local/workbench-web`，成功后回仓库根目录用上面的唯一入口启动。日常查看无须构建。备份、回滚和未完成项见交付候选检查单；不得用旧库覆盖当前库恢复次数。

首次空白安装与可配置scope见上述契约；已配置数据库缺失或损坏不会静默建立空库。`.local/p07-backup` 保留本轮升级前一致性备份、代码和构建用于核对；备份不能覆盖当前库恢复旧预算。

下面各阶段命令和结果作为历史记录保留，不是额外推荐入口。


P03 增加已确认兴趣的地点与分段路程核实，保持原资料、G1 NOT PASS和当时测试条件。地图只在明确点击时调用，缺少Key也能填写条件、预览/取消/采用并恢复。地图返回值只存内存；重启保留输入及额度，地图需显式重查。见 [P03设计](docs/architecture/p03-amap-route-check.md) 和 [验收报告](reports/P03-amap-route-check.md)。独立页面不覆盖8765/8766/8767：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent\apps\web
npm.cmd run build -- --outDir ../../.local/p03-web
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\route_preview.py --open
```

地址 `http://127.0.0.1:8768/`。已有服务时直接使用，不重复启动。Key仅通过本机用户环境变量 `AMAP_WEB_SERVICE_KEY` 配置（Web服务类型），新终端启动时继承；不自动读.env。不要把Key填入页面或聊天。当前批次最多8次地点+8次路径，不通过重启/新目录恢复；没有小红书或模型能力。

P02.1 对齐时间审核契约，并对已存模型提议做版本化本地回放；没有新的模型作答或小红书访问。原提议、历史审核和选择保留，新增资料需显式采用。见 [本地回放设计](docs/architecture/p021-review-replay.md)。P01/P02 的数据库和共享前端构建不被覆盖。

本机隔离页面启动（已有依赖；8767 已运行时直接使用页面）：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent\apps\web
npm.cmd run build -- --outDir ../../.local/p021-web
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\review_replay.py serve --source-database .local\p02-preview\preview.sqlite3 --workspace .local\p021-preview --account-scope current-private-profile --port 8767 --open
```

本机地址 `http://127.0.0.1:8767/`。首次建库使用 SQLite 一致性备份；已有副本不会重建或恢复预算。`serve` 不执行回放，只有操作者显式使用 `dry-run` / `replay` 命令才会校验已存提议；没有页面强制批准入口。普通页面浏览、展开理由、取消和采用均零业务外部请求。

P02 增加普通 v3 入口、独立模型上下文审核和页面主动触发的有限研究。新材料与选择保存在同一个私人工作副本，必须显式采用；刷新、查询状态和改条件仍不触发外部请求。模型审核只检查原文支持关系，未核实当前可行性。历史 Work 审核不会改名为模型审核，G1 仍 NOT PASS。真实分项结果、预算与限制见 [P02 验收报告](reports/P02-live-research-workbench.md)，契约见 [P02 设计](docs/architecture/p02-live-workbench.md)。

本机已建立的 P02 工作区可用以下命令恢复（端口占用时直接使用正在运行的页面，不要重复启动）：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\live_workbench.py serve --source-database .local\p01-preview\preview.sqlite3 --workspace .local\p02-preview --account-scope current-private-profile --continuation p02-live-workbench --port 8766 --open
```

本机地址 `http://127.0.0.1:8766/`；`--open` 自动打开短时本机入口，不需要复制 Cookie 或数据库 ID。启动不会重新覆盖已存在的副本、自动创建许可或调用模型。受控验证完成后关闭本轮许可，未用次数保留为历史记录，不因重启恢复。没有既定模型配置也可浏览缓存，真实研究不可执行。原 P01 8765 服务和数据库独立保留。

P01 已接通已审核缓存到 Vue 页面、条件选择、改选预览/取消/确认及重启恢复。它是缓存驱动开发预览，G1 仍 NOT PASS，不能据兴趣确认判断行程可行。见 [P01 使用与验收](reports/P01-cached-overview-preview.md)、[接口与备份](docs/architecture/p01-cached-preview.md)。不自动研究、不调用小红书或模型。

已安装锁定依赖的开发环境中，在 `apps/web` 执行 `pnpm build` 后回仓库根目录启动（路径和 scope 使用自己的已配置缓存）：

```powershell
.venv\Scripts\python.exe scripts\cached_preview.py --source-database <已有缓存.sqlite3> --workspace .local\cached-preview --account-scope <本地scope> --port 8765 --open
```

浏览器会打开仅本机的一次性入口并跳到 `http://127.0.0.1:8765/`。终端也显示五分钟有效入口；不要分享该临时入口。Ctrl+C 正常停止，下次原命令恢复工作副本的选择。原库和 profile 保留。明确的 SYNTHETIC_DEMO 模式只显示合成来源，不会在真实缓存缺失时回填合成攻略。

T06.6 将缓存复验改为片段 ID 选择，由程序回填准确文本、定位和条件集合，再经过严格 Work 上下文审核。仅用两篇缓存与两次追加模型请求，24 条定位通过、接纳 19、拒绝 5；旧六条原样保留，共 25 条记录（含一条同源旧观点重叠，不增加独立支持）。非空片段映射恢复和五天不自驾零访问增量通过。**正文现在能展示作者七日草案与攻略五个日段，仍无实测总耗时或非自驾可行性，G1 NOT PASS。** 小红书/浏览器全为 0，见 [T06.6 报告](reports/T06.6-reference-extraction.md)。

T06.5 已完成一批有界补充：1 次搜索、2 篇新详情、2 次模型提取，新增接纳 3 条，加旧 3 条共 6 条。已生成私人可读局部攻略，并通过跨进程非空、零站点/零模型恢复和五天不自驾增量。**G1 仍 NOT PASS：路线和整趟时长候选未通过原定位标准，不能输出完整粗略路线。** 标题筛选、逐条条件展示及正常提取的 120/180 秒截止已修复；实际结果和剩余缺口见 [T06.5 报告](reports/T06.5-coverage-closure.md)。本批额度耗尽，未进入新产品功能。下方保留历史阶段结果。

T06.4 完成单次追加授权与 120 秒等待/180 秒总截止，859 项离线测试通过。唯一缓存正文复验完整返回；12 条候选经严格定位及 Work 上下文审核后，3 条入库、9 条拒绝，非空 Evidence 跨进程零访问恢复 PASS。XHS connect/search/detail=0/0/0。**G1 仍 NOT PASS：只有局部作者体验线索，路线、时长与交通 Coverage 不足。** 原失败记录、原耗尽预算及本次已消费授权全部保留。详见 [T06.4 分层报告](reports/T06.4-model-response-timeout.md)；下方为历史结果。

T06.3 已完成逐条 grounding 诊断、上下文审核候选区与独立合格结果的部分保留，849 项离线测试通过。仅缓存正文的一次模型复验收到 HTTP 200 后读取超时；本次真实 Evidence=0，**G1 仍 FAIL**。XHS connect/search/detail 全部为 0；原缓存、历史失败和已用重跑额度保留，未再次请求。详见 [T06.3 报告](reports/T06.3-grounding-recovery.md) 与 [逐条审核契约](docs/architecture/t063-grounding-recovery.md)。下方 T06.2/T06.1 为历史结果。

T06.2 已完成安全错误分型、正文先保存和仅模型恢复入口。合成真实提取通过；有界真实复验在第一篇 grounding 拒绝后停止，**G1 仍 FAIL**。这次已保存正文并通过独立进程恢复，不再因模型失败丢失原文。详见 [T06.2 报告](reports/T06.2-llm-diagnostics-and-recovery.md) 和 [恢复契约](docs/architecture/t062-extraction-recovery.md)。真实账本不允许自动重跑；后续从本地已保存来源排查，不重新搜索。下方 T06.1 结果和入口是历史记录。

当前仅供当前用户本人私人使用，暂不考虑公开发布和多用户产品。默认数据模式为 `PRIVATE_LOCAL_RESEARCH`，正文保留默认 `PERSISTENT`；后续保留选择支持 `7_DAYS / 30_DAYS / PERSISTENT / EPHEMERAL`。

只缓存实际精读用于旅行研究的少量正文、规范文本、正文块与 Evidence，以减少下一次重复访问。搜索候选不自动缓存全文；不长期保存原始图片。研究数据仅在本机 SQLite，不建公共数据集、不跨用户共享、不上传自有服务端、不提交 Git。配置的外部模型只处理必要正文块，认证材料始终隔离在浏览器会话中。

私人用途模式不代表作者授权、平台授权或合规认证；权利依据仍记录 UNKNOWN。明确的本次用户用途决策覆盖旧的 UNKNOWN 一律禁止本地保存规则，但不取消只读、预算和验证暂停要求。设计与迁移见 [私人研究数据策略](docs/architecture/t06-private-local-research.md)。下方早期发布计划及阶段结果作为历史记录保留。

真实验收入口为 `scripts/private_research_smoke.py --live`，上限 1 次搜索、3 篇详情、OBSERVE_ONLY。正常关闭保留 profile 与 `.local/t06.1-private/research.sqlite3`；清研究缓存使用既有 `research_quality.py clear-cache`，不会 disconnect 或清理登录 profile。独立进程恢复验证使用 `tools/private_cache_probe.py`，禁止网络访问。模型已验证可用，不重跑合成连通性请求。

用户明确批准本次必要正文发送 DeepSeek 后，真实验收已完成一次搜索和一篇详情：登录复用、搜索和正文读取成功，首次模型抽取降级并触发停止，**G1 FAIL**，G0 保持此前 PASS。独立入口路径问题已修复；模型失败缺乏分型诊断，以及失败时正文尚未落库，是后续修复点。详见 [本轮验收记录](reports/T06.1-g1-live-validation.md)；[旅行研究示例文件](reports/T06.1-live-travel-research-example.md) 如实说明暂无合格 Evidence，没有虚构真实路线。

已确认的下一步架构方向是 Raw Source → Evidence → KnowledgeCard → Knowledge RAG，未来推荐原文 SESSION 保留，卡片成功落库且 grounding 完成后才允许清理原文。KnowledgeCard、SESSION 及“清原文缓存/清旅行知识”拆分目前只是设计待办，当前实现仍用 PERSISTENT；不因这项设计变更删除现有研究库。详见上方私人研究数据策略。

## 现在怎么交给 Codex

1. 将此包导入 `wenbox98/TravelAgent` 根目录。导入前先检查远端和本地内容，不覆盖已有文件；成功导入后，在 Codex 中选择该仓库即可读取文档，无需再下载聊天附件。
2. 在 Codex 中打开该目录，把 [CODEX_START.md](CODEX_START.md) 的启动指令整段发给它。
3. 首次完成 T00、T01 后逐个执行任务，不要求一次生成全部系统。每个任务的产物和验收见 [任务总表](docs/12-task-plan.md)。
4. 原包历史上只执行过文档校验；T00/T01 离线实现见 [T00 报告](reports/T00-implementation.md)、[T01 报告](reports/T01-implementation.md)。后续本机登录专项已由 [T03.8 报告](reports/T03.8-implementation.md) 验收；真实读取、访问成本和 Windows 发行安装不能据此视为通过，T04 当前状态见下文。

没有真实账号、Windows 或 API 凭证时，Codex 应完成离线可验证部分，准确记录阻塞项，不得把 mock 结果写成实测。

## 首版边界

**首版 v0.1：Windows x64 本地单用户；支持本地正常登录小红书、有限自动研究、粗略攻略、多轮选择、个人资料复用、明确标记状态的预算，以及高德地图接入。**

发布包的体验目标是解压/安装后启动应用，点“连接小红书”，在官方页面或官方生成的二维码完成登录。不要求普通用户安装 Docker、Python、Go，或复制 Cookie。开发者构建可以使用开发工具。

首版不做云端托管多人账号、不承诺纯手机独立运行、不做无人值守验证码处理、不做账号/IP 轮换、不自动下单。真实票价必须有可用供应商才能显示为报价；未接通时标记未知，不构造“演示价”。

## 阅读导航

| 文档 | 解决什么问题 |
|---|---|
| [01 产品需求](docs/01-product.md) | 做成什么样、首轮怎么回答、哪些不做 |
| [02 总体架构](docs/02-architecture.md) | 模块边界、目录、进程和数据流 |
| [03 小红书接入与登录](docs/03-xhs-access-login.md) | 低操作成本登录、上游核实、只读适配、异常恢复 |
| [04 准确性与请求预算](docs/04-research-efficiency.md) | 先筛后读、去重、缺口搜索、计数与熔断 |
| [05 数据与 RAG](docs/05-data-rag.md) | 保存什么、权限、检索、时效与删除 |
| [06 Agent 与规划引擎](docs/06-agent-planning.md) | 多轮状态、修改、时间与预算计算 |
| [07 接口与领域契约](docs/07-api-contracts.md) | HTTP、事件、错误、并发和版本规则 |
| [08 页面与交互](docs/08-ui-ux.md) | 登录页、粗略攻略、取舍预览、资料库 |
| [09 安全与开源边界](docs/09-security-open-source.md) | 凭证、来源指令注入、数据用途、发布边界 |
| [10 测试设计](docs/10-test-strategy.md) | 离线、集成、人工实测、度量与门禁 |
| [11 开发部署运行手册](docs/11-dev-deploy.md) | 命令、配置、桌面打包、排错 |
| [12 开发任务总表](docs/12-task-plan.md) | 任务顺序和 Codex 每次改什么 |
| [13 设计质询](docs/13-design-review.md) | 十二项反例检查与调整 |
| [14 来源与事实状态](docs/14-sources.md) | 哪些已读源码、哪些待验证 |
| [15 发布验收](docs/15-release-acceptance.md) | 什么程度才能说“可用” |
| [16 小红书筛选实施细则](docs/16-xhs-screening-spec.md) | 未知值、正文验证、停止语义及筛选审计 |

`contracts/` 是机器可读的领域/API/数据库草案；`fixtures/` 全部是合成测试数据；`prompts/` 为 Agent 提示词规范；`docs/tasks/` 是具体施工单；`tools/validate_pack.py` 可校验本包；`00-阅读导航.html` 是目录导航，完整内容以 Markdown 与契约源文件为准。

## 三类文字的意义

- **用户要求/设计决策**：本项目应实现的行为，并非外部平台承诺。
- **源码或官方文档已核实**：带来源编号；仅证明所观察到的版本或文档内容，不等于线上成功。
- **待实测/设计目标**：必须用真实报告验证，不能当成已达到的指标。

所有测试中的地点代号、时间、票价、笔记和账号标识均为合成示例；“国庆成都去川西”只是需求输入样例，不包含真实旅行建议。

## v1.0.1 变更

补充第 16 章与 T04 的筛选验收，修正“连续两篇没有新信息”不等于研究完成的语义；加入 Git 忽略规则与文本换行规则。原 76 项应用测试继续保持 NOT_RUN；新增 SEL01～SEL12 为待实现测试设计。外部事实沿用原包来源记录，本次整理未重新运行真实平台验证。


## v1.1 变更

本版不推翻原产品设计，重点把“小红书攻略获取”收敛成可实施、可验收的 PoC：

- 首次连接通过本地正常网页会话完成，不要求普通用户复制 Cookie、开 DevTools 或配置 profile；会话失效时保留研究任务，重新连接后续跑。
- 不通过验证码破解、代理/IP/账号轮换、stealth/anti-detect 等方式规避平台安全机制；优化目标是**提高命中率与资料复用率，从源头减少无意义访问**。
- 研究改为 Evidence Gap 驱动：先查个人资料库，再少量搜索候选，先筛后读，逐篇更新缺口，证据足够即停止。
- PoC 默认护栏调整为每轮最多 3 次搜索、6 篇详情；它是应用成本上限，不是平台安全阈值。
- 统一正文完整度为 `FULL_TEXT / PARTIAL_TEXT / SUMMARY_ONLY / METADATA_ONLY`，避免标题或摘要被误报成“已阅读全文”。
- 新增 [XHS PoC 上游分析](docs/architecture/xhs-poc-analysis.md) 与 [XHS PoC 设计](docs/architecture/xhs-poc-design.md)。
- 第一阶段以 CLI 验证登录→搜索→筛选→精读→Evidence→SQLite 复用→增量补搜；Electron/完整工作台继续保留在后续阶段。
- 新增 XPOC01～XPOC10 验收设计：缓存 0 请求、预算上限、提前停止、去重、增量补搜、登录失效、验证暂停、摘要边界、revision 防覆盖、预算耗尽。

**上述 v1.1 变更说明是历史开发规格，不能单独作为实测证据；后续各阶段的真实状态以对应报告为准。**

## T02只读sidecar离线基础

T02 增加独立[只读 sidecar 基础](integrations/xhs-sidecar/README.md)：Fake 普通浏览器会话、路由白名单、源头日志脱敏、筛选/完整度/来源定位/网络模型。历史验证见 [T02 报告](reports/T02-implementation.md)，来源见 [provenance](docs/architecture/xhs-upstream-provenance.md)。没有复制或运行完整 upstream。

## T03 登录生命周期

在 T02 基础上新增标准 Playwright 普通 Chrome/Chromium、系统应用数据目录中的 TravelAgent 专用 profile，以及本地登录状态机。默认仍为 offline Fake；显式 login 模式启动服务也不打开浏览器，只有 connect 才启动可见官方窗口并导航一次。用户在官方窗口正常登录，无 Cookie 复制或二维码提取；等待复用同页，不反复刷新。

`GET /v1/login/status` 只读本地快照；profile 存在只标 SESSION_PRESENT_UNVERIFIED。generation 拒绝取消/断开后的晚到结果；cancel 和关闭保留 profile，disconnect 关闭后清理。验证要求暂停，手工处理后显式 resume 同页继续。login 模式拒绝 search/detail 和旧浏览器 POST 入口。

命令、launch 参数与 profile 边界见 [sidecar README](integrations/xhs-sidecar/README.md)。初次离线交付见 [T03 实现报告](reports/T03-implementation.md)；后续经用户授权完成登录识别修复、200 项离线测试及本机真实登录/重启复用/断开清理，执行证据见 [T03.8 验收报告](reports/T03.8-implementation.md)。**T03 登录专项已通过，最终提交为 `ccd329056794d3f29549ff0383f6236ce6373f36`。** 当时停止于 T03；本轮经用户新授权进入下面的 T04，G0 整体仍未通过。

## 历史 T04 首次读取 Smoke（PARTIAL）

T04 仅增加独立人工 CLI `.venv/Scripts/python.exe scripts/xhs_read_smoke.py --live`。启动不打开浏览器，输入 `connect` 后才用 T03 相同的普通 Chromium、专用 profile 和同一个 BrowserSession 正常登录。命令为 `connect/status/search/detail 0/detail 1/snapshot/quit`；`quit` 正常关闭并保留 profile。

一次固定搜索 `成都 川西 国庆 攻略`，最多两篇确定性选择的图文详情；第一篇足够技术验证时不读第二篇。不自动换词、翻页、滚动、展开评论、分析图片、下载视频或执行平台写操作，不实现完整研究服务、RAG 或最终攻略。预算在读取派发前记录，已有非零读取记录时拒绝通过重启重置预算。

输出和 Git 忽略目录中的 `.local/t04-smoke/summary.json` 仅保存匿名字段存在性、数量、完整度与网络统计。网络 scope 为 `context_events_since_attach`，保留窗口外流量和晚到响应，未知字节数为 null；业务 search/detail 次数与真实请求数分列。现有 sidecar HTTP 契约仍是 0.3.0 的 offline/login，`live_smoke` 仅是内部摘要类型。边界和命令见 [sidecar README](integrations/xhs-sidecar/README.md)，结果见 [T04 Smoke 报告](reports/T04-xhs-read-smoke-test.md)。

本次同一 BrowserSession 正常登录为 AUTHENTICATED，1 次上述搜索得到 20 个去重候选，搜索技术验证 PASS。1 次详情已消耗预算，但返回 UNEXPECTED_PAGE，未解析出正文；用户确认浏览器显示正常图文页，不能据此把自动 detail 判为成功。详情验证 FAIL，总体 PARTIAL；路由别名校验不一致仅完成离线修复，实际失败原因未确证，未进行真实复测。CLI 已正常退出并保留 profile。

搜索窗口观测 173 个 context 请求，详情失败前窗口为 86 个（不代表完整详情成本），TOTAL 为 725 个、主 frame 导航请求 5 个；字节数未测。默认评论相关请求有 1 个，分类为 DERIVED，不代表主动展开评论。G0 仍未通过，本轮停止，不进入 T05。

## T04.1 详情补验（有限技术 Smoke 通过）

[T04.1 报告](reports/T04.1-xhs-detail-smoke-test.md) 记录 423 项离线测试及真实补验：复用 profile，无需重新登录，使用 1 个 BrowserSession；旧 locator 仅在内存，因此使用另行授权的 1 次 fallback 搜索取得 20 个候选，再读取上一轮未访问的备用候选，本轮 detail 仅 1 次。入口为 `scripts/xhs_read_smoke.py --live --detail-smoke`，使用独立 `.local/t04.1-smoke/summary.json` 账本，未重置历史 T04 额度。

该详情 IDENTITY_MATCH、主响应 200，取得正文 672 字符、22 个非空行（计数 DERIVED），完整度 PARTIAL_TEXT：DOM 不完全一致，展开/截断状态未知；5 张图片未做 OCR。详情窗口 3.150135 秒观测 181 个请求，TOTAL 587，字节数未测；正常 quit 保留 profile，自有浏览器剩余 0。历史失败根因仅 LIKELY 与路由别名有关，原失败分支仍 UNKNOWN，不能确证。

T04 有限技术 Smoke 可以结束；这不自动通过 G0 完整发布门禁，也不进入 T05。下一步建议另行授权 T04.2 基线请求优化，当前未实施请求阻断。

## T04.2 / T05 新授权阶段

在 T04.1 基线后增加阶段限定的 TEXT_FIRST、BodyBlock 证据摘取、SQLite 研究元数据、缓存优先的有预算 ResearchService 与增量缺口。默认仍 OBSERVE_ONLY；真实入口为 `scripts/xhs_research_smoke.py --live`，上限固定 1 次搜索、2 次详情，只生成研究材料，不生成完整行程。

详见 [实现设计与来源用途边界](docs/architecture/t05-research-loop.md) 和 [T05 执行报告](reports/T05-xhs-research-loop-smoke.md)。UNKNOWN 来源内容只在内存临时研究；没有模型配置时明确使用本地保守摘取，不冒充模型抽取或持久化缓存。历史阶段的停止要求不代表本次新授权阶段已经通过，实际状态以报告为准。

T05 最终离线测试 581 PASS；真实 1 次 search、2 次 detail 取得 6 条低置信 PARTIAL_TEXT 证据，缓存和 5 天/不自驾增量复用均 0 访问。TEXT_FIRST 阻止 224 次图片加载，请求事件 SEARCH 236、DETAIL 276/285 包含被阻断的尝试，不能代表实际出网数量。它尚未证明减少实际网络成本，默认继续 OBSERVE_ONLY。G0 本机受控只读数据通道通过，G1 研究质量未通过；T05 真实 Evidence 只在内存，profile 保留，自有浏览器/sidecar 均已关闭。

## T06 研究质量与持久缓存

新增 SQLite v4 研究约束、证据质量与报告元数据；缓存判断在登录前，跨进程复用和清除研究缓存均有离线验收。正文先 canonicalize，再做有块定位的严格抽取，按来源/条件去重、时效、冲突与 Q1–Q4 coverage 形成可追溯的候选方向。只处理研究材料，不生成最终详细行程。

T06 交付时没有真实 LLM 配置，当时为 **G1_LIVE_LLM_BLOCKED，G1 未通过**。后续 T06.1 已通过合成正文的真实模型检查，见 [模型接入阶段报告](reports/T06.1-g1-live-llm-validation.md)。当时的来源策略门槛已由用户明确的私人用途决策更新；当前真实验收状态见上方本轮记录。合成 benchmark 与示例是离线验收，不是真实川西攻略。用法和数据边界见 [T06 设计](docs/architecture/t06-research-quality.md)，历史结果见 [T06 报告](reports/T06-g1-research-quality.md)；G0 保留此前 PASS。

## 真实模型配置（T06.1）

沿用 `OpenAICompatibleProvider`，使用 OpenAI 兼容的 Chat Completions 接口。默认使用 `json_schema`，也支持显式选择 `json_object`；两种模式都保留严格的本地 schema 和正文定位校验。模型配置只从进程环境变量读取；[.env.example](.env.example) 仅为名称与默认值参考，程序不会自动加载 `.env`，复制文件不会使配置生效。

| 环境变量 | 在本机填写的内容 |
|---|---|
| `LLM_BASE_URL` | 服务商提供的 API 根地址，通常包含版本路径；程序会追加 `/chat/completions`，不要填写完整请求地址 |
| `LLM_API_KEY` | 该服务的 API key |
| `LLM_MODEL` | 服务商提供的准确模型 ID，需要支持所选 JSON 输出模式 |
| `LLM_RESPONSE_FORMAT`（可选） | 默认 `json_schema`；仅支持 JSON Object 的服务显式填写 `json_object`，不支持其他值或自动切换 |

Windows 可在开始菜单搜索“编辑账户的环境变量”，在“用户变量”中新建这三个变量并填写自己的值。保存后重新打开运行项目的终端；如果从 Codex 启动验收，应重启 Codex，使新进程继承环境变量。真实 key 只配置在本机，不写入 `.env.example`、源码、报告或聊天。

目前也兼容旧 `TRAVEL_LLM_*`、`OPENAI_*` 名称，`LLM_*` 优先；T06.1 使用上述三个统一名称。以下本地预检不会调用模型，也不会连接小红书：

```text
.venv\Scripts\python.exe scripts/research_quality.py live-preflight
```

`G1_LIVE_LLM_BLOCKED` 表示模型未配置或配置格式不完整。当前私人模式配置通过时返回 `PRIVATE_LOCAL_CONFIG_READY`，只表示本地配置可用，不表示刚刚调用了模型或 G1 已通过；旧 SOURCE_POLICY 模式仍可返回来源策略阻塞。阻塞退出码为 2。

T06.1 的顺序是：环境配置 → 全部离线测试 → 完全合成 BodyBlock 的极少真实模型调用 → 来源用途检查 → 真实小红书受控验收。真实验收采用 OBSERVE_ONLY，首次最多 1 次搜索、3 次详情；模型连通失败或出现访问验证要求时停止。未配置模型时暂停，不把 Mock 验收作为 G1 PASS。

T06.1 合成正文的单次真实模型检查工具是 `.venv\Scripts\python.exe tools/llm_connectivity_smoke.py --live-llm`。不加 `--live-llm` 不调用模型；工具不导入浏览器，只记录脱敏错误、请求次数及合成引文。尝试前写入 `.local/t06.1-llm/connectivity.json`，已有记录就拒绝自动重跑，失败不会把本地摘取记为模型通过。人工修正配置、明确安排新检查后可加 `--attempt <新名称>`，保存独立账本；同名尝试仍拒绝重复，不删除历史记录，也不用于重置真实小红书预算。

本机首次模型检查返回 HTTP 404：配置使用 DeepSeek 的 `/anthropic` 地址，与项目 Chat Completions 协议不匹配。DeepSeek 的 OpenAI 兼容根地址是 `https://api.deepseek.com`，`/anthropic` 对应另一种接口。[官方协议说明](https://api-docs.deepseek.com/guides/anthropic_api/)；[OpenAI 兼容调用示例](https://api-docs.deepseek.com/guides/json_mode/)。此外，官方当前文档的 `response_format` 声明 `text/json_object`，因此该服务需要显式选择 `LLM_RESPONSE_FORMAT=json_object`。[Chat Completions 参数](https://api-docs.deepseek.com/api/create-chat-completion/)

地址修正后，本机以 `deepseek-v4-flash`、`json_object` 完成一次 HTTP 200 的合成正文检查，5 条证据的 schema 与正文定位全部通过。本次只在验收子进程中设置输出模式，没有修改 Windows 用户环境变量；之后使用该服务的进程仍需选择同一模式。当时真实资料仍为 **G1_LIVE_SOURCE_POLICY_BLOCKED**；后续用户已明确私人本地用途策略，当前按上方私人模式执行。模型检查通过仍不能替代真实 G1。

## 离线开发启动（T00/T01）

使用 Python 3.14 和 Node 22.12+，先运行 `uv sync --locked`，再在 `apps/web` 运行 `pnpm install --frozen-lockfile` 和 `pnpm build`。返回项目根目录运行：

```text
python scripts/doctor.py
python scripts/dev.py --mode mock
```

此为历史 T00/T01 健康控制面，Ctrl+C 停止。当前 Vue 缓存预览请使用上方 `cached_preview.py` 入口；旧 dev.py 未配置缓存 API。T03 登录仍为独立 sidecar CLI，本轮不启动。

测试：`python scripts/check.py --suite unit|contract|integration|security|e2e`（分别执行，竖线表示选项）；P01 已加入仅访问 loopback 的 Vue e2e，先构建前端。文档检查使用 `.venv\Scripts\python.exe tools/validate_pack.py`。运行资料在 Git 忽略的 `.local/`；T03 profile 位于仓库外应用数据目录。自动测试不访问真实站点，本机 UI 测试浏览器与 XHS 浏览器分开。
