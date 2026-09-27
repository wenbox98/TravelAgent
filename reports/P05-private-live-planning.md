# P05 正常私人规划入口：实站与恢复验收

## 结论

**PARTIAL。** 普通私人入口已经串接真实研究、运行时审核、私人规划模型、高德公交及页面采用/修改/恢复；本轮没有得到可采用的 AI 安排，也未证明所得活动符合“成都市区”范围。不能宣称完整城市规划闭环成功。

基线包含 `2be094df2eb1dd8c921a3b07301ff003bd8cd001`，实际功能分支为 `feature/g1-live-llm-validation`，未合并 master。历史 G0 PASS、G1 NOT PASS、G3 原状态不改写。主入口仍为 `http://127.0.0.1:8768/`，保持运行。

| 子项 | 结果 | 证据与边界 |
|---|---|---|
| 普通输入与任务入口 | PASS | 独立私人旅行，`demo=null`、`validation_trip=true`；不手填活动，无历史川西条件 |
| 真实研究与活动投影 | PASS / 范围 PARTIAL | 页面派发搜索、详情、v3 提取与模型上下文审核；得到 4 个来源支持的具体地点，但属于从市区出发的周边一日游 |
| 私人模型通路 | PASS | 原 DeepSeek 实际完成 1 次安排响应；不再由 SYNTHETIC_ONLY 拦截 |
| 可采用 AI 安排 | NOT PASS | `PLANNING_LOCKED_TRANSPORT`；模型输出违反当前明确交通，整份响应未采用，无重试 |
| 地点与公交 | PASS | 2 个公共地点经页面辨认，1 条真实 TRANSIT 成功，秒数进入当前时间线 |
| 步行 / 驾车 | SKIPPED | 未请求，不用公交成功替代步行成功，不用驾车时间替代公交 |
| 修改、预览、取消、采用 | PASS（页面测试输入） | 修改第一项停留与休息，预览未覆盖旧采用版；取消恢复，再修改并采用。不能冒充 AI 改选成功 |
| AI 改选 | SKIPPED | 首份 AI 响应被拒后停止该真实操作，没有消耗第二次规划调用 |
| 非空跨进程恢复 | PASS | 两个采用活动、来源、测试条件、折叠及额度恢复；临时地图过期，未自动查询 |
| 完整行程可行性 | 未验证 | 城区匹配、开放预约、第二项停留、日期和完整交通均有缺口 |

## 实际页面与资料

正常输入为本次开发测试：成都市区一天、公共交通和步行、10 点开始首个项目、往返自行安排。日期、预算、人数未知，驾车/包车未额外代选；不成为长期偏好。

实际 query：`成都 市区 游玩 公共交通 步行 1天 路线 行程 交通`。20 个搜索候选，读取 1 篇新来源，正文完整度 `PARTIAL_TEXT`。12 条定位通过候选经过独立模型上下文审核：

- 接纳 1：`MODEL_CONTEXT_SUPPORTED`，性质为 `GUIDE_SUGGESTION`，不是历史实测、作者计划或当前保证。
- 待审 4：时间上下文不确定 1（`CONTEXT_TIME_UNCERTAIN`），依赖尚未解决 3（`DEPENDENCY_UNRESOLVED`）。
- 拒绝 7：时长范围不匹配 1（`DURATION_SCOPE_MISMATCH`），重要事实未核实 2（`UNVERIFIED_IMPORTANT_FACT`），非旅行证据 4（`NOT_TRAVEL_EVIDENCE`）。

历史 34 条 claims 保持原样，现库 35 条；没有 Work 人工接纳或 SQL 补活动。程序从被接纳路线的地点序列投影出 4 个候选，保留同一 Evidence 与条件，不能说成 4 条独立证据或多个独立来源。页面选取其中的美术馆 A、老街 B，地点名称由程序生成，未把整句路线发给地图。

真实来源地名、作者内容、账号、URL/标识、地图返回和坐标仅在私人运行环境处理，不进入 Git。本机页面与交付消息提供实际活动名称；此公开报告用 A/B 表示，不能作为页面的手写数据源。

