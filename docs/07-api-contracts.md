# 07｜API、事件、错误和数据契约

## T02/T03内部sidecar契约

[xhs-sidecar.openapi.json](../contracts/xhs-sidecar.openapi.json)是独立内部API v0.2.0，由严格Pydantic模型导出并与运行路由离线比对。它不是下面业务OpenAPI/FetchResult的替代物，不改Evidence或SQLite语义。默认offline保留T02合成读取；显式login模式仅实现普通浏览器登录，搜索、详情和旧POST browser/session返回409 LOGIN_ONLY。无完整upstream二进制兼容声明。

T03增加POST `/v1/login/connect|resume|cancel|disconnect`（四个固定路径），共12个method/path组合。GET `/v1/login/status`只返回本地缓存，不检查Cookie或触发任何浏览器操作。connect首次导航一次；已认证时再次显式connect只观察当前页。resume仅恢复验证暂停后的当前页观察；cancel关闭并保留profile；disconnect关闭后删除专用profile。未启用login的四个POST返回409 LOGIN_NOT_ENABLED。DELETE browser/session在login模式走cancel，失败返回500，不绕过generation撤销。

登录操作成功受理返回200及LoginState；调用者必须读取其中status，ERROR不是已退出或已登录，error_code区分BROWSER_ERROR、LOGIN_TIMEOUT、CLEANUP_FAILED、FLOW_STOP_TIMEOUT。profile存在仅标SESSION_PRESENT_UNVERIFIED。状态含generation、随机flow_id、历史remote_checked、account_identity的KNOWN/UNKNOWN；不含账号ID、Cookie、二维码或profile路径。身份原值只留本机私有内存，AccessLocator也不进入公共schema。NetworkSnapshot与LoginState独立标记login_status_external_requests=0；真实浏览器总流量仍NOT_MEASURED/null。

这些控制接口使用T02的loopback Host/Origin限制与专用Bearer凭证，不开放任意URL或浏览器命令。以下业务API认证/事件/幂等方案仍为后续契约，T03未实现GUI、二维码接口或研究恢复。

## 机器可读文件
- `contracts/domain.schema.json`：JSON Schema Draft 2020-12 领域输出。
- `contracts/openapi.yaml`：OpenAPI 3.1 接口草案。
- `contracts/database.sql`：SQLite 初始模式；后续由 T01 迁移落地。
- `contracts/upstream-lock.json`：上游候选版本与待验证项目。
- `config/defaults.json`：本应用设计默认值，非第三方平台额度。

这些是本应用的接口，不是声称小红书或供应商原生支持这些路径。上游具体映射只在适配层。

## 本地身份
发布版 UI/API 同源。launcher 首次打开带一次性 bootstrap ticket 的本地 URL；ticket 仅在 loopback 使用、短时效、单次交换为 HttpOnly SameSite=Strict 会话 cookie，随后跳转到无 token URL。ticket 不能进访问日志或 referrer。应用 cookie 在纯 loopback HTTP 下的 Secure 属性按实际协议配置，不能错误设置后导致不可登录；绝不把这一安排照搬到远端 HTTP。

变更接口验证 X-CSRF-Token 与精确 Origin；WebSocket/SSE 同样验证会话和来源。拒绝任意 Host（防 DNS rebinding），不使用 CORS=*。健康探测只返回非敏感存活信息，不能暴露安装路径和凭证状态。

## 主要 API
| 方法与路径 | 行为 |
|---|---|
| GET /api/v1/capabilities | 返回各数据源配置/验证状态，不泄露 key |
| POST /api/v1/auth/xhs/sessions | 幂等创建本地登录会话 |
| GET /api/v1/auth/xhs/sessions/{session_id} | 只读本地状态，不访问小红书 |
| GET /api/v1/auth/xhs/sessions/{session_id}/qrcode | 授权读取内存二维码，Cache-Control:no-store |
| POST /api/v1/auth/xhs/sessions/{session_id}/open-browser | 打开本应用拥有的官方登录窗口 |
| DELETE /api/v1/auth/xhs/session | 断开本地连接并取消关联任务 |
| POST /api/v1/trips | 创建旅行，初始信息允许缺失 |
| GET /api/v1/trips/{trip_id} | 当前版本与阶段 |
| GET /api/v1/trips/{trip_id}/overviews/{overview_id} | 读取已生成的粗略攻略 |
| POST /api/v1/trips/{trip_id}/messages | 提交消息并开始/推进研究任务 |
| POST /api/v1/trips/{trip_id}/proposals | 提交结构化修改，生成取舍预览 |
| GET /api/v1/trips/{trip_id}/proposals/{proposal_id} | 读取取舍预览 |
| POST /api/v1/trips/{trip_id}/proposals/{proposal_id}/confirm | 检查 expected_revision 后确认 |
| GET /api/v1/jobs/{job_id} | 状态、调用量、缺口 |
| POST /api/v1/jobs/{job_id}/cancel | 可重复取消，禁止后续新访问 |
| POST /api/v1/jobs/{job_id}/resume | 用户处理验证或授权追加预算后恢复 |
| GET /api/v1/jobs/{job_id}/events | SSE 进度事件，支持 Last-Event-ID |
| POST /api/v1/knowledge/search | 查询允许使用的个人资料 |
| DELETE /api/v1/knowledge/sources/{source_id} | 立即隐藏并安排派生清理 |
| POST /api/v1/settings/providers | 一次性保存用户选择的服务配置到 secret store |

