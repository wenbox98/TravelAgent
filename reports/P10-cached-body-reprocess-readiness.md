# 缓存正文重新分析：离线接线与部署准备验收

日期：2026-10-10。基线：`1edb9f28c84c226ab18ee04ea28350ee44976f82`；功能分支：`feature/g1-live-llm-validation`。

本阶段结论：**离线实现与真实缓存只读准备 PASS；真实重新分析 NOT_MEASURED，内容交付仍 NOT_READY，G1不变。** 没有新建真实许可，没有模型、小红书、高德、embedding或报价业务请求。没有用旧余额，也没有改写历史失败、正文、审核、草稿或采用版。此阶段交付后等待独立复核，不自动继续真实验收。

## 问题、修复与契约

旧普通入口的 CACHE/DECOMPOSE 只整理已采信引用，不能将已有正文按当前新缺口重新提取审核；旧 Recovery 也会拒绝跨批次的正文分析。直接开放新批次会绕过旧失败和预算边界，因此本次只接入一个明确请求、快照与任务绑定的缓存分析步骤，继续既有 worker/Recovery/独立审核。

| 生产函数或规则 | 通用行为 |
|---|---|
| `agent_contract.cached_body_reprocess_requested` | 识别明确“用/使用已缓存正文重新分析/提取”；否定、问题、假设与引述不作为该操作请求 |
| `automatic.AutomaticService._create` | 准备有效快照后登记本次新有限许可；连接/搜索/详情/地图均0，模型至多8或明确的更低上限，至少5才开始；不改旧许可 |
| 新 `cached_reprocess.prepare/validate/validate_attempt` | 当前旅行的可证明来源关系、当前缺口、最多两份FULL/PARTIAL快照、哈希、规范化与策略版本绑定；清理/撤回/过期/权限失效即停止 |
| `cached_reprocess.external_allowed` | 原快照策略与最新策略均须允许外部模型；本地缓存可读不能代替外部推理权限 |
| `cached_reprocess.permits_new_batch`、`ExtractionRecovery.execute` | 仅有效任务与快照绑定可进入新分析；相同快照+提示版本+缺口已经实际尝试则拒绝重复，不改旧尝试；新版本或变化的当前缺口仍需明确请求 |
| `agent.run`、`JobService.create`、`worker.run_job/extract_worker` | 普通对话/API进入同一耐久作业和账本；子命令完整保留缺口；缓存分析不构造站点reader、不启动小红书浏览器 |
| `context_review.reserve_review/run_review` | 继续独立上下文、定位、引用、条件、依赖检查；审核预留、子进程入口、HTTP开启与晚到提交均检查缓存任务和外部权限 |
| `cached_reprocess.analyze` | 后份失败时保留前份独立合格结果，停止且不重试；分别统计真正新增、此次审核采信、当前可用与此前已有Evidence |
| `agent_contract.understanding`、`intake_values.relaxed_pace_evidence` | “不要求精确时刻/不必排满每天”不能推出RELAXED；需要明确节奏原话，未知保留；不回写真实历史误判 |
| `planning.network.install` | Windows复用PID时，先将旧计数文件以唯一名称保留，再建立当前worker固定诊断路径；不覆盖历史网络计数 |
| `AgentProgress.vue`、`AutomaticPlanning.vue`、`planning-api.ts` | 普通页面说明缓存分析用途、接收方和有界范围；区分本地复核与新模型分析，显示停止原因及新旧资料计数 |

提取输入版本为 `reference-selection-v1.2`。既有片段目录、ID/哈希与原文定位规则不改；有效片段ID不等于语义通过。继续原过滤与每来源每次最多6000字，不发送凭据、私址或真实地图返回。generation、父子任务、revision、截止与有效许可继续原有防护；取消、过期、撤销后晚到结果不得提交。未增加schema迁移，数据库仍18；HTTP提交沿用原认证、Origin、CSRF与幂等契约。

## 实际复现与回归

