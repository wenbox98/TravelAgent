# P04 产品流程纠偏与合成规划验收

执行日期：2026-09-27。基线包含 `61985251728ca75b383558dd1f85960bc1d6531b`，实际功能分支 `feature/g1-live-llm-validation`。本报告只含程序行为、计数与自编合成场景，无真实正文、地址、来源 ID、Key、Cookie 或地图原始返回。代码/契约与报告分开提交，历史样例未修改。

## 分层结论

| 层次 | 结果 | 边界 |
| --- | --- | --- |
| 产品交互 | PASS | 三种合成旅行经过正常页面新建、修改、采用、恢复；另验普通苏州缓存未命中 |
| 运行时 AI 建议 | PASS | 城市与区域各 1 次真实模型请求，各返回 2 个提议，经程序校验后由页面显式放入草稿及采用 |
| 来源质量 | 保留历史结果 | 34 条 Evidence、旧审核原样保留；本批没有提取/审核新来源；G1 仍 NOT PASS |
| 交通可行性 | NOT_VERIFIED | 本批高德 0 次；合成地图只验交互，不能证明路线真实可行 |
| 门禁 | 不升级 | G0 保留历史 PASS，G1 NOT PASS，G3 不变 |

不是只改文档：主页面与 API 已运行，唯一推荐入口为 `http://127.0.0.1:8768/`。临时 8769 已关闭。原 P03 服务正常停止，原库、原静态目录、历史选择和预算保留，可回滚。

## 复现后的纠偏清单与落点

| 原问题 | 修改后的正常操作 | 主要符号/文件 |
| --- | --- | --- |
| 新行程默认公交，研究时的五天/不自驾容易进入新偏好 | 新建仅解析当前输入；交通、驾驶、包车未定保持 UNKNOWN；历史会话单独保留 | `TripInputs`、`PreviewService.open`、`PlanningService.create` |
| 固定川西/国庆报告与缓存示例偏置 | 标题来自当前 request；按目的地精确匹配资料，多匹配或未命中不借用其他目的地 Evidence | `render_private_report`、`ResearchReport.material_view`、`PlanningService.create` |
| 用户先处理全部字段，方向/候选确认后仍挤在主页面 | 先给方向与建议；已完成方向、项目、条件收起；改选预览、取消、采用均可逆；地图细节和诊断可展开 | `PlanningPanel.vue`、共用 `PlaceChoices.vue`、原 `RoutePanel.vue` |
| 往返同点重复输入、重复选地点 | 默认“返回出发点”为可修改假设，异地结束才展开；复用已确认 identity 一次；返程边独立保留 | `TripInputs`、`RoutePreviewService._view/mutate`、`PlaceChoices` |
| 未知到达方式阻塞整套安排 | 默认 ACTIVITY_WINDOW，从首个项目时间排；DOOR_TO_DOOR 可选；最晚返回硬约束继续保留 | `timeline`、`check_time`、`PlanDraft` |
| 只有提取/审核，没有运行时安排提议 | 新 `planning_suggestion`，建议顺序/停留/休息/首项时间；引用和约束校验后供选择，不自动覆盖确认版 | `PLANNING_PROMPT`、`PlanningResponse`、`suggestions.run_worker/apply_proposal` |

其他改动：`flow_api` 复用原同源鉴权和幂等；`FlowMapService` 复用原地点/分段生命周期；`product_preview.py` 负责独立副本、静态目录、固定许可和外连边界。`migration 015` 只调整研究 job 唯一索引的规划任务适用范围，不新增业务表。Schema/OpenAPI 与导出工具同步更新。

现场检查还修复：首日 10 点不再复制给第二天；重复建议请求只启动一个监督任务；正常停服先使未完成任务失效再关闭自身 worker；旧 P03 缺少范围字段时按原门到门语义读取且不重写；DRIVING 参考不得参与公交/未定交通的时间计算；改日期使旧路段参考失效。

## 三个实际页面输出（全部合成）

以下活动、地点和区域均为自编虚构，城市名只是测试标签，不是用户真实行程或当地事实。不是 Work 将攻略手写入运行数据库：三个场景均由页面“历史旅行与合成场景”的普通新建动作生成；前两次由页面按钮启动实际模型任务，按程序返回提议选择后采用。