初次实站在获得至少两个候选时以 `ACTIVITY_CANDIDATES_READY` 提前停止。后续审查发现来源描述“从市区出发”，不足以满足本次市区要求。已修复：保留范围缺口，阻止这一上下文满足数量提前停止条件；页面在预算允许时仍可补充研究。修复仅离线验证，未重开研究或再读第二篇，也不是完备的城市地理边界检查。

Coverage 继续保留：路线 Q1 PARTIAL，体验 Q2 / 时长 Q3 / 限制 Q4 UNSUPPORTED；单来源、正文不完整、图片未分析、实际旅行时间未知、天数适配和条件关联等缺口不消失。

## 建议、时间与地图

首轮“少量项目/多种体验”明确是节奏选择；实际候选来自审核引用。选择 A/B 后，经正常页面发出一次私人安排请求，模型 HTTP 响应完成，但交通约束校验不通过。没有 AI 停留/休息被采用。程序保留失败原因及原草稿，不额外审稿、不重试。

当前实现对任一提议的硬约束错误会拒绝整个响应；本次没有保存可重新审查的原始规划响应，因此不能宣称其中其他建议已成功或通过本地回放补救。后续若要改善部分保留，需要另行定义验收，不在本批追加模型请求碰运气。

地点查询不是按首条盲选：页面核对区域及对象类型，A 区分其他同名/近名场馆；B 区分景区对象与道路名称。无用户私址、城市中心猜测或设备定位。日期仍未知，未自动填今日。

一次真实公交查询成功。接口返回的是公交总耗时；页面使用原秒数转换，不再加一次换乘/等待，不把它当作假期班次保证。只查采用顺序 A→B，没有候选全排列查询，没有步行/驾车兜底。

为完成页面修改验证，Work 在页面明确输入 **A 停留 60–90 分钟、休息 15 分钟**。界面标注“本轮页面测试假设，非作者耗时或长期偏好”。首项 10:00，结束 11:00–11:30；下一项窗口按“首项结束 + 15 分钟 + 当前公交总耗时”计算，实站时已显示非空窗口。B 停留和终点结束仍未知。地图秒数及派生窗口不写入本报告、数据库、日志或恢复文件。

修改前采用版的停留未知；预览新数值时旧采用版未变；“恢复已采用版”恢复未知停留；再次输入同一测试值并采用。现场发现数字字段自动保存不稳定，增加有效输入的延迟自动保存兜底；重新通过页面确认保存成功。

正常重启后 A 的 10:00 与 11:00–11:30 保留，B 显示“待交通核实”。“地点确认与相邻路段”明确提示临时结果已过期；不是地图恢复失败后自动重查，也没有将旧 ETA 冒充有效值。AI 成功采用/改选只能列离线验证，本轮真实没有该成果。

## 调用、计量与安全

固定账本 `p05-private-live-planning`，仍在同一工作区及旅行；未重置 P03/P04 或任何历史批次。

| 操作 | 实际 / 本批上限 | 剩余 |
|---|---:|---:|
| XHS connect | 1 / 1 | 0 |
| XHS search | 1 / 1 | 0 |
| XHS detail | 1 / 2 | 1 |
| 项目模型总计 | 3 / 6 | 3 |
| 高德地点 | 2 / 6 | 4 |
| 高德路径 | 1 / 4 | 3 |

模型分别为提取 1、上下文审核 1、规划 1；原配置 DeepSeek，实际 requested_model=`deepseek-v4-flash`、response_model=`deepseek-flash`，未更换。响应等待 120 秒、单次总截止 180 秒，无连通性测试、自动重试或额外命名/排名。每次仅在原过滤规则、每篇 6000 字限制内构造正文/引用；私人规划不发送自由请求、私址端点、地图值或凭据。用户私人研究许可不等于作者/平台授权。

BrowserSession 1，正常关闭保留 profile。浏览器 context observer 从挂载后记录：

| 窗口 | request events | document navigation |
|---|---:|---:|
| LOGIN | 191 | 1 |
| SEARCH | 170 | 3 |
| DETAIL_1 | 188 | 1 |
| OUTSIDE_WINDOW | 36 | 0 |
| 合计 | 585 | 5 |
| DETAIL_2 | NOT_MEASURED（未读取） | NOT_MEASURED |

