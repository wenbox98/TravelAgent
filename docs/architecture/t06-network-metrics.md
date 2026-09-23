# T06 网络观测口径

本页定义内部 `LiveNetworkSnapshot`，不改变 sidecar HTTP 契约。默认策略仍为 `OBSERVE_ONLY`。本轮没有真实 LLM 配置，按用户要求标记 `G1_LIVE_LLM_BLOCKED`；仅运行合成离线事件测试，没有追加实站访问。

## 请求事件、本地决策与完成

scope 始终是 `context_events_since_attach`，不代表所有浏览器或操作系统流量。以下每项均提供总数与 `document / xhr_fetch / image / media / font / script / stylesheet / other` 八类数量；未 attach 的未测结果为 null，不是 0。

| 字段 | 实际观测口径 | 不能据此声称 |
|---|---|---|
| `attempted_requests` / `attempted_by_category` | BrowserContext 的唯一 Request 对象 `request` 事件；兼容旧 `total_requests` / `requests` | 实际发到服务器的请求数 |
| `blocked_requests` / `blocked_by_category` | 本应用 `route.abort()` 成功返回；仍属于 attempted | 所有浏览器阻断、HTTP 拒绝或节省字节数 |
| `allowed_requests` / `allowed_by_category` | 无本应用 handler 时的未拦截事件，加成功返回的 `route.continue_()` | 到达站点或完成传输 |
| `unblocked_request_events` / `unblocked_by_category` | 观察 request 时没有本应用 route handler | 没有其他 handler、缓存或 Service Worker 干预 |
| `continued_requests` / `continued_by_category` | 本应用 handler 成功继续原请求；不是新建请求 | 继续后一定到站 |
| `completed_requests` / `completed_by_category` | `requestfinished`；已进入 route 决策的请求等待成功 continue 结果 | 必定有实际出网或响应为 2xx；缓存也可能完成 |
| `failed_requests` / `failed_by_category` | `requestfailed`，包括客户端 abort；HTTP 4xx/5xx 单列 response status | 服务器拒绝率或用户可见失败率 |
| `unresolved_policy_requests` / `unresolved_policy_by_category` | handler 启用时观测到请求，但未关联成功 abort/continue 决策 | 可由 attempted − blocked 推算成 allowed |
| `actual_sent_requests` / `actual_sent_by_category` | 全部 null，`actual_sent_measurement=NOT_MEASURED` | 已测量 wire sent |
| `transferred_bytes`（旧 `total_bytes` 同样如此） | null，`transferred_bytes_measurement=NOT_MEASURED` | 估计或精确传输字节 |

`allowed_semantics=APPLICATION_UNBLOCKED_EVENT_OR_SUCCESSFUL_ROUTE_CONTINUE` 明确它只是应用本地放行口径。OBSERVE_ONLY 不为计数安装 route。TEXT_FIRST 仅 SEARCH/DETAIL 阶段阻止 image/media/font；退出恢复。启用 route 对 HTTP cache 的影响保留在 `routing_cache_affected`，不能拿受影响的 fallback 窗口冒充未修改的基线。

request 先于 route 决策时，TEXT_FIRST 不立即把 attempted 加到 allowed。晚到决策、响应和完成归原请求发起窗口，窗口外事件归 `OUTSIDE_WINDOW`。同一个 Request 的重复回调不重复计数；合成冲突事件由 `outcome_conflicts` 暴露，blocked 不计入 allowed/completed。关联容量有限，`association_losses`、`callback_errors` 和 unresolved 非零时不能把未见结果解释为成功或零流量。

## 重复资源与隐私

`repeated_resource_events` / `repeated_by_category` 是 **DERIVED** 候选：比较 method、资源类型、scheme、hostname、port、path 的临时 HMAC；先排除 URL query、fragment 和 userinfo。不同 query 的合法 API 调用可能合并，因此相同键不等于重试、同一内容或同一账号。

随机 HMAC key 仅在当前 observer 内存中使用；至多 2048 个摘要、默认 60 秒的滑动识别窗口、最大可配置 300 秒。旧项在后续事件到来时剔除，到期项不再用于匹配；detach 清空全部摘要和 key。`repeat_tracking_evictions` 记录容量或过期剔除，未匹配不能证明没有重复。原始 URL/path/query、摘要、headers、body、Cookie/token 均不进入报告或日志；不保存 Request 强引用。未读取请求/响应 body 或 headers。

`duplicate_request_events` 仅表示同一 Request 对象的重复回调，不是新资源尝试。`resource_retry_assessment`、`lazy_load_assessment`、`service_worker_assessment` 始终 `UNKNOWN`；本实现不额外访问站点以寻找原因，不改 Service Worker、UA 或浏览器指纹设置。

## 当前能下的结论

- **CONFIRMED（离线）**：被 abort 的请求仍可产生 request 事件；成功 continue 只是放行；一个请求可先结束再返回 route 调用结果；重复资源候选可以由不同 Request 产生。测试验证计数能区分这些情况，不证明真实站点发生了哪一种原因。
- **LIKELY**：本轮未把任何站点原因升级为 LIKELY；没有能支持该等级的新实站证据。
- **UNKNOWN**：真实资源 retry、lazy-load fallback、额外 xhr/fetch 的因果、Service Worker 影响、实际 wire 数量与传输字节。

历史 OBSERVE_ONLY 的 SEARCH 173 / DETAIL 181 与 TEXT_FIRST 的 236 / 276 / 285 是 context 请求事件参考，页面/来源、时间窗口、缓存状态并非严格配对；224 次 blocked image 本身也会进入 attempted。**当前只能得出 TEXT_FIRST 尚未证明减少实际网络成本，不能说实际网络访问增加。** 历史日志缺少新指标，不能反推历史 allowed/completed/wire/bytes。

后续若另获授权，应在受控预算内比较同来源、相同观察边界的 attempted、本地 allowed、完成的 image 事件，同时披露 route/cache 干扰及未知项。字节和 wire 仍不能可靠测时继续 NOT_MEASURED；一次非配对采样不构成成本收益证明。