| 场景 | 实際采用的活动草案 | 程序时间与未定项 |
| --- | --- | --- |
| 成都城市观光两天，明确选公交（合成） | 第一天云台园 90–150 分钟，休息 15；纸舟工坊 60–120 分钟，休息 15。第二天星河展厅 90–150 分钟，休息 20 | 首项 10:00 → 11:30–12:30；第二项因移动未知显示“待交通核实”；第二天开始时间另待选择；公交意向保留 |
| 成都到川西，交通未定（合成） | 采用模型方案 B：第一天纸舟工坊 60–120 分钟，休息 20；云台园 60–90 分钟，休息 15。第二天星河展厅 90–180 分钟，休息 20 | 首项 10:00 → 11:00–12:00；后续交通未知；未继承五天、不自驾或拒绝包车，交通仍 UNKNOWN |
| 苏州两日（合成） | 云台园 → 纸舟工坊 → 星河展厅；页面把首项停留改为 60–90 分钟，后两项停留未填 | 首项 10:00 → 11:00–11:30；第二项待交通核实；第二天开始时间待选。21:00 返回硬约束保留且未声称满足；本场景没有模型调用 |

区域场景还保留模型方案 A 供查看：原顺序云台园 60–90、纸舟工坊 90–120、次日星河展厅 90–150 分钟。它和方案 B 都是可修改假设，不是已查服务或作者实际路线。

此外从普通“新建独立旅行”输入“苏州 / 两天”：显示苏州标题、两天当前输入，交通/驾驶/包车未知，0 条匹配 Evidence、0 个自动填充活动；页面给出两个可比较类别，并说明尚无本地匹配资料。没有将合成活动或川西原文填入私人草稿。

## 页面操作与离线场景结果

| 验收场景 | 实际验证方式 | 结果 |
| --- | --- | --- |
| 城市公交、区域未定、非成都独立场景 | 浏览器逐个新建、选方向、采用；前两场景实际 AI；后两场景没有继承公交 | PASS |
| 10 点开始、往返自行安排 | 无家庭地址仍产生首项可计算结束区间 | PASS |
| 四个同名候选、跨虚构地区歧义 | 页面看见四个候选，选择一个收起其余，重新选择展开本地结果 | PASS；没有新真实查询 |
| 同点往返 | 在苏州合成草稿切门到门，填写虚构公共站，一次 origin 选择复用给 return；逻辑返程仍在 | PASS |
| 改成异地结束只影响相关边 | 离线 service 生成不同方向参考，再改终点，内段保留、末端失效 | PASS（合成，不是高德实站） |
| 大方向改选/取消/采用 | 页面选择另一方向出现差异；取消恢复原方向，停留与 21:00 约束保留；恢复采用版重新收起 | PASS |
| 拒绝包车但查看道路参考 | 离线保持 charter=NO、mode=DRIVING；未把道路参考写成接受自驾/包车 | PASS |
| 公交空返回 | 合成适配器返回 NO_ROUTE_RETURNED，无时长；计划保留，不切驾车补齐 | PASS（未做真实公交查询） |
| 固定预约、返回硬约束、未知移动 | 离线校验模型不能删除/改日锁定预约，首项锚点不可移动；页面 21:00 从门到门切回活动窗口仍保留 | PASS |
| 合法已知移动和休息 | 合成单位用例逐段计算停留 + 20 分钟参考 + 15 分钟休息；下一未知段中断精确时刻 | PASS |
| 模型失败/无配置/恶意输入 | 离线拒绝任意 ID/URL/未经支持的地图事实；原草稿不变，无工具调用；错误脱敏 | PASS |
| 取消/旧 revision/重复任务/180 秒截止 | 离线 Fake 验证不发布晚结果、只启动一个 worker、不返还额度、正常停服处理自己的任务 | PASS |
| 多来源材料组合 | 离线通过合法缓存投影添加两组来源活动，保留 Evidence 引用和条件，标系统草稿 | PASS；未改写为作者亲历完整行程 |
| 刷新/重启恢复 | 实际重启后 4 个独立草稿恢复，其中 3 个采用版非空；活动/锚点/采用版/折叠状态摘要哈希相同 | PASS |
| 地图临时性 | 重启后原候选和确认消失，页面明确临时结果过期，活动和输入保留 | PASS；无自动重查 |

确认后的页面已做可视检查；旧模型提议移入可展开区，“来自 AI 建议”不会因为用户采用就改称事实或显示成尚未采用。

## 最少输入与数据含义

新旅行只需目的城市或区域即可先看方向，旅行想法和天数可空。选方向后进入项目，可添加/修改活动，再填首项时间或相对时段；普通字段自动存本地草稿，整体只有采用/恢复。没有缓存时仍能选类别和编辑项目，但不会冒充已研究完成。需要当前可行性结论时，实际项目、同名地点歧义、具体交通方式、必要日期与预约仍须明确，这些确认不能靠猜测省略。