合计 550 finished、35 failed，OBSERVE_ONLY 无资源拦截。实际发送数、传输字节 NOT_MEASURED；缓存、service worker、资源重试 UNKNOWN。应用一次搜索不等于一次浏览器 HTTP。站点脚本含 POST 和一个按路径归类的 comment 请求，不能据此推断用户发帖/评论；本程序未调用任何平台写操作。此次不宣称低请求性能改善。

Python 审计独立于浏览器：三个模型子进程各记录一次 model_http；原主服务记录 amap_http=3；研究子进程 Python 外连为 0，不能据此声称浏览器零网络。重启后的主服务 model_http/amap_http/external_dns/external_socket/blocked_external 全为 0。跨进程只读恢复探针禁止 socket/DNS，恢复非空。刷新、折叠、保存与取消/采用未增加账本或外部调用。

没有额外实站请求来修复失败，没有验证码绕过、代理、指纹修改或平台写行为。认证 profile 未读取入普通日志；扫描不输出 Key/Cookie/token 实值。全机器网络包及其他进程后台网络 NOT_MEASURED，Git 同步独立于业务调用统计。

## 变更与契约

- `planning/flow.py::PlanningService`、`materials::{references,activities,scope_gaps}`：同目的地/同 scope 缓存合并、来源短名投影、研究/采用链路、范围提醒与时间区间。
- `private_budget::PrivatePlanningBudget`：复用 BoundedBudget 持久许可，绑定工作区、原模型和当前旅行；无需新表。
- `private_payload::{payload,ground}`、`suggestions::{payload_for,validate_response,apply_proposal}`：私人资料最小输入、可选同调用短名选择、当前引用重新校验、约束保护、失败不自动再调用。
- `preview/jobs`、`preview/worker`、`ResearchService`：正常 v3 提取审核任务，两个活动的有条件提前停止；后续错误保留前面独立接纳结果，安全关闭浏览器。
- `flow_maps::PrivateFlowMapService`：真实公共活动地点与采用顺序相邻边；地图临时存储，不进入模型/数据库。
- `network::install`、`scripts/product_preview.py`：原主入口角色级出站边界、服务端既有 Key、独立 P05 静态目录。
- `PlanningPanel.vue`、`PlanPlaces.vue` 与 DTO：正常研究进度、候选/引用、明确失败原因、测试输入来源、自动保存、地图及额度展示。
- `domain.schema.json` / `openapi.yaml` 与导出工具同步：增加 validation_trip、活动说明/引用性质、步行意向、改选指令、研究动作和状态字段；地图总额度兼容本批 10 与历史 16。明确契约变更提交，DB schema 15 无迁移。

## 验证与保护

最后一次代码修复后实际执行：

- `.venv\Scripts\python.exe -m pytest -q`：**1037 passed，67.14 秒**，2 条既有 Starlette 弃用警告。
- `.venv\Scripts\python.exe -m ruff check .`：通过；修改的 Python 文件已格式检查。
- `.venv\Scripts\python.exe -m mypy`：75 个源码文件通过。
- `pnpm.cmd test`：ReviewPanel、RoutePanel、PlaceChoices 三组通过；既有 SSR cssVars 提示保留。
- `pnpm.cmd exec vue-tsc --noEmit` 与 `pnpm.cmd exec vite build --outDir ../../.local/p05-web`：通过，33 modules。未覆盖旧构建。
- `tools/validate_pack.py`：98 definitions、173 references、38 operations、239 Markdown links 等离线文档/SQL/fixture 检查全部通过。
- `git diff --check`：通过，仅有 CRLF/LF 规范化提示。
- 独立只读恢复探针及历史保护检查：非空恢复、预算不变、旧行保留、旧库/静态哈希一致全部通过。实际页面验证与离线替身结果在前述表格分别列出。

实站前全量 1032 passed；曾出现一个测试替身不接受新的 worker 关键字参数，修复透传后原测试通过。其后根据实站发现补区域检查、自动保存和部分结果保留等，最终再运行全量。

