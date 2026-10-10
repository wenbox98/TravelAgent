# P10 住宿专项：真实中止、子进程缺口传递修复

2026-10-10。用途 `FOCUSED_LODGING_AFTER_PIPELINE_FIX`，只处理 B 的住宿片区比较；A 不参与新研究。真实运行代码基线 `7a8a9547b9ad1974f63dd7940dec10891eb5135d`。修复代码提交 `8134a418a2b0d715f6fce08840125604f27ed67d`。

本阶段结论：**真实内容验收未通过；发现问题后中止，缺口传递修复的相关回归通过；全量回归仍有一项原基线失败。G1 仍 NOT PASS，整体 NOT_READY。** 没有新攻略，不将旧攻略或待审住宿候选说成新成果。修复后没有再次请求模型或站点。

## 普通入口与实际运行

检查 `automatic._cached`、监督工具 `CACHE/DECOMPOSE`：只整理当前有效的已审核引用，没有普通入口可对缓存正文执行新提取及独立模型审核。本轮采用已限定的后备路径，而没有脚本直调 provider。

事前保存独立私人 SQLite 备份、61 表 8526 行快照、A/B 草稿及采用历史、原导出、T03 文件和进程指标。通过正常主对话**仅提交一次**住宿研究；服务先建立新许可，再派发调用。新许可关联此前已关闭许可，不重置旧用量。上限为连接 1、搜索 1、详情 2、模型 8、地图 0。

页面一度显示提交超时。先只读查询任务记录，再点击“读取已保存状态”；确认原提交已经保存，未重复发送。这是本机响应确认体验问题，不能记成研究未派发。

需求理解保留 B 的 3 天、AIR 往返、公共交通与步行、不自驾、不租车。监督决策选择 `gap_key=LODGING`；搜索和标题筛选聚焦住宿。只读取一篇此前未读的正文，归一化长度 641 字；没有重新读取旧来源，没有泛查景点。

## 漏检问题与中止依据

`ResearchService.query_gaps()` 已把 LODGING 传给派发闭包，但默认生产派发没有将 `gaps` 传给独立子进程。`preview.worker.extract_worker()` 又固定使用 `("ROUTES", "DURATION", "TRANSPORT")`，覆盖了实际住宿重点。此前服务层测试使用注入派发，未覆盖这一真实子进程边界；本轮检查发现得过晚，第一篇提取已经发生。

发现后从正常页面停止任务，许可关闭，剩余额度不再使用。没有点击再次生成，也没有自动补开下一轮。没有遇到验证码、访问限制或人工登录要求。

提取返回 12 个候选：9 个原文定位通过但仍待上下文审核，3 个因 `REFERENCE_ID_NOT_SENT` 拒绝。9 个待审包括路线 3、交通 2、体验 1、取舍 2、时长 1；两个候选涉及住宿文字。**定位通过不等于语义通过，住宿候选不等于合格住宿证据。**

独立审核请求已发出，取消后才完整返回 HTTP 200。活动许可检查阻止晚到结果入库：审核运行最终 FAILED，未保存审核判定，没有新增 claims/Evidence。真实提取、审核和取消记录保留，没有本地重审冒充新的模型审核。

## 通用修复

没有目的地、景点、来源、旅行或验收编号特判，没有改提示词、事实标准、数据库契约、旧候选或攻略文件。

| 文件与函数 | 修改 |
|---|---|
| `preview/worker.py:model_command` | 为提取子进程携带实际查询的 `research_gaps`，两种启动入口一致；其他子进程不能带这个参数。 |
| `preview/worker.py:extraction_gap_ids` | 只允许最多 32 个、有界长度的大写程序缺口标识，不能携带任意正文或命令行选项。 |
| `preview/worker.py:run_job.dispatch` | 将当前 `query_gaps()` 结果传入真正的子进程命令，保留顺序及空集合。 |
| `preview/worker.py:extract_worker` | 将收到的缺口交给 `ExtractionRecovery.run_reserved`，删除固定路线/时长/交通覆盖；未指定缺口时为空，不自行制造重点。原版本、额度、许可和任务活动检查保留。 |
| `scripts/product_preview.py`、`scripts/live_workbench.py` | 解析并传递同一 `--research-gaps` 参数，不新增普通用户配置门槛。 |
| `tests/helpers/dispatch_worker.py` | 合成页面验收的子进程适配器同步解析及传递参数，不改真实 provider 或业务规则。 |

