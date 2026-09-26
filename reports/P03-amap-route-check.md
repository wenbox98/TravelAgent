# P03 出行条件与高德分段核实

日期：2026-09-26。基线：`69fb39f16932454f840b572f16043b005a1a7fe7`。
分支：`feature/g1-live-llm-validation`，不合并 master。

## 分层结论

**P03 本机功能与离线验收 PASS；高德实站 AMAP_LIVE_BLOCKED_NOT_CONFIGURED；门到门时间 WAITING_TRIP_INPUT。** 不是整轮真实地图验收通过。G0保留历史PASS，本轮未重测；G1仍NOT PASS，G3未通过。T07/T08/T09仅本子范围实现。

已连续交付正常API和Vue：继承当前已确认方向/五天/不自驾 → 两组出行输入 → 来源片段地点建议/候选确认 → 主动分段查询入口 → 模式、时间参考与缺口 → 保存修改预览/取消/采用 → 刷新与重启恢复。无Key时仍可操作本机条件；未伪造地图数值。

## 当前真实资料与计划结论

原34条 Evidence、4来源、旧审核和原确认方向全部保留；仍是25条历史Work、4条模型上下文、5条本地重校验，不重新提取或审核。本轮方向是来源S3的一段已关联 Day1 攻略建议，不是作者亲历证明或完整五天计划。数据库运行时得到四个待确认的地点文字、三个相邻路段，未合并其他日段。

用户“五天、不自驾”已继承。预算、人数、包车倾向未知；时间表达仍只有“国庆”，没有年份/明确出发返回时刻。门到门起点及最终返回点为空，未用区域中心、IP或设备位置代填。

当前结论：这些资料能支持**保留这一日段作为兴趣方向**。它还不能支持五天不自驾的可执行路线。三个路段目前均无真实距离/耗时；地点、车辆或班次、入口及末端接驳、停留、休息、缓冲、开放预约和未来日期适用性均待核实。页面显示 PARTIAL / UNKNOWN / UNVERIFIED。没有新增时刻表、拥堵倍数或费用，也没有把已知部分0误报为全程耗时0。

## 配置、接口和覆盖

本次仅检查进程和Windows用户环境变量是否存在，没有输出Key；两处 AMAP_WEB_SERVICE_KEY 均未配置。没有额外“测Key”请求。

| 接口 | 实现与离线 | 真实结果 |
| --- | --- | --- |
| v5/place/text | PASS：少量候选、城市限定、显式选择、区域/入口区分 | NOT_CONFIGURED，0次 |
| v5/direction/driving | PASS：仅道路参考，不冒充公交或包车可订 | NOT_CONFIGURED，0次 |
| v5/direction/transit/integrated | PASS：城市编码、明确段日期、总耗时不重复相加 | NOT_CONFIGURED，0次 |
| v5/direction/walking | PASS：缺值保持未知、不证明徒步安全 | NOT_CONFIGURED，0次 |

固定HTTPS主机 restapi.amap.com；TLS验证、无重定向、无环境代理、无自动重试。字段、单位和官方依据见 [设计与映射](../docs/architecture/p03-amap-route-check.md)。这是结果列表和手动官方URI入口，不是完整内嵌地图；没有点击出站URI。

真实地点确认0，已核实路段0/3；四个名称目前都只是来源候选文字，不能称为高德已定位的点。没有已采用的系统默认停留时间，也没有实际发送精确私址。

## 隔离与页面操作

独立数据库 `.local/p03-preview/preview.sqlite3` 从当前 `.local/p021-preview/preview.sqlite3` 做online backup；独立静态目录 `.local/p03-web`，端口8768，会话名ta_preview_8768。原8765/8766/8767服务保持进程26740/27100/43832，未停止或重建。

开工后、备份前观察到原P02.1运行页面新增一份未确认需求：preview_sessions和preview_receipts各增加一行；来源和审核表未变。本轮没有调用原服务写接口，也没有回滚这份记录。P03选择最近一次已确认的原五天方向，备份保留新增未确认记录。备份前重新记录只读摘要；备份后至验收四个原数据库逐表摘要均相同。没有把这次运行中外部变化掩饰成开工以来逐字不变。

通过实际浏览器页面执行：

1. 查看34条、五天/不自驾、当前日段、四个候选/三段未知、Key待配置及禁用查询按钮。
2. 暂时预览“愿意比较包车”，保存修改预览；无外部调用，未冒充用户最终选择。
3. 取消修改，恢复UNKNOWN；明确采用保持未知项的原条件。没有采用虚构日期或起终点。
4. 刷新；正常关闭本轮13108服务，重启为28644；页面恢复34条、原兴趣、UNKNOWN包车和已采用条件，额度仍0/8+0/8。

时间输入的时区/跨夜、确切合成起终点、地图成功/失败、STALE和晚到结果、同名中心与入口等在隔离合成测试完成。真实页没有Key，所以不能以合成距离充当当前真实路线结果。原已运行页面的构建、数据库和Cookie均不覆盖。

## 数据、预算和恢复

v14只新增用户条件表、扩展原 continuation_operations 类型。复用现有BoundedBudget原子占位，固定P03批次绑定账号、工作区、原session/option；无新run ID入口。地点8、路线8，合计16不可挪用；失败也消耗，旧模型/XHS额度不变。不同标签和重复点击不重复派发；重启不自动派发，显式重查仍消耗同一剩余额度。

地图返回值仅内存，没有POI、坐标、路线数值或原始响应写入SQLite、日志、checkpoint、报告或浏览器存储。保存和采用只保留用户输入/原Evidence引用。重启地图标EXPIRED_OR_NOT_QUERIED，不声称恢复地图数据。

