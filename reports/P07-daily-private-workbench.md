# P07：日常私人工作台验收

本批从 `49063254785824e8964a27a7bc5593e9d352eb81` 继续，实际分支 `feature/g1-live-llm-validation`，使用原 8768 主入口和原活动数据库。普通用户不再需要指定 Pxx、执行阶段授权命令或修改 Python 常量。G0 保留历史结论，G1 仍 NOT PASS，其余门禁不升级。

## 普通入口与契约变更

页面支持独立新旅行、明确选择历史活动、有限用途许可、累计用量、追加和关闭；研究、规划、改选、地图仍走原业务引擎。许可 ID 由服务器随机创建，绑定账号、旅行、目的地、所选资料、任务、接收服务、配置摘要、工作区和期限。新建、读取、刷新、采用、普通编辑不创建外部预算；无许可不能回退到历史批次。

复用 `research_continuations / continuation_operations / preview_jobs / preview_receipts`，schema 15 不变。`OperationAuthorization` 增加用途与有限额度输入；`PlanAction` 增加 authorize/revoke_authorization/reuse_activities；`PlanView` 增加 operation/model_status/reuse_options。`MapQuota` 总额/已用为 0–32 的整数，与两类各16次硬上限一致，解除历史固定总额枚举。schema/OpenAPI、导出器、说明和测试同步。

明确追加只新增关联许可并关闭前许可的未来派发，旧上限、失败和已用不可回退。失败/超时仍消耗派发次数，重启不重派。普通改选可以先减少、再延长，第三次合法操作由明确余额决定；历史 P06 顺序及2次上限保持原义。一项不能再减少，锁定条件、来源、上下文和意图检查未放宽。

## 修改文件与主要符号

- `planning/workbench.py`：DailyBudget、authorize/close/overview/model_status、reuse_options/reuse/local_contents；普通有限许可与许可内本地资料复用。
- `planning/flow.py`、`flow_models.py`、`flow_api.py`：普通旅行创建、动作、状态、DTO和同源接口。
- `planning/private_budget.py`、`private_payload.py`、`discovery.py`、`materials.py`：普通旅行绑定、来源有效期与引用映射、最小必要模型输入。
- `planning/suggestions.py`、`preview/jobs.py`、`preview/worker.py`、`research/bounded.py`：普通任务连接、耐久预留、子进程继承实际工作区、最终规划额度保留与任务恢复。
- `research/recovery.py`、`context_review.py`、`planning/service.py`、`flow_maps.py`：长响应后重新检查许可、任务及修订，阻止晚结果；地图复用现有端点和临时生命周期。
- `planning/models.py`：MapQuota 响应契约；`preview/api.py`：状态说明和仅计数的本地页面请求统计。
- `scripts/product_preview.py`：默认同库同端口、普通角色限制、配置继承、空白安装与既有库损坏保护；静态目录为 `.local/workbench-web`。
- `OperationPanel.vue`、`PlanningPanel.vue`、`PlanPlaces.vue`、`planning-api.ts`：页面许可、额度、历史复用和可用操作。
- `tests/integration/test_daily_workbench.py`、`apps/web/tests/operation-panel.mjs`：普通生产路径的 Fake/页面契约回归。
- `README.md`、`docs/architecture/daily-private-workbench.md`、契约和文档校验报告：使用方法及边界。

没有改成 network 全允许：主服务只有高德适配传输上下文能访问允许路径；模型 worker 只有原 DeepSeek 路径且单进程至多一次 HTTP；研究 worker 仍受预算和只读流程保护。新研究组合在详情前至少保留提取、审核、最终规划3次模型资源。缓存读写没有业务外连。

## 离线验收

新增普通路径测试涵盖：无历史授权的新旅行、零调用读取、跨旅行/账号拒绝、并发幂等、超时不退额、追加与撤销、过期/取消/修订/晚返回、第三次合法操作、先减少后延长、失败后新明确操作、无网络跨进程恢复，以及空白库/缺失库/损坏库。

合成组合测试通过正常 job/worker 完成：首篇待审→第二篇资料→v3片段提取→独立审核→非空入库→规划→采用，5次 Fake 模型调用分别计账，并为最终规划留出余额。真实小红书本批未复测。

独立城市、区域交通未定、其他目的地和无缓存场景均不串资料或偏好。历史地点提及仍为 SOURCE_MENTION，不晋升 Evidence；空间范围 UNKNOWN 不伪装 MATCH。

页面实测前发现并修复一个遗漏：地图响应总额仍枚举历史8/10/16，在普通2地点+1路径许可下触发响应校验失败。该失败发生在本地 GET，未发出外部请求，原许可与旅行保留。补充真实 API 序列化测试后重新执行全量回归。

