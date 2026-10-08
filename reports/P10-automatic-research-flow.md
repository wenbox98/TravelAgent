# P10：一句需求到有限研究与建议预览

## 本轮结论

普通8768主入口已更新为「查资料并生成旅行建议」。服务端自动衔接缓存、有限研究、必要正文提取/上下文审核、活动投影和建议型规划，用户不需要逐面板操作许可、研究、加入资料、选活动、生成建议。预览、取消、明确采用仍使用原业务路径。

**本轮没有真实试用授权，真实业务外部调用全部0。真实小红书尚未实测。** 合成禁网验收通过不代表真实网站、真实模型质量或完整旅行可行性通过，不改写历史门禁、G1或私人版冻结结论。

基线：`05b173e70de04e6089e7dc7b21a1c1c3ed52e104`；工作分支：`feature/g1-live-llm-validation`。本批接续同一业务工作区，没有修改master。

## 生产修改与契约

- `planning/automatic_models.py::AutomaticStart/AutomaticAction`：一句需求、可选区域修正、版本化操作意图、修订及补充条件。不会要求已知人数、预算、日期、精确时刻或完整交通。
- `planning/automatic.py::AutomaticService.start/action/_create`：幂等新旅行和有限任务；缓存优先；使用现有许可账本。按钮旁明确披露用途、接收方和最小资料，服务端把这一明确意图映射到旧许可契约，记录授权版本与generation；没有伪造用户勾选或无限权限。
- `_cached/_activities`：当前有效的来源知识优先，其次按明确目的区域查已审核资料；最多两个来源、八个候选。默认排除测试卡及测试旅行关联的原始研究，不能通过回退绕过测试筛选。保留来源角色、作用范围、引用、撤销与知识版本检查；MISMATCH不自动入选，UNKNOWN不升级。
- `run_task/current/checkpoint`：持久化编排，领取一次QUEUED，通过既有受限worker完成研究和规划。子任务有独立占额和超时；各阶段检查任务、许可和修订。资料只形成有限建议时，独立合格方案可以保留，不因PARTIAL丢弃；无合格活动不造路线。
- `invalidate/recover`、`flow.py::mutate`、`workbench.py::check_active`：取消或实际条件变化先失效任务并关闭许可；阻止旧结果提交。启动把未完成任务标中断，不自动重放。取消也有持久化幂等回执。无强制取消正在运行Playwright coroutine的新增代码。
- `automatic_api.py::install_automatic`：新增两个同源POST，沿用Cookie、Origin、CSRF、账号隔离及幂等检查；GET只读投影，不派发。
- `preview/worker.py::progress/activity_target`：真实阶段由研究worker更新；自动任务取得一个合格且非明确越界的可规划活动即可给有限建议，旧手动/历史协议不变。
- `suggestions.py::launch/shutdown_workers`、`scripts/product_preview.py::task-worker`：新编排角色不能直接访问小红书或模型，只监督既有worker；正常关闭/启动处理持久化任务。
- `AutomaticPlanning.vue`、`TripIntake.vue`、`PlanningPanel.vue`：普通首屏一句输入和一次启动；来源、阶段、正文数、缓存数、失败、预算可见；结果可预览、取消、采用；自然补充优先复用；旧手动能力折叠在高级入口。提交结果未知保留幂等键，读取匹配结果后解除，不偷偷建第二任务。

显式契约变更：迁移017新增`planning_tasks`，最新schema17；导出`AutomaticStart/AutomaticAction`至domain.schema.json及OpenAPI。新POST为`/api/v1/preview/automatic-planning`及`/{session_id}`；`PlanView.automatic_task`是本地任务投影。原表、审核和用量不重写。契约文档见`docs/architecture/automatic-private-planning.md`，原日常许可文档增加当前入口补充。

## 默认有限范围

一次启动最多连接1、搜索1、正文2、模型5；地图、embedding及报价为0，一小时内有效。五次模型为最多两篇提取、两篇审核和一次建议生成，不是五次规划。可用缓存足够时收窄为站点0、模型1。失败占用派发计数，无自动重试；新明确补充创建关联许可并累计旧用量，旧剩余次数不转移。

每来源每次最多6000字，经原过滤发送到配置中的`api.deepseek.com`；不发送私址、凭据或地图返回。模型未配置时保存WAITING_CONFIGURATION且不创建额度、不联网；配置后显式继续。正常登录等待在同任务内，验证/访问拒绝/限流停止。取消不能保证撤回已发送请求，已用次数保留。

## 实际执行验证

### 离线和合成业务链

