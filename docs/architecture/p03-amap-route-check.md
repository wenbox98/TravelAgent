# P03：当前方向的地点与路程参考

## 已有能力和本轮边界

P01/P02.1 已有已审核缓存投影、条件、确认兴趣、取消/采用、revision/幂等、同源鉴权和 SQLite online backup。原 AmapAdapter、TravelMatrix、完整规划工作台只是任务文档目标；没有可直接调用的实现。本轮新增 planning 小模块、官方 v5 adapter、确定性部分时间计算和 Vue RoutePanel，沿用现有 FastAPI/Preview 启动与账本，不新增研究任务执行器。G0 保留历史结论，G1 NOT PASS；T07/T08/T09 均只完成本子范围。

P03 从当前 P02.1 副本备份，选择最近一次**已确认**且引用有效的兴趣；未确认的新需求不会取代原决定。grant 固定绑定该 session、option、account scope、工作区绝对路径摘要。正常入口固定 .local/p03-preview、.local/p03-web；原页及共享 dist 不动。服务 Cookie 为 ta_preview_<port>，默认8768。端口不是 Cookie 隔离依据。

## 输入和状态

继承天数、驾驶偏好，日期、起终点和包车倾向由页面补充。时间解释为 Asia/Shanghai，存 ISO8601 +08:00；单个路段的公交出发时间需另行明确，不能拿旅行起点时间填给所有路段。未知日期仍允许一般参考。包车 COMPARE 只是比较意愿；不自驾且未选择 COMPARE 时不派发驾车查询。

只有一个明确箭头路线片段时程序拆分建议名称，保留 Evidence ID；多个日段不自动拼接。用户可编辑或补充相邻地点，标 USER_INPUT，原 Evidence 不改写。地点查询每页最多3项、只取第1页。任何候选都需用户选择，区域中心要求 REGIONAL_REFERENCE，明确入口/站点/停车场等要求对象类别相符；接驳和真实可达性保持未知。

GET /api/v1/preview/routes/{session_id} 只读。POST /api/v1/preview/routes 的 save/cancel/adopt/confirm_place 为本地动作；resolve/route 必须有发送确认、符合范围并先原子预占额度。精确私址另有确认。保存修改生成 draft，adopt 才替换 adopted；原兴趣不变。条件变化使旧路程 STALE；保留旧查询端点、模式、数值和时间作为旧参考，不计入新情景。未改名的地点确认在同进程内保留，避免重查。修改名称或区域后相应地图对象失效。异步结果核对输入 revision、Preview revision 和内存 generation。

## 官方映射（2026-09-26核对）

| 能力 | 固定 HTTPS 路径 | 本轮参数/响应 |
| --- | --- | --- |
| 地点 | /v5/place/text | keywords；可选region、city_limit=true；page_size=3/page_num=1；基础pois字段，不请求business/photos |
| 驾车 | /v5/direction/driving | origin/destination；strategy=0；show_fields=cost；route.paths[0] |
| 公交 | /v5/direction/transit/integrated | city1/city2取POI城市编码，不用adcode；AlternativeRoute=1；可选明确date/time；route.transits[0] |
| 步行 | /v5/direction/walking | alternative_route=1；show_fields=cost；route.paths[0] |

三种路线分别使用方案 distance（米）、cost.duration（秒），缺失/空数组/非数/负数保留未知。公交总耗时包含等车，不叠加步行/换乘分项。HTTP状态、业务status/infocode、count与方案集合分开检查。权限/额度、网络/格式错误、无方案、部分数值分别显示。只有公交传支持的日期时刻；未来适用性仍未核实。驾车不等于公共交通或包车可订，步行不等于徒步安全。

来源：[搜索POI 2.0](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch)、[路径规划2.0](https://lbs.amap.com/api/webservice/guide/api/newroute)、[Web服务Key](https://lbs.amap.com/api/webservice/create-project-and-key)。本轮没有账户权限或成功请求证明。

手动链接为 [官方单点URI](https://lbs.amap.com/api/uri-api/guide/mobile-web/point)：marker、position经度在前、coordinate=gaode、callnative=0，无Key、无预加载。没有地图SDK/第二种Key/底图/折线。

## 存储、安全和预算

SQLite v14 扩展原 continuation_operations 的 MAP_PLACE/MAP_ROUTE 类型（原行原样复制），新增 route_preview_inputs 存用户输入、采用版本及原 Evidence 引用。BoundedBudget.reserve_count 复用同一事务计数，地点≤8、路径≤8、合计≤16，失败不退回，旧许可不动。固定批次不能传新ID；复制到其他目录不能使用旧许可。服务独占工作区进程锁。

相同进程中同参数仅派发一次，幂等回执跨进程持久化。不同标签、不同幂等键也不能重复派发。重启不自动请求；新的**显式**重新核实可在原剩余额度内消耗新次数，不恢复次数。预算预占是保守尝试数：占位后崩溃可能高于真实HTTP派发，不冒充网络测量。

Key仅从进程环境 AMAP_WEB_SERVICE_KEY 读取；不加载.env、不传前端、不打印异常/URL/查询地址。固定主机/路径、TLS默认验证、禁止重定向和环境代理，无重试。CLI审计仅允许固定Amap transport窗口出网；其他外连与XHS研究导入拒绝；指标只记录类别与计数。开发读官方文档/Git不属于应用调用数。

依 [高德服务协议](https://lbs.amap.com/pages/terms/)，当前未建立持久化返回数据的适用许可，本轮 EPHEMERAL_MEMORY_ONLY。POI、坐标、URI、距离、耗时、查询结果/失败内容均不进SQLite、日志、报告、checkpoint或浏览器持久存储。只存输入、操作摘要/计数。重启恢复原资料及输入，地图显示 EXPIRED_OR_NOT_QUERIED，需主动重新核实；不声称恢复地图内容。

## 时间语义

只计算已知移动估算与用户填写的假设。每日活动窗口与真实出发/返回区间取交集，支持跨夜；窗口之外作为用户留给夜间休息的时间。窗口内休息、停留、缓冲、接口未含末端接驳为空则未知，不能取0。五天/Day4/来源日数与经过小时分离。

独立输出 COMPLETE/PARTIAL、UNKNOWN/FITS_UNDER_STATED_ASSUMPTIONS/EXCEEDS_UNDER_STATED_ASSUMPTIONS、executable=UNVERIFIED，附 assumptions/unknown_legs/missing_inputs/checked_scope。一个来源日段保持局部；部分和不是可靠全程下界。估算超过窗口只说明当前情景超出，不证明所有现实路线不可行。本轮不验证运营、预订、开放或五天完整路线。