| 实际执行的检查 | 最终结果 |
|---|---|
| `.venv\Scripts\python.exe -X utf8 -m pytest -q --tb=short -o cache_dir=.local/p07-pytest-cache` | 最后一处生产修改后 1112 passed；92.50 秒；2项既有依赖弃用警告 |
| `.venv\Scripts\python.exe -m ruff check .` | PASS |
| `.venv\Scripts\python.exe -m mypy` | 81个配置范围内源文件，无错误 |
| `.venv\Scripts\python.exe tools/export_preview_contract.py` | 契约已同步 |
| `.venv\Scripts\python.exe tools/validate_pack.py` | 12/12；105定义、181引用、38操作、238本地链接 |
| `npm.cmd test`（apps/web） | 六组组件测试 PASS；SSR 测试工具存在 cssVars 提示 |
| `node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` | PASS |
| `node node_modules/vite/bin/vite.js build --outDir ../../.local/workbench-web` | PASS；42 modules；新目录构建未覆盖历史目录 |
| `git diff --check`、暂存区敏感数据扫描 | PASS |

过程中的检查错误没有算作成功：首次新组件 SSR 中的内联 TS 断言已改为脚本方法；Fake 响应构造重复 pop 已修正。一次显式对整个 apps/api/travel_agent 运行 mypy，绕开项目原定 files/follow_imports 范围，报出208个既有宽范围类型问题；项目配置的正式 mypy 命令最终通过。首次受限构建出现 Windows spawn EPERM，正常授权环境完成构建。以上均未产生业务外部请求。

## 真实普通页面验收

以下称历史两项为 A、B；对应真实名称在本机页面显示。公开 Git 报告不保存真实来源名称、片段、原始模型提议、地图候选/坐标或运行标识。

1. 主页面点击“新建独立旅行”，明确填写本次测试的城市、一日、公共交通及步行、10:00首项、往返自行安排，并标记独立验收。驾驶/包车意愿仍 UNKNOWN，游玩范围未定；没有继承旧测试偏好。
2. 从历史采用组合中明确选择原两项版本 A→B，各45–75分钟、休息15分钟。程序从原数据库读取来源和已有建议，页面采用本地草稿；没有 SQL 写活动、Work 手填 AI 时长或批准新证据。
3. 页面设置并确认正常许可：MODEL=2、MAP_PLACE=2、MAP_ROUTE=1，RESEARCH用途未选，CONNECT/SEARCH/DETAIL均0，有效24小时。ID随机创建，没有 P07业务常量。设置许可本身外连为0。
4. 各查询一次公共地点。每次返回多个对象，其中同名、同区、道路类型候选与原公共地点一致，另有小区/交叉口等不同对象；逐一展开依据后选择正确道路，没有盲选地区中心。确认后候选折叠。
5. 对已采用 A→B 方向执行一次 TRANSIT：**OK，有非空结果，页面显示约19分钟**。没有切成驾车/步行补查，没有虚构日期。两项时页面显示 A 10:00起，约10:45–11:15结束；B约11:15–11:50起、12:00–13:05结束。这是停留假设与临时公交估算的向外取整展示，不是未来班次或可行性保证。
6. 第一次模型操作 FEWER：1个提议、1个通过、0个拒绝，程序判定 INTENT_SATISFIED。模型移除 A，保留 B原45–75分钟及15分钟休息。预览后取消，原两项采用版仍在；再次预览并明确采用，当前为一项。
7. 第二次 LONGER_FIRST：未手填增加分钟；模型对实际保留的 B建议上下界各增加30分钟，即75–105分钟。1个提议、1个通过、0个拒绝，INTENT_SATISFIED。再次完成预览→取消→预览→采用，首项10:00、原交通和休息未变。
8. 最终页面实际安排：**第1天10:00开始 B，停留75–105分钟，约11:15–11:45结束，活动后休息15分钟；往返自行安排，公共交通优先并允许步行。** 一项版本没有项目间交通；前述19分钟属于之前两项版本，不混入最终时间。
9. 额度耗尽出现明确提示。关闭本次许可后，用本地天数1→2的临时编辑验证仍可操作，再取消回已采用的一日版本；没有修改模型停留数字。查看、取消、采用、折叠和刷新不增加外部请求。

| 子项 | 结论及限度 |
|---|---|
| 普通新旅行、显式复用、页面许可 | PASS；不依赖固定阶段记录；本轮选择的资料来自历史库 |
| 任意合法改选顺序、独立校验、预览/取消/采用 | PASS；真实 FEWER→LONGER_FIRST；第三次合法操作仅离线 Fake 验证 |
| 同入口地图通路 | PASS；2个公共道路对象确认、1段公交 OK；没有核实未来班次和接驳 |
| 模型/地图能力状态 | 配置存在且本轮实际请求成功；收尾许可 CLOSED、可用0，未做额外“测Key” |
| 普通研究接线 | 离线组合 PASS；真实 XHS 本批 NOT_TESTED，页面此旅行未授权研究 |
| 作者事实/空间范围/可游玩性 | 原标签保留：SOURCE_MENTION、UNKNOWN；不是已审核作者事实或市区 MATCH |
| 完整旅行可执行性及 G1 | 未通过；本批不升级门禁 |