历史保护：原 P01/P02/P02.1/P03/T06.2 五个数据库逐表哈希与开始时一致，原静态目录未变；当前活动库旧表全部历史行仍为子集，旧 34 条 Evidence、审核、采用版和预算未改写。仅新增本批会话、资料、操作及回执。

备份位于本机忽略目录 `.local/p05-backup`：升级前一致 SQLite 备份、P04 静态文件及基线代码归档。活动库仍为 `.local/p04-preview/preview.sqlite3`，静态目录 `.local/p05-web`。未在 Git 中存储运行数据库、真实内容、地图结果、登录截图或审计原始数据。原三份未跟踪 T03 报告不触碰。

## 启动与回滚

主页面已运行，直接访问 `http://127.0.0.1:8768/`，不要重复启动。之后需要启动时：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py --open
```

需重新构建时在 `apps/web` 执行 `pnpm.cmd exec vue-tsc --noEmit` 和 `pnpm.cmd exec vite build --outDir ../../.local/p05-web`。不会覆盖原静态构建。不要再次 authorize 或恢复旧数据库来重置预算。

回滚代码应先正常停止自有 8768 服务，保全当前 P05 库和账本，再使用本机基线代码/静态备份在隔离目录恢复旧预览。升级前 SQLite 仅作历史只读核对，不覆盖当前活动库或重新启用旧额度。回滚完整旧版浏览本轮没有实际演练，不能列为实测 PASS；不自动重启其他端口。

本批不继续新功能、追加抓取或模型调用。剩余问题是城区资料适配、可采用的 AI 安排，以及真实行程日期/开放/停留/交通缺口。

## 提交与实际 diff

代码及显式契约变更提交：`507024839dc3862b8d1c369a464faa2a5f21d5f3`。报告与文档验证结果单独提交。

```text
 README.md                                         |   7 +-
 apps/api/travel_agent/planning/flow.py            | 207 ++++++++--
 apps/api/travel_agent/planning/flow_api.py        |  29 +-
 apps/api/travel_agent/planning/flow_maps.py       | 100 +++++
 apps/api/travel_agent/planning/flow_models.py     |  26 +-
 apps/api/travel_agent/planning/materials.py       | 111 ++++++
 apps/api/travel_agent/planning/models.py          |   2 +-
 apps/api/travel_agent/planning/network.py         | 111 ++++++
 apps/api/travel_agent/planning/private_budget.py  | 112 ++++++
 apps/api/travel_agent/planning/private_payload.py | 137 +++++++
 apps/api/travel_agent/planning/suggestions.py     | 122 +++++-
 apps/api/travel_agent/preview/jobs.py             |  39 +-
 apps/api/travel_agent/preview/worker.py           |  65 ++-
 apps/api/travel_agent/providers/llm.py            |   4 +
 apps/api/travel_agent/research/bounded.py         |   2 +-
 apps/api/travel_agent/research/models.py          |   2 +-
 apps/api/travel_agent/research/service.py         |   8 +-
 apps/web/src/App.vue                              |   2 +-
 apps/web/src/components/PlanPlaces.vue            |   2 +-
 apps/web/src/components/PlanningPanel.vue         |  46 ++-
 apps/web/src/planning-api.ts                      |   6 +-
 contracts/domain.schema.json                      | 162 +++++++-
 contracts/openapi.yaml                            |  12 +-
 docs/architecture/p05-private-live-planning.md    |  38 ++
 scripts/product_preview.py                        | 131 +++---
 tests/helpers/workbench_server.py                 |   4 +-
 tests/integration/test_private_planning.py        | 466 ++++++++++++++++++++++
 tools/export_preview_contract.py                  |   2 +-
 28 files changed, 1759 insertions(+), 196 deletions(-)
```

只按明确文件清单暂存。代码提交前扫描 28 个文件，未发现已配置密钥、真实来源 ID/正文、运行库、profile 或敏感二进制。推送前继续扫描整个未推送范围；最终报告提交 SHA、完整远端一致性和 GitHub 链接见交付消息。TLS 校验保持启用，不强推、不合并 master。