实际新进程断网恢复：34条/4源、原兴趣及原偏好完全相同，四个来源候选文字、已采用条件和0消耗额度恢复。独立合成子进程另证明：先有非空地点/路线结果并消耗2+1次，重启后只恢复输入/Evidence/2+1计数，地图数值和候选消失，外部请求0。

保护检查：原claims、sources、正文、策略、候选/attempt/batch、模型审核、本地重校验与旧额度行原样保留；共享dist和P02.1静态目录摘要不变；专用profile的1073个文件大小/mtime未变，没有读取Cookie内容。

## 调用计数与测量范围

| 指标 | 本轮实际 | 依据 |
| --- | --- | --- |
| 高德地点 / 路径 / 总计 | 0 / 0 / 0 | 固定耐久账本；剩8/8，合计16 |
| Amap HTTP/DNS/socket 尝试 | 0 / 0 / 0 | 三个P03服务进程审计指标 |
| 被拒绝外部尝试 | 0 | 进程审计钩子 |
| XHS connect/search/detail/browser | 0/0/0/0 | 不安装worker，禁止研究导入，旧账本/profile不变 |
| 项目模型/embedding/审核 | 0 | 无provider调用路径，旧账本不变 |
| P03本机HTTP | 验收截止25次 | 首进程15、两次重启各5；之后用户浏览会增加 |
| 服务内部loopback连接 | 3 | 三进程各1，用于本机事件循环唤醒 |
| 整机/浏览器后台流量 | NOT_MEASURED | 未系统抓包，不能声称整机零联网 |

官方文档浏览和GitHub同步单列，不计入高德应用额度；没有将这些活动隐藏成整机零网络。合成HTTP替身的请求不计为真实高德请求。

## 验证与代码

新增失败用例先确实因缺模块失败；随后实现并验证。最初普通沙箱测试临时目录和构建子进程受限，使用获准的本机离线执行后通过，没有放开测试外网。

- 完整Python回归：最终执行 `.venv\Scripts\python.exe -m pytest -q`，994 passed、2 warnings，76.93秒；包含最后的地点改名来源标记回归，无真实接口请求。
- 曾执行定向测试31 passed（含契约）；最终全量已覆盖这些用例及新增改名测试。
- Ruff PASS；配置范围Mypy PASS（66文件，新增planning/adapter已纳入）。
- Vue实际模板测试PASS；vue-tsc与独立Vite构建PASS。两个既有Starlette弃用提示及SSR测试cssVars提示不影响断言。
- 契约导出一致、文档链接/SQL/JSON检查PASS；git diff --check PASS。
- 实际页面修改/取消/采用、刷新和服务重启PASS；独立恢复脚本PASS。
- 合成sentinel检查覆盖Key/含Key URL/私址错误不泄漏；返回POI/坐标不落SQLite。提交前扫描真实配置值、源ID及正文片段；原三份T03报告不暂存。

主要实现：providers/amap.py（官方投影）、planning/{models,budget,service,time_check,api}.py（输入/临时结果/计数/时间/API）、PreviewConfig路由与隔离Cookie、migration014/领域/OpenAPI同步、RoutePanel/route-api与独立启动脚本。共享预算仅抽出reserve_count，旧许可逻辑继续原样执行。

最后检查修复了地点编辑的来源标记：用户修改来源地点名称后标为USER_INPUT，同时保留原名称和Evidence引用；不将改写文字冒充已审核来源，不改原Evidence。离线测试验证采用、重新创建服务后的恢复及原审核视图不变。

## 启动和剩余输入

页面已实际运行：[P03](http://127.0.0.1:8768/)。交付时服务PID39768；已有服务时直接使用页面。首次入口由--open打开本机短时入口，不需要用户复制Cookie。

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\route_preview.py --open
```

需要重建本轮页面时：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent\apps\web
npm.cmd test
npm.cmd run build -- --outDir ../../.local/p03-web
```

剩余最小事项：在本机用户环境变量配置Web服务类型AMAP_WEB_SERVICE_KEY，重开终端并重启P03；在页面填实际出发/最晚返回时刻、公共起终点及包车倾向，再主动检索、逐项确认地点并按剩余额度查相邻路段。未确认日期可先一般参考；门到门结论仍等待实际输入。Key不要发送到聊天/前端/Git。

本轮停止于此，不进入报价、酒店、模型或新的小红书研究。Git提交与远端完整SHA核验在最终汇报中记录；未强推、未关闭TLS、未合并master。

## Git 与变更范围

实现及契约提交：`2b4617930a697ab9fb4149d87b529b36fc46045c`（feat(p03): add bounded Amap route preview and contracts）。基线是其祖先；README、本文和文档验证结果另作验收提交。完整待推送范围逐提交扫描密钥、私有正文/源ID、数据库和认证材料，具体同步结果以最终本地/远端SHA核对为准。

实现提交实际 `git diff --stat 69fb39f16932454f840b572f16043b005a1a7fe7..2b4617930a697ab9fb4149d87b529b36fc46045c` 摘要：

```text
32 files changed, 3492 insertions(+), 13 deletions(-)
```

核心符号：AmapAdapter.resolve_place/route、MapBudget.initialize/reserve_map、RoutePreviewService.get/mutate、seed_places、check_time、MapAction/MapView、PreviewConfig.route_check、BoundedBudget.reserve_count。领域Schema和OpenAPI同步新增地图预览DTO/两个操作，数据库迁移v14；共1121行新增领域Schema属于生成契约，不是新增业务服务。

新增测试只使用合成地点、合成响应和禁网子进程。原三份未跟踪T03报告保持未跟踪；本机数据库、静态构建、审计摘要和入口认证文件均位于忽略目录，不进入Git。