## 非空恢复与安全诊断

整页刷新以及正常停止/重新启动同一8768服务后：新旅行仍为一项采用版，保留两版历史、来源/发现属性、测试标记、折叠、10:00条件、公共交通/步行与一日输入；许可关闭和已用2/2/1不变。新进程读取与页面查看的模型/高德 HTTP、外部DNS/socket均0。

额外新 Python 进程直接禁用 socket/DNS，读取并比较完整 planning 状态与重启前快照，重复读取非空采用版；PASS。临时地图结果按既定策略过期，没有持久化或自动重查。过期不会禁止本地编辑。

两次真实 V3结构提议均可在本地确定性回放。以代码 SHA `c8367b2cc236e8374bbe32ceda204fc768c8aa27` 回放，每笔仍为1生成/1接纳/0拒绝；记录标记 LOCAL_REVALIDATION、external_calls=0、adopted=false，数据库所有表哈希前后相同。它们不是新的模型审核或人工审批。

派发输入审计：两笔分别只含2/1个活动、2/1个必要引用；引用文本/条件加公开名称共196/100字符，均低于每来源6000上限。known_map_values为空，未含私址字段、地图坐标/耗时返回或配置中的真实密钥。安全结构诊断仅在忽略目录，沿用七天保留策略；未提交 Git。

保护检查：活动库升级前所有旧行均仍存在且内容相同，包含 P06当前一项采用版和两版历史、旧许可/消耗/失败/审核；35条Evidence不变；其余5个历史数据库表哈希与46个旧静态文件哈希均一致。原三份未跟踪T03报告未动。

## 真实调用与计量边界

| 项目 | 本批实测 |
|---|---:|
| 模型 HTTP（原 DeepSeek） | 2/2 |
| 高德地点 | 2/2 |
| 高德路径（TRANSIT） | 1/1 |
| XHS connect/search/detail/browser | 0/0/0/0 |
| 连通性测试、额外审核、自动重试、embedding | 0 |
| 项目外部 DNS / socket connect | 5 / 5 |
| 出站边界阻止次数 | 0 |
| 本轮正常许可剩余 | 模型0、地点0、路径0；许可已关闭 |

业务账本与项目进程审计独立一致：model_http=2、amap_http=3。真实服务重启与两笔本地诊断回放均零外连。UI loopback 单列：本报告采样时读取74、修改26、静态12，共112次；bootstrap0，其他0，计数包含早期地图响应契约失败的本地GET。它们不是站点/模型业务请求，后续用户查看会增加本地计数。

计量来自应用派发账本、Python HTTP/DNS/socket审计和本地API计数；整机/浏览器所有后台网络、供应商内部执行次数、准确计费均 NOT_MEASURED。XHS为0依据本轮未创建研究任务、许可三项为0、未启动相关worker/browser，不声称全机抓包。收尾没有 QUEUED/RUNNING/WAITING_LOGIN任务；本轮临时worker已结束，保留8768主服务供查看，不能称全部进程为零。

## 实际使用说明

已运行的主页面：`http://127.0.0.1:8768/`。无需重新启动或重新配置Key；当前展示本轮已采用的一项版本。要开始自己的旅行，点击“新建独立旅行”，只填目的地/想法，明确复用活动或主动研究；页面设置用途与有限额度，然后点击想执行的操作。追加需明确确认，关闭许可后仍可本地编辑。

停止主服务后，可复制以下命令重新打开正常认证入口（不打印一次性票据）：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

本轮静态构建已经完成；代码变更需要重建时：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent\apps\web
npm.cmd run build -- --outDir ../../.local/workbench-web
```

## Git与停止边界

功能/契约提交：`c8367b2cc236e8374bbe32ceda204fc768c8aa27`。实现 diff：33 files changed, 1576 insertions(+), 69 deletions(-)；本报告单独提交。基线完整SHA见首段。初次远端只读核对遇TLS EOF，后续保持证书验证的核对已成功，基线与远端一致；未强推、未合并master。收尾对整个基线到HEAD范围及暂存报告扫描实际密钥、token形状、真实来源ID/正文、数据库、认证资料、图片、私有地点名称和诊断；最终同步SHA由交付消息给出。

保留缺口：来源质量、作者事实、空间范围、开放/预约、旅行日期、末端接驳和未来交通可行性仍待核实；KnowledgeCard、原文清理后知识保留、酒店报价和完整端到端旅程尚未完成。没有启动新研究或下一阶段开发。本轮到此停止。
