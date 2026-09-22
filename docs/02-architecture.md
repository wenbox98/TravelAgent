# 02｜总体架构与代码地图

## ADR-01：首版本地化，减少部署依赖
相较早期讨论的 Celery＋Redis＋PostgreSQL，首版改为 **FastAPI＋单个本地 worker＋SQLite＋本地向量计算**。这是为开源自用、Windows 启动简单而作的范围优化，不是宣称 SQLite 适合任意规模。保留 JobRepository、KnowledgeRepository、VectorIndex 等接口，未来再替换后端。

前端 Vue 3＋TypeScript；Agent 流程用 LangGraph；业务规则为独立 Python 函数。SQLite 存结构化数据与任务，FTS5 存预分词文本，向量以受控 BLOB 保存并在小型个人库中精确计算相似度。初始容量设计目标 10,000 chunks，性能须基准测试，超过上限提示清理/升级，不能承诺无限容量。FTS5 是官方支持的全文索引能力，但中文分词需本项目处理。[S10]

## 进程与信任边界
```text
用户浏览器中的本地网页
        │ 同源 HTTP + SSE，只访问本应用
        ▼
TravelAgent Launcher（Windows 首版）
        ├─ API/UI 服务：127.0.0.1:8765
        ├─ 单个任务 worker：SQLite job queue + LangGraph
        └─ 只读 XHS sidecar：loopback 动态端口 + 随机 Bearer token
                                  └─ 专用浏览器会话 / 官方登录页面

API/worker ── Domain Services ── SQLite（计划、任务、允许存的资料）
                   ├─ ModelAdapter（用户选定服务/本地模型）
                   ├─ SearchAdapter（官方资料发现）
                   ├─ AmapAdapter（运行时地图/路线）
                   └─ QuoteAdapter（真实供应商或明确 UNSUPPORTED）
```

sidecar 只允许 launcher/API 调用；模型不可见它的 URL、token 或原始工具集。不要让浏览器前端直接访问上游 MCP。公开入口不提供“调用任意工具/任意 URL”。

## 目标目录（源文件待 Codex 创建）
```text
apps/api/travel_agent/
  main.py                         # FastAPI 入口与生命周期
  settings.py                     # 配置、路径、能力开关
  api/{auth,trips,jobs,knowledge,settings,events}.py
  domain/{models,errors,permissions}.py
  services/{auth_service,trip_service,revision_service}.py
  research/{query_planner,ranker,scheduler,coverage,extractor}.py
  providers/xhs/{protocol,adapter,session_broker,error_mapper}.py
  providers/{amap,quotes,official_search,model,embeddings}.py
  knowledge/{ingest,retriever,vector_index,retention}.py
  planning/{graph,nodes,feasibility,budget,diff}.py
  persistence/{database,repositories,migrations}.py
  worker/{runner,leases,operation_ledger}.py
  security/{redaction,origin,secret_store,url_policy}.py
apps/web/src/
  views/{Setup,TripWorkspace,Knowledge,Settings}.vue
  components/{XhsConnect,RouteOptions,ResearchProgress,PlanDiff,BudgetPanel}.vue
  api/{client,generated-types}.ts
  stores/{trip,session,jobs}.ts
apps/launcher/{main.py,supervisor.py,doctor.py}
integrations/xhs-sidecar/{README.md,patches/,build.ps1,build.sh}
tests/{unit,contract,integration,e2e,live,security}/
```

本包已带的 `contracts/`、`fixtures/`、`docs/` 不属于待实现代码。新建运行脚本放 `scripts/`，开发产物不写回文档生成工具。

## 单 worker 的调度
一个用户实例只有一个 worker 所有者。API 入队，worker 用 `BEGIN IMMEDIATE` 事务领取任务，设置 lease 和 generation；短事务提交后才做网络操作，严禁占着数据库事务等待浏览器/模型。worker 心跳续租；过期任务恢复前先检查操作账本。

所有 XHS 任务共享账号级互斥锁，包括搜索、详情、登录核实；登录期间暂停研究。模型/高德可独立执行，但初版不必增加并行复杂性。关闭网页不停止进程；退出 launcher 或关机则任务暂停，不能声称继续运行。

## 持久化状态边界
LangGraph 官方文档支持 checkpoint 和用户中断；恢复会重新执行中断节点的前部代码，所以有代价的工具调用与用户确认节点要分离。[S08][S09]

graph state 只放 trip_id、revision、job_id、证据 ID、允许保存的摘要、待问问题和公开业务状态。禁止放 Cookie、xsec_token、二维码、原始 HTTP 响应或禁止保存的原文。不可持久化内容通过短生命期 `evidence_handle` 在同进程访问，失效后回退到重新获取/缺口状态。

## 密钥与数据位置
Windows 默认 `%LOCALAPPDATA%\TravelAgent\`，开发模式 `.local/`。配置与数据库不放安装目录。凭证通过 Windows Credential Manager/DPAPI 等 OS 安全存储适配；无安全存储时不落明文密码，降为本次运行有效并提示。浏览器专用 profile 受当前 OS 用户权限保护；不要承诺可以抵御同用户恶意软件。

## 关键替代边界
浏览器插件可作为后续研究项，不能首版同时维护两套会话栈。上游 README 指向插件项目只说明有备选入口，不证明它已满足本工具搜索、只读和本地数据要求。[S01] 供应商报价也是可插拔能力，不应因为拿不到一个接口而伪造出完整报价。