- 初次全量：1333 passed，2条既有依赖弃用警告。
- 最终新增集成及普通根入口/自动页面验收：16 passed，2条既有警告。覆盖取消回执、隐藏测试原始回退、接口鉴权、版本化明确意图、幂等、刷新零派发、失效/晚结果、无配置和显式恢复、挑战停止、重启中断和1/3/5/9天通用约束。
- 最终全量：`python -X utf8 -m pytest -q --basetemp=<隔离临时目录> -o cache_dir=.local/automatic/pytest-cache`，1335 passed，2条既有依赖弃用警告，219.48秒。
- `python -m mypy --cache-dir=.local/automatic/mypy-contract`：97 files，无问题，使用仓库既定检查范围。额外直接指定整个apps/api试跑触发了原未纳入范围的历史缺注解/缺stub错误，未据此扩展本轮开发，也没有把该扩展范围写成通过。
- 修改Python文件及新测试的ruff通过。Vue类型检查和Vite构建通过；9组现有组件测试脚本通过。
- `tools/validate_pack.py`：12类检查通过，120 schema定义、42 operation IDs、257个文档链接。`git diff --check`通过；完整未推送安全扫描在提交前后执行。

合成Reader/Model使用自编青谷与镜湖材料，真实执行ResearchService、v3提取、上下文审核、来源入库、活动投影和规划校验，不手填业务结果。适配器仅可由tests/helpers注入，生产命令/API不能选择假provider。

| 操作 | 合成适配器派发 | 结果 |
| --- | --- | --- |
| 一次提交 | connect1/search1/detail1；model3（提取/审核/规划） | 首篇有可规划活动后早停，正文1篇，非空方案，无自动采用 |
| 预览/取消/采用 | 全部0 | 使用原路径，采用前原版不变 |
| 补充“五天、不想自驾、轻松一点” | site0；model1 | 条件落实，材料复用，旧采用版保留，新建议待采用 |
| 重复领取/刷新/独立连接恢复 | 全部0 | 不重放，结果、引用和采用版一致 |
| 网站验证挑战 | 仅合成connect1；model0 | BLOCKED，禁止自动重试 |
| 条件变更后晚结果 | 不再派发规划 | 旧任务不能提交当前草稿 |

浏览器实际加载已构建Vue：一次点击直接得到建议；查看依据、预览、取消、采用、自然补充和刷新恢复通过；390px无横向溢出，无pageerror。测试服务与浏览器分别拦截外部访问，`outbound_attempts=[]/live_imports=[]`及浏览器external=[]。截图仅在本机`.local/automatic`，不提交Git。

注意以上模型/站点次数都是**合成适配器计数**；本批真实小红书connect/search/detail/browser、DeepSeek、高德、embedding和报价均为0。

### 部署与数据保护

正常停止已确认8768旧进程后启动新服务，没有停止其他页面或清库。同一`.local/p04-preview/preview.sqlite3`与`.local/workbench-web`；旧静态和一致性数据库备份留在`.local/automatic`供回滚。

当前JS：`index-N0W6-YTY.js`；CSS：`index-DIzA-_fH.css`。本地构建与生产静态文件字节一致，HTTP根页面和两项asset的SHA256一致。通过computer-use刷新用户普通页面，显示新版入口；点击“新建独立旅行”只打开本机输入表单，没有提交研究。

部署前后59张旧业务表全部原行及总数一致，schema_version仅增加17。claims37、知识卡8、jobs24、既有调用76、旅行25、回执299，全部保留；新增planning_tasks为0。当前serve审计model_http/amap_http/external_dns/external_socket/blocked_external全0；状态和刷新没有派发worker。UI审计的本地POST包含只读投影操作，不能将其误报为外部调用。

## 使用与实际边界

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

地址：`http://127.0.0.1:8768/`。已有服务时同命令为原服务重新打开本机入口。页面已保留供本人试用；本轮未代用户点击真实研究。

可用流程：一句想法→一次有限启动→可见阶段/来源→有限建议→预览/取消/采用→既有导出；补充条件优先复用。不会强制精确排时或每天排满，也不把资料不足当完整攻略。

尚未解决/未验证：真实自动XHS整链及实际模型内容质量尚未实测；普通模糊区域识别仍是确定性解析，识别不清需修正；补充支持明确的天数、驾驶/公交、轻松节奏、步行、人数房晚、范围和硬时间，任意复杂改写尚不等同自由对话理解；首次只有一份独立合格方案时如实显示一份，不造第二种方案。地图核实仍是高级手动能力，默认自动任务不会为改善完整度偷偷增加地图/报价请求。没有准确计价、可执行保证或稳定版发布结论。

完成安全提交和正常功能分支推送后停止主动开发，保留服务和页面供试用。

## Git差异与安全收尾

显式暂存32个文件；`git diff --cached --stat`在加入本收尾段前的实际快照为：`32 files changed, 1824 insertions(+), 51 deletions(-)`。主要新增编排契约与worker（664行）、自动页面、迁移017、14项新增集成用例及禁网浏览器测试；其余为既有入口衔接、契约导出和文档。

提交前32个暂存blob扫描：findings=[]；检查配置密钥精确值、凭据模式、真实原文片段、数据库/profile/图片及二进制，均无发现。三份原未跟踪T03报告保留，不纳入本批。提交后还需扫描全部未推送commit范围，再正常推送并核对完整远端SHA；不force、不合并master。