先单独复跑 `test_policy_revoked_after_permission_stops_before_extraction`，**1 FAIL**：撤销外部模型权限后没有真实HTTP提取，但仍错误创建提取尝试，停止原因是 `CACHE_BODY_EXTRACTION_NOT_COMPLETED`。这不是状态断言问题。修复后同项 **1 PASS**：仅已允许的理解请求替身发生，正文提取/审核均0、无新提取尝试，明确停止为 `CACHE_BODY_SNAPSHOT_OR_POLICY_DENIED`。

最终相关回归命令：

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest tests\integration\test_cached_body_reprocess.py tests\integration\test_model_context_review.py tests\integration\test_extraction_worker_focus.py tests\integration\test_reference_deduplication.py -q --basetemp=..\cache-body-readiness-resume-regression-host
```

结果 **91 PASS**（71.66秒，2条既有依赖弃用警告）。随后补充的 `test_accepted_duplicates_are_not_reported_as_new_evidence` **1 PASS**：相同合格条目再次采信时，新Evidence仍0，当前可用与此前已有数量一致。最后把有效性检查与每条独立证据提交放进同一事务，两个受影响文件 `test_cached_body_reprocess.py` / `test_model_context_review.py` 再次运行 **60 PASS**（69.11秒）。各次包含重叠用例，不相加冒充独立测试数量。没有再跑全量1685项；原基线 `MAP_SCOPE_UNVERIFIED` 问题不在本阶段修复，也不宣称全量通过。

本阶段新文件最终32个案例，覆盖：普通对话与真实API路由、实际提取子命令/生产序列化、独立审核、重复请求与重复分析阻止、正文缺失/清理/权限/哈希异常、规范化及完整性的数据库约束、取消与晚到回复、审核前/子进程入口/回复后撤销权限、部分保留、新旧统计，以及输出弹性与真实轻松偏好的区分。测试均用自编来源、替身HTTP与临时数据库，不手写真实攻略或审批。

合成生产链：一次理解、两次提取、两次审核、一次结果决策，**6次替身模型调用**；真正新增2条合成Evidence，旧尝试、旧审核、旧claims和旧账本逐行不变。另一案例第二份失败，第一份合格结果保留，不进行第三次提取或自动重试。替身调用次数不能写成真实DeepSeek成功。

前序10组前端检查已通过；最后只重跑修改相关的 `node tests\automatic-planning.mjs`，通过缓存提示、旧状态及新增/已有计数断言。`npm.cmd run build -- --outDir ../../.local/cache-body-readiness/web-delivery` 的类型检查与构建通过。修改Python文件的Ruff与 `git diff --check` 通过。

最后一次真实本机重启触发了Windows PID复用：旧 `metrics-19404.json` 被原安装器写为新serve的零计数，独立恢复脚本正确报错，出现model/DNS/socket各-1的无效增量，未将其当作通过。正常关闭该实例后，从本阶段之前保存的只读基线恢复旧计数值，新零文件另存私人诊断；数据库和旧额度全程不变。生产安装器现将同名旧文件唯一归档再写新计数。增加旧文件逐字保留回归，并运行启动检查及6种角色网络隔离，**13 PASS**。最终恢复同时要求每份旧计数仍原样存在或完整归档，且全部文件累计增量为0，不能靠忽略负数过关。

## 真实缓存与输入准备

在独立进程中关闭socket、DNS，并以 `PRAGMA query_only=ON` 加载当前B旅行，调用真正的coverage、prepare、canonical/catalog/payload/outbound_blocks；没有调用provider，没有创建许可或任务。当前住宿缺口为LODGING，选中两份PARTIAL_TEXT：过滤后分别619字/24片段、783字/36片段，均规范化版本1、原文关系与哈希有效，低于6000字，未发现敏感访问材料。没有打印正文、来源标识或账户材料。

这证明当前缓存可进入生产分析准备；**不证明两篇包含足够住宿知识，更不证明真实模型将接纳有用结果**。完整生产wire契约只由合成测试验证；真实模型提取、真实审核、住宿片区改善及新攻略均NOT_MEASURED。没有把历史“已审核/已采信总数”当作本次新增。

## 同一8768部署与恢复

确认原PID10996监听127.0.0.1:8768，命令属于本仓库product_preview服务；通过持有终端正常关闭。原静态目录保留于私人回滚目录，再部署独立构建。最后一次局部复核后再次正常重启，当前服务PID24648、静态资源 `index-DiYZuIaf.js` / `index-Cj59D7xp.css`；构建和最终生产代码均在本次检查完成后启动，未替换原数据库、认证配置或浏览器profile。

普通Edge页面刷新后连接成功，看到缓存正文分析新提示及发送用途说明；当前B的3天9项目、采用v2仍在，原失败仍显示为旧结果，未提交新分析。页面继续保留历史节奏值，未通过数据库反改来掩盖旧误判。

独立禁网进程恢复：A为5天5项目、采用v1；B为3天9项目、采用v2；均非空，草稿/采用/版本与基线完全一致。当前代码重建的Markdown导出也非空（A7000字节、B15734字节）；这不是替换原已下载文件。两份原下载及三份T03报告哈希完全不变。

表级比对：**61张表、8595条原记录，changed_tables=[]，old_row_changes=[]**。其中原89条claims、40份来源/正文、39次提取、33次上下文审核、242条操作账本和25个planning_tasks均保持。没有新的真实任务或许可，活跃任务0。前端首页/health返回200，HTTP静态入口与部署文件逐字相同。

| 测量项 | 本阶段真实增量/结论 |
|---|---|
| 模型HTTP、高德HTTP、外部DNS/socket、blocked_external | 全部0；由原账本和本机审计文件增量核对 |
| 小红书连接/搜索/详情 | 0/0/0；无研究任务，账本未变 |
| 小红书浏览器 | 启动本地构造自检计数0；未创建真实研究reader或导航 |
| embedding/报价 | 0；没有对应调用路径或新增操作 |
| 真实缓存模型结果/住宿改善 | NOT_MEASURED；未派发，不把只读检查算内容成功 |

可复制日常入口（已运行时仅重新打开，不停止原服务）：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

地址：<http://127.0.0.1:8768/>。本阶段留页面供独立复核，不自动创建真实分析任务。

## 仍未解决与下一阶段建议

当前真实玩法、停留、季节和住宿资料缺口仍保留，既有交通参考不能替代现实核实。此次不重做多日、地图、酒店、报价或资料清理，也不改旧门禁。历史pace误判保留为已知历史问题，新输入边界已修复。

独立复核通过后，可另行明确批准一次缓存正文分析：同一当前旅行、当前住宿缺口、至多这两份有效快照；最多8次模型，模型接收方仍为原DeepSeek；站点/地图等全部0，不挪旧余额。典型成本为理解1+提取2+审核2+决策1+规划1=7；没有合格活动则不强求规划。此处只是建议，**不是已经批准或已经执行的真实操作**。任何失败、取消、验证或预算不足都按既有边界停止，不能通过重复许可重试相同配方。

## Git与安全

按明确21文件清单提交，不包括真实SQLite、正文、profile、配置、审计、截图或私人恢复证据；保留三份未跟踪T03报告。推送仅原功能分支，不合并master、不发布、不强推。扫描工作文件及完整未推送提交范围，检查配置凭据、认证材料、真实来源标识与二进制，核对完整远端SHA；最终SHA与链接见交付消息。

本次diff覆盖12个生产Python文件、4个前端/类型/测试文件、2个合成集成测试文件及3份文档。主要新增是当前旅行缓存分析的通用绑定与派发，其余为接线、防护、计数和提示；没有目的地、景点、来源ID或旅行ID特判。

收尾暂存检查实际 `git diff --cached --stat` 摘要：`21 files changed, 920 insertions(+), 33 deletions(-)`（本条记录补入之前的快照）。
