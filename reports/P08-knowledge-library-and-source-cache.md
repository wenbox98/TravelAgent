# P08 我的旅行资料库与原文独立清理

## 结论与边界

核心闭环 PASS：正常页面整理既有资料、本机关键词检索、新旅行显式复用、唯一一次真实模型规划、预览/取消/采用及重启恢复完成。隔离副本真实清原文后，独立进程仍能检索、加入旅行、构建规划输入和采用；禁止网络、原文读取及其他库/源文目录兜底。

基线 `5197f9574baa5897e664587451d83febd58e4789`，分支 `feature/g1-live-llm-validation`。不合并 master。G1 保留历史 NOT PASS。本批不是对地点开放、公共交通或完整旅行质量的验证。

## 主库保护与迁移

SQLite 15→16；迁移前保存一致性备份和静态构建备份，未覆盖其他阶段数据库或页面。主库原记录逐行比较：6来源、35 Evidence、6原文、135正文块、89候选、10提取尝试、5模型审核、3本地复核、12旧旅行、12旧任务、49旧调用账本、9旧许可全部原样保留。新增1独立验证旅行、1任务、1普通许可、1模型账本行。

主库原文真实删除数 **0**。本批没有操作真实登录profile，没有 connect/disconnect。隔离副本的profile标记在清原文与删知识后保留；这不是整机文件写入监控。

## 实际卡片与检索

由正常页面选择原采用旅行并预览整理，主库共3张卡：SOURCE_REFERENCE 1、PLACE_LEAD 1、PLAN_PATTERN 1。三者不是3条独立事实；地点提及和采用节奏不能晋升Evidence，原35条未增加。主库涉及2个来源标识；真实名称关键词检索命中2张同源卡、计1个来源。卡片保持测试属性、原角色、条件、完整度、来源与定位链；真实例子只留私人页面，不写入Git报告。

实际检索为 LOCAL_KEYWORD_RETRIEVAL / FTS5_BIGRAM，编码后的二字词与BM25；未用embedding。运行库本地能力检查，不能使用FTS时有明确 LIMITED_TERM_INDEX_FALLBACK。先过滤权限、账号、精确地区、测试属性、类型和日期，再做有界排名，250候选/60返回上限不冒充大规模性能验证。

合成检索质量：两字区域“青谷”与长词、分隔关键词能命中；异地“苏州”在无当地卡时为零；注入式查询按文字处理为零。多地区同名案例严格地区隔离；春节公交与国庆自驾条件分别保留，同源去重计1，不把冲突平均消失。测试资料默认排除、显式包含后显示。索引可重建，卡片条件变更创建新版本，旧绑定拒绝。

## 原文真实清理与独立恢复

只在忽略目录下的隔离私人副本执行。副本A重新核对并幂等整理后，通过生产清理预览和执行：清1份原文，清除其BodyBlock及7处上下文副本。内容身份保留为 USER_CLEARED，卡片显示 HISTORICAL_ATTESTATION。35条Evidence、旧审核身份、旧采用版和账本保留。

检查指定副本全部逻辑应用表，未发现该份等价完整正文；合成原文专用sentinel清理后不在正文、块、历史输入、卡片或索引中。有限已审核条目和必要条件仍是有意保留的派生内容，不能称为所有相关文字都已消失。

独立进程B：网络连接/DNS禁用；SourceContent.load禁用；其他SQLite、主库、备份及.local源文路径禁止读取。恢复非空知识→新旅行→正常最小规划payload→本地采用全部成功，原文/网络/兜底尝试计数均0。撤销来源后模型输入拒绝，用户已采用版及隔离profile标记保留；其他独立来源不受影响。

历史备份、其他数据库、WAL/磁盘物理残留没有被擦除，也没有作为知识兜底；检查范围不是SSD安全抹除或全盘扫描。主库与副本检查范围分别记录。

## 实际唯一模型请求

通过普通页面建立新旅行，显式选择1张已检索地点卡、1个已有来源；普通许可 MODEL=1，其余连接/搜索/详情/地图额度全部0。输入包含必要公共名称、该卡有限条件及当前旅行约束；引用正文与条件共32字符（不是整个HTTP请求大小）。每来源≤6000；没有完整正文、BodyBlock目录、旧模型完整输入、私址、凭据或地图返回。实际payload构建使用SQL授权器禁止原文/块/候选/旧输入读取，与无原文副本相同生产路径。

接收方原配置 `api.deepseek.com`；120秒等待、180秒外层时限沿用。只1次请求，无连接探测、重试、提取、审稿或重排。

真实结果：2个提议，2个接纳，0个拒绝。方案1：原有单一公共活动10:00开始，AI建议停留45–90分钟，结束参考10:45–11:30，休息15分钟。方案2建议停留20–45分钟。交通保留公共交通与步行，往返自行安排；没有新增交通耗时。活动身份/范围、开放、预约和实际可行性仍未知。

页面实际完成方案1预览→取消恢复原草稿（停留未知）→重新预览已存方案→采用；没有额外模型请求。正常停止并重启主服务后，非空采用版、首项10:00、停留45–90及休息15分钟恢复。许可已关闭。

## 本批发现并修复的问题