- 产品默认：返回出发点、活动窗口与两种初步方向，均可修改。
- 本行程用户输入/确认：当前交通意向、锚点、停留、锁定预约及采用版，不跨旅行继承。
- AI_PROPOSED：建议顺序、停留、休息和未定锚点，保留简短理由、假设、引用、未知与取舍；采用后也不成为来源事实。
- SOURCE_REFERENCE：来自已有严格投影的 Evidence，保留引用及适用条件；组合是系统安排，不代表作者完整走过。
- SYNTHETIC_TEST：本轮虚构活动和本地地图 fixture，醒目标识；不进入真实私人模式的缓存缺口。

本批没有新增长期记忆。普通私人草稿的外部 AI 操作关闭，两个合成许可已用完，不能通过新建旅行或重启恢复。

## 真实调用、预算与数据保护

| 项目 | 本批新增 | 证据与测量范围 |
| --- | --- | --- |
| DeepSeek planning_suggestion | 2 | 两条耐久 MODEL 消耗，两条 COMPLETED job；各 HTTP 200、http_attempts=1、retry_count=0，各 2 个 schema 合格提议 |
| provider / 总截止 | 120 / 180 秒 | 实际请求约 19.49 秒、13.57 秒；截止和取消另外用离线 Fake 验证 |
| 模型 DNS / socket / HTTP | 2 / 2 / 2 | 本项目 worker 运行时审计值；原配置服务 api.deepseek.com；没有测连接请求 |
| 小红书 connect/search/detail/browser | 0/0/0/0 | 未安装对应业务路径到本入口，外连防护+账本差分；无新浏览器进程或真实访问 |
| 高德地点 / 路径 | 0/0 | 本入口真实高德禁用；原账本仍 5/8、2/8，剩余 3/6 |
| 最终主服务外连 | 0 | 新进程启动及恢复浏览后 model_http/model_dns/model_socket/amap_http 均 0，blocked_external=0 |
| 全机器网络包、其他进程/浏览器后台访问 | NOT_MEASURED | 未抓包；Git 同步流量独立于研究与模型计数；不把项目计数说成整机绝对零流量 |

模型使用原配置，诊断 requested_model=`deepseek-v4-flash`、response_model=`deepseek-flash`，本批未更换配置。模型输入由 allowlist 生成：服务端自编活动名/虚构区域及枚举、数字、时间；不发送自由请求文字、私人端点、缓存原文、真实账号或任何地图值。没有自动重试、额外审核或追加请求。

保护核对：原 P01/P02/P02.1/P03/T06.2 五个数据库逐表哈希与批次开始一致；P03/P02.1/原 apps/web/dist 的受保护静态文件哈希一致。P04 副本保留原 49 个数据表全部旧行（schema_version 单独迁移），34 条 claims 不变。新增规划会话/回执/job/许可与合成操作独立；旧预算、失败记录、原文和审核均未改写。地图候选/返回只在进程内，重启恢复不带候选坐标或确认对象。

## 运行与回滚