审核仍独立检查候选的主题、原文片段、条件、依赖和作者角色，不为了研究目标放宽判定。它不需要把住宿目标当成通过指令。

## 实际 wire 证据

诊断记录来自真实组装后的 system message/schema，不是预先计算的预计提示。四次均 HTTP 200、单次 HTTP attempt、retry 0；审核的应用状态因停止而失败。

| 用途 | system_prompt_sha256 |
|---|---|
| 理解 | `f6ff2118464413ac2c1223f7796b04a1b3323fbe35e6c3e3b74a4843f11278fa` |
| 决策 | `c833e48553a19c447fbc3f55e64e7298677bb6be21c61191c854f14fed5bf17b` |
| 提取 | `97b5d6dca019e15d360e85c455b81eb8d34cc332fa7780c196582294ba4ce59d` |
| 审核 | `ccb625a8935984e36f076cb3946715776c7a0cbdc11bf1ed25d4481a156889ed` |

本轮真实提取虽然使用包含住宿说明的新版 system prompt，但其 `research_gaps` 仍被旧子进程固定值覆盖。修复后只有合成 wire 验证，不宣称新的真实住宿内容已经改善。

## 调用数与保留

| 范围 | connect | search | detail | model | 地点 | 路径 |
|---|---:|---:|---:|---:|---:|---:|
| 本用途增量 | 1 | 1 | 1 | 4 | 0 | 0 |
| B 累计账本 | 4 | 6 | 11 | 37 | 2 | 1 |
| A 累计账本（不变） | 2 | 3 | 5 | 36 | 2 | 1 |

四次模型用途为理解、决策、提取、审核。以上业务额度与站点请求量不同。本用途浏览器观测：1 个 session、5 次 navigation、586 个 context request 事件，555 个完成、31 个失败；这是事件观察值，含资源和浏览器后台请求。实际发出请求数、传输字节为 NOT_MEASURED；不把它们写成 586 次已发送请求，也不把后台 POST 当成本工具发布内容。无工具写站点操作、地图、embedding 或报价调用。

真实运行结束后比较旧行：只有 B 的会话状态变化，其他旧行全部逐字保留；既有 claims、知识卡、审核、用量记录均未改写。A 会话完全相同。B 的采用 v2/9 项及 v1 历史完全相同，两份原下载导出及 T03 hash 不变。

本轮唯一草稿条件变化为 `pace: UNKNOWN → RELAXED`：理解模型把“不要求精确时刻或排满每天”归到放松节奏。没有修改原采用版，也未脚本回写旧状态。建议型产品要求和用户节奏偏好是否应分别表达，仍需后续核对，不能宣称所有当前草稿条件逐字不变。

## 回归、部署与恢复

新增 `tests/integration/test_extraction_worker_focus.py` 和 `tests/helpers/extraction_entry_probe.py`，覆盖缺口集合（LODGING、PLAY、ROUTES/DURATION、空集合）、两个真实入口解析、非法参数拒绝，以及普通研究任务 → 子进程命令 → 实际提取 wire → 独立审核。合成生产链路保留原许可，不用注入提取绕过要检查的边界。初始命令边界回归 8 项失败；修复后通过。期间纠正了测试中未声明天数和错误合成数据库文件名的问题，没有为测试改变生产门槛。

已执行相关 9 个测试文件：**135 passed**，两个既有 Starlette/AnyIO 弃用警告。全量离线运行完成：**1683 passed、2 failed，514.73 秒**。其中正常页面合成子进程适配器未接受新增参数，已同步该测试辅助脚本，单项重跑 **1 passed，24.25 秒**；没有再改生产规则。