provider 设置入口只允许列出的服务类型和经用户确认的 base URL，不能开放任意代理请求。模型服务自定义地址属于管理员设置，不可被文章/模型工具调用改变；私有网段请求策略分别控制。

## 异步结果的读取
Job.result_ref 初始为 null，结果就绪后返回 kind、resource_id、availability；SSE 的 safe_data 可携带同一引用。前端据 kind 调用 overview/proposal GET，不从事件文字猜 ID。结果引用只定位本地资源，不包含平台 token。

允许持久化的结果写入相应安全结果存储；不允许持久化的内容只留当前进程内存，并标 EPHEMERAL。进程退出后返回 410 RESULT_EXPIRED/availability=EXPIRED；不将“读取旧结果”变成未经用户同意的新研究请求。操作状态与安全引用可恢复，不意味着受限正文也可恢复。

本 OpenAPI 覆盖业务接口；launcher 启动握手和只返回存活的 health 属于本地控制面，由 T00/T09 实现并补入其独立契约测试。

## 幂等与并发
写接口要求 `Idempotency-Key`。同一路径、同一身份、同键同体返回原资源；同键不同体返回 409 IDEMPOTENCY_CONFLICT。保存 body hash，不保存包含 secret 的原请求。登录、resume、confirm 尤其不能因双击触发两次。

修改需要 expected_revision；resume 同时检查 job generation 和会话预算。任务属于当前本地实例；未来多人化前不能省略所有权字段。

## 错误 envelope
统一 `{error:{code,message,request_id,retryable,details}}`。details 为白名单结构，不含原始工具异常、Cookie、xsec_token、原文或本机绝对路径。

400/422 入参；401 本应用会话失效；403 能力/用途策略拒绝；404 不存在；409 版本/幂等冲突；429 本应用请求预算或调用限制；503 上游暂不可用。小红书需要登录是 job 的 WAITING_AUTH，不把应用 HTTP 401 和小红书会话混为一谈。

## SSE
事件：job.started、research.progress、auth.required、research.partial、overview.ready、proposal.ready、job.completed、job.failed、job.canceled。

事件 ID 为每 job 单调递增整数；payload 有 job_id、trip_id、revision、type、timestamp、safe_data。只传阶段、数量、安全证据引用和可显示的结果。断线恢复读既有 events，不重新发起抓取。事件保留由策略控制，不允许借 events 绕开数据保存禁令。

## Schema 约束
`additionalProperties:false` 用于外部模型输出，禁止多余字段混入。JSON 合法不等于语义正确：金额范围、资料权限、引用真实存在、路线活动 ID、时间窗口、version 等由业务校验补充。

知识来源缺失时 `evidence_refs=[]` 配合 `status=ASSUMPTION/UNKNOWN`，不构造假的 source_id。合成 fixtures 的 is_synthetic=true 永远不能在真实运行中消失。

## T01 的显式契约调整

- 内部 `FetchResult.status` 与 `OverviewResult.xhs_status` 统一使用 `NEED_LOGIN`、`VERIFICATION_REQUIRED`。03 章的 `AUTH_REQUIRED/CHALLENGE` 是候选上游错误概念，T02 adapter 必须映射；不作为应用 HTTP 401。
- Evidence 增加来源类型/标题/目的地/适用条件及可空置信度；字段映射见 PoC 设计。敏感 locator 不得出现在这些字段中。
- 增加严格 `ResearchSession` 定义；SQLite 通过 `contracts/migrations/002_poc.sql` 从 v1 升级。完整度旧值只按明确对应关系转换，未知值导致事务回滚。
- SourcePolicy 的 UNKNOWN 禁止原文、派生、向量和导出权限；仓储还检查审核时间、有效期、账号和策略版本。
- T00 控制面只实现 GET /health 和合成静态页。20 个业务 OpenAPI 接口仍是设计契约，未对外开放；其认证、CSRF、幂等与真实登录留待对应任务。