当前已运行主入口：`http://127.0.0.1:8768/`。不要重复启动。之后唯一推荐命令（本机已构建）：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py --open
```

需要重建前端时，在 `apps/web` 执行 `npm.cmd run build -- --outDir ../../.local/p04-web`。不会覆盖历史静态目录。服务只监听 127.0.0.1。

原 P03 PID 7520 已核对命令属于 route_preview 后，通过原终端 Ctrl+C 正常关闭；临时 P04 8769 同样正常关闭，未批量结束其他进程。最终 P04 使用 `.local/p04-preview/preview.sqlite3` 和 `.local/p04-web`，停服保留选择/额度。原 `.local/p03-preview`、`.local/p03-web` 未变；迁移前备份保留。

回滚：先在 P04 所在终端 Ctrl+C 正常停止，然后在同一仓库运行 `.venv\Scripts\python.exe -X utf8 scripts\route_preview.py --open`。回到原 P03 数据与静态页面，不把新草稿覆盖回旧库。回滚命令可用性沿用原入口及离线回归，本轮没有为了演示回滚再次启动旧页面或查询高德。

## 实际检查命令和结果

- `.venv\Scripts\python.exe -m pytest -q`：1018 passed，58.19 秒，2 条既有 Starlette 弃用警告。之后最后增加“道路参考与交通意向匹配”的检查、日期失效覆盖，再执行 `tests/integration/test_planning_flow.py`：22 passed；其他代码未变。
- `.venv\Scripts\python.exe -m mypy`：71 个文件通过（最后修改后再次通过）。
- Ruff：修改的 planning 服务与测试静态检查通过；格式检查已执行。
- `npm run build -- --outDir ../../.local/p04-web`：Vue 类型检查及 Vite 构建通过，33 modules；只生成独立目录。
- `npm test`：ReviewPanel、RoutePanel、PlaceChoices 三组通过；Vue 测试编译器 cssVars 提示不影响结果。
- `tools/export_preview_contract.py`、`tools/validate_pack.py`：97 schema definitions、171 references、38 operations、238 Markdown links 与其他文档/SQL/fixture 检查通过。
- `git diff --check`：通过，仅有仓库 CRLF/LF 规范化提示。
- 浏览器：正常页面操作、方向取消、候选重选、同点返程、实际重启恢复、页面可视布局检查已执行；无登录截图或实站截图入 Git。

提交前/全未推送提交范围扫描密钥、认证派生值、真实来源 ID/正文/地址、数据库/profile/图片/调试文件。仅显式清单暂存；原三份未跟踪 T03 报告保留。最终 Git 同步 SHA 在交付消息中给出，不强推、不关闭 TLS、不合并 master。

本轮到此停止。未验证真实新城市路线、公交班次、交通可行性、开放时间、票务/酒店、真实攻略质量或长期偏好学习，不升级历史门禁。

## 代码与契约 diff 摘要

代码/契约提交：`8fe7db51c0f08d30f9377a707ac6d4b9a0492877`。实际 `git diff --stat 61985251728ca75b383558dd1f85960bc1d6531b..8fe7db51c0f08d30f9377a707ac6d4b9a0492877`：

```text
README.md                                     |  18 +-
 apps/api/travel_agent/persistence/database.py |   3 +-
 apps/api/travel_agent/planning/api.py         |   1 +
 apps/api/travel_agent/planning/flow.py        | 463 ++++++++++++++++
 apps/api/travel_agent/planning/flow_api.py    | 110 ++++
 apps/api/travel_agent/planning/flow_maps.py   | 188 +++++++
 apps/api/travel_agent/planning/flow_models.py | 153 ++++++
 apps/api/travel_agent/planning/models.py      |   7 +-
 apps/api/travel_agent/planning/service.py     |  69 ++-
 apps/api/travel_agent/planning/suggestions.py | 418 +++++++++++++++
 apps/api/travel_agent/planning/time_check.py  |  16 +-
 apps/api/travel_agent/preview/api.py          |  11 +-
 apps/api/travel_agent/preview/models.py       |   1 +
 apps/api/travel_agent/preview/service.py      |   9 +-
 apps/api/travel_agent/providers/llm.py        |  18 +-
 apps/api/travel_agent/research/models.py      |   3 +-
 apps/api/travel_agent/research/reporting.py   |   8 +-
 apps/web/package.json                         |   2 +-
 apps/web/src/App.vue                          |  11 +-
 apps/web/src/api.ts                           |   2 +-
 apps/web/src/components/PlaceChoices.vue      |  24 +
 apps/web/src/components/PlanPlaces.vue        |  15 +
 apps/web/src/components/PlanningPanel.vue     |  93 ++++
 apps/web/src/components/RoutePanel.vue        |  19 +-
 apps/web/src/planning-api.ts                  |   8 +
 apps/web/src/route-api.ts                     |   4 +-
 apps/web/tests/place-choices.mjs              |  25 +
 apps/web/tests/route-panel.mjs                |   2 +-
 contracts/domain.schema.json                  | 740 +++++++++++++++++++++++++-
 contracts/migrations/015_planning_jobs.sql    |   5 +
 contracts/openapi.yaml                        | 181 +++++++
 docs/01-product.md                            |   4 +
 docs/architecture/p04-product-flow.md         |  41 ++
 scripts/product_preview.py                    | 202 +++++++
 tests/integration/test_planning_flow.py       | 557 +++++++++++++++++++
 tests/integration/test_route_preview.py       |  39 +-
 tests/unit/test_amap.py                       |   1 +
 tests/unit/test_coverage_closure.py           |   8 +
 tools/export_preview_contract.py              |  12 +-
 39 files changed, 3435 insertions(+), 56 deletions(-)
```

报告与文档验证输出另行提交。未修改或提交历史 T03 三份未跟踪报告。