另一个失败 `test_exact_public_road_auto_match_and_only_selected_adjacent_route` 报 `MAP_SCOPE_UNVERIFIED`。当前工作区单项复现失败；再从 Git 导出完整 `7a8a954` 源码到隔离目录、不复制真实数据库，在原基线上运行同一测试，仍在 `flow_maps.py:379` 失败。因此不是本轮提取参数修复引入；本阶段保留这个既有阻塞，不改变地图范围标准，也不宣称全量 PASS。修正辅助脚本后没有再次运行整个 1685 项套件，以上是完整实际记录。

实际执行的主要命令及结果：

```powershell
# 子进程边界复现：最初 8 个命令上下文用例失败；相关修复后并入 135 项回归通过
.venv\Scripts\python.exe -m pytest tests/integration/test_extraction_worker_focus.py -q --basetemp E:/workSpace/travel-agent-project/focused-lodging-repro-host
# 全量：1683 passed / 2 failed
.venv\Scripts\python.exe -X utf8 -m pytest -q --basetemp E:/workSpace/travel-agent-project/focused-lodging-full-host
# 同步合成适配器后的正常页面复验：1 passed
.venv\Scripts\python.exe -X utf8 -m pytest tests/e2e/test_research_dispatch.py -q --basetemp E:/workSpace/travel-agent-project/focused-lodging-dispatch-host
# 地图范围失败复现；隔离原基线运行同一节点也失败，不允许真实地图请求
.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_place_discovery.py::test_exact_public_road_auto_match_and_only_selected_adjacent_route -q --basetemp E:/workSpace/travel-agent-project/focused-lodging-road-host
```

Ruff 与 `git diff --check` 通过。前端没有修改，不覆盖静态构建。模型接收方仍为现有 `api.deepseek.com`；使用现有过滤及每来源每次 6000 字上限，无私址、凭据或真实地图返回上传。

已正常关闭本任务拥有的旧服务，再以普通本机权限启动修复代码：PID 10996，同一工作区、数据库、静态目录、8768 主入口。启动自检 `ready=true / browser_sessions=0`。正常页面显示任务已停止、采用版 3 天 9 项仍在。

重启后的独立进程禁止 socket/DNS，并只读恢复 A/B 和导出：A 5 天 5 项 v1，B 3 天 9 项 v2，均非空；只读投影导出的 hash 与上阶段一致。刷新、状态、重启、恢复的模型/高德 HTTP、外部 DNS/socket、blocked_external 增量均为 0，未新增任务或额度预约。

## 私人试用与停止点

```powershell
cd E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

页面 `http://127.0.0.1:8768/` 保留。已有服务时启动器只重新打开本机入口；浏览、修改和导出本地采用版不调用外部服务。本阶段不再发送研究消息。

住宿片区优缺点仍没有新的合格证据，没有新规划、预览、采用或新导出版本。A 的区域非自驾衔接和内容缺口、B 的多数地点玩法及住宿缺口继续保留。内容 NOT_READY；禁止将此次修复描述为真实内容验收成功。本用途已关闭，等待独立核对，不能用剩余 4 次模型或未读的第二篇自动重试。

所有真实快照、原文、诊断和账本映射仅留在忽略的 `.local/focused-lodging`。Git 只提交通用代码、合成测试和本报告，不含真实来源标识、正文、Cookie、凭据、profile、数据库或登录截图。不合并 master，不发布稳定版。

本报告暂存前实际执行 `git diff --stat 7a8a954` 的代码/测试差异：

```text
 apps/api/travel_agent/preview/worker.py           | 34 +++++++--
 scripts/live_workbench.py                         |  6 +-
 scripts/product_preview.py                        | 11 ++-
 tests/helpers/dispatch_worker.py                  |  9 ++-
 tests/helpers/extraction_entry_probe.py           | 29 +++++++
 tests/integration/test_extraction_worker_focus.py | 93 +++++++++++++++++++++++
 6 files changed, 171 insertions(+), 11 deletions(-)
```