首次规划没有旧采用版时，旧取消入口不可用。新增原草稿预览备份与显式取消；重新使用已存方案必须是程序记录的取消修订，且最小输入仍完全一致。没有放宽引用、交通、范围或事实检查。

卡片删除向依赖卡片传播并清理活跃索引；多源依赖无法重建时整体失效。来源知识还检查旧claim删除/变化。原文意外修改/缺失不冒充正常清理；清理修改按当前账号隔离；显式清理后的内容身份不被旧原文到期清理入口删除。删除或版本变化在调用前、返回后、发布事务内和采用时生效。

保留偏好支持长期保留、整理后可清理、会话后可清理；后两者仅记录偏好，页面明确仍需清理预览和确认，未启用自动删除存量资料。

## 调用和计量

|项目|实际本批增量|依据|
|---|---:|---|
|项目模型HTTP|1|请求钩子与普通账本均为1|
|高德HTTP/地点/路径|0/0/0|项目计量与账本|
|XHS connect/search/detail/browser|0/0/0/0|无对应派发、许可全0，项目外联仅模型|
|embedding/模型下载|0|无实现/无派发|
|项目外部DNS/socket|1/1|运行时计量，非整机总量|
|阻止的项目外联|0|运行时计量|
|副本B网络/原文/其他库尝试|0/0/0|进程内硬禁止及计数|

刷新、检索、折叠、编辑、预览、取消、采用和重启未增加上述项目外部计数。整机网络包/其他软件流量 **NOT_MEASURED**。Git推送和开发参考文档访问不属于项目业务请求计数。

## 代码、契约与验证

新增knowledge模块：organize.prepare/commit、Library.get/search/remove/rebuild/retention、cleanup.preview/clear、planning.attach/payload和同源API。数据库16迁移、KnowledgeBinding、LibraryAction/Response及规划取消状态同步导出JSON Schema/OpenAPI。旧raw audit_grounding语义保持。

实际运行：Python完整回归、Ruff、项目配置Mypy、7组前端SSR组件测试、vue-tsc、Vite构建及契约校验。最终为 **1137 passed，106.49秒**（含25项知识专项）；Ruff通过，Mypy 81个配置内源文件通过；7组前端组件测试、类型检查、Vite 45模块构建通过；契约108定义/186引用/39操作通过。Python依赖弃用提示2项、部分原前端SSR测试cssVars提示仍在，不影响通过。

安全扫描只暂存明确的代码、契约、合成测试和文档；不提交真实卡片库、正文、源ID、认证材料、私人截图或诊断。原3份未跟踪T03报告保留。提交与远端SHA在最终回复给出。

## 启动与使用

仓库根目录：

```powershell
cd E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

主入口 http://127.0.0.1:8768/，本轮保持运行。同一入口“我的旅行资料”→整理已有资料并确认→关键词查询→新建独立旅行→选卡加入草稿→明确普通许可后主动AI建议→预览/取消/采用。清理原文与删除知识为不同操作。

向量能力 NOT_IMPLEMENTED；本批交付关键词检索辅助规划。后续工作未开始。

## Git diff 摘要（提交前）

```text
 apps/api/travel_agent/knowledge/__init__.py       |   1 +
 apps/api/travel_agent/knowledge/api.py            | 105 ++++
 apps/api/travel_agent/knowledge/cleanup.py        | 145 ++++++
 apps/api/travel_agent/knowledge/organize.py       | 269 +++++++++++
 apps/api/travel_agent/knowledge/planning.py       | 151 ++++++
 apps/api/travel_agent/knowledge/store.py          | 358 ++++++++++++++
 apps/api/travel_agent/persistence/database.py     |   3 +-
 apps/api/travel_agent/planning/arrangements.py    |   6 +-
 apps/api/travel_agent/planning/flow.py            |  49 +-
 apps/api/travel_agent/planning/flow_maps.py       |   2 +-
 apps/api/travel_agent/planning/flow_models.py     |   9 +
 apps/api/travel_agent/planning/private_payload.py |  16 +-
 apps/api/travel_agent/planning/suggestions.py     |  36 +-
 apps/api/travel_agent/planning/workbench.py       |  18 +-
 apps/api/travel_agent/preview/api.py              |   2 +
 apps/api/travel_agent/preview/worker.py           |   9 +
 apps/api/travel_agent/research/content_store.py   |   4 +
 apps/web/package.json                             |   2 +-
 apps/web/src/components/KnowledgeLibrary.vue      |  42 ++
 apps/web/src/components/PlanningPanel.vue         |   6 +-
 apps/web/src/planning-api.ts                      |   2 +-
 apps/web/tests/knowledge-library.mjs              |  16 +
 contracts/domain.schema.json                      | 164 +++++++
 contracts/migrations/016_knowledge.sql            |  40 ++
 contracts/openapi.yaml                            |  36 ++
 docs/05-data-rag.md                               |  22 +-
 docs/architecture/knowledge-library.md            |  44 ++
 reports/P08-knowledge-library-and-source-cache.md |  84 ++++
 reports/document-validation.json                  |  14 +-
 reports/document-validation.md                    |  10 +-
 tests/integration/test_knowledge_library.py       | 552 ++++++++++++++++++++++
 tools/export_preview_contract.py                  |   9 +-
 32 files changed, 2188 insertions(+), 38 deletions(-)
```
