# P10 东北七天：一次有限真实验收

日期：2026-10-08。代码基线：`3f714d404949e6d0ef48ec67be9842acab3828d8`。这是用户对上一轮零外发边界的单次追加批准，不改变历史许可、账本或成绩，不扩大到后续旅行。

## 批准范围与实际入口

- 从同一8768普通新旅行页面提交“东北7天，先比较玩法”，旅行类型选择跨地区；交通、人数、预算、日期均未知。
- 新任务上限：小红书连接1次、搜索3次、正文6篇、项目模型13次；高德、embedding和报价全部0。失败计数、无自动重试、不使用旧余额。
- 仅向原配置 `api.deepseek.com` 发送过滤后的必要公开文字与当前条件，每来源每次最多6000字。不发送私址、凭据或真实地图返回，不额外测试连接，不读图片/视频内容。
- 启动前确认无活动任务并作SQLite一致性备份。原37条Evidence、8张知识卡、26个旅行、25个旧job、80条操作账目和1个旧自动任务为本次基线。

## 当前实际结果

**整体验收未通过：任务最终为BLOCKED，停止于MATERIALS，原因NO_REVIEWED_PLAY_MATERIAL。** 研究本身为PARTIAL，原因CONTEXT_REVIEW_REQUIRED，停止码BUDGET_EXHAUSTED。取得并保留了真实的局部参考，但没有生成可比较玩法的攻略，G1仍NOT PASS，不能宣布私人版整链交付。

本地持久会话正常复用，任务确认 `LOGIN_AUTHENTICATED`，BrowserSession创建1个，没有要求重新扫码，结束后profile保留。未观察到验证、限流或访问拒绝停止码；这不代表全站安全组件已经完整测量。

| 子项 | 结果 | 实际依据 |
|---|---|---|
| 正常页面提交、登录、搜索、正文读取 | PASS | 同一8768页面一次提交；连接1、搜索3、正文读取6，无额外连接测试 |
| 动态缺口查询、共享上限、禁止超额 | PASS | 三次查询分别覆盖初始缺口、路线缺口、玩法缺口；共用6篇正文额度，没有以非空缓存提前结束 |
| 严格逐条审核、部分保留 | PASS | 50条候选中5条接纳、25条待审、20条拒绝；独立合格项未因其他项失败被丢弃 |
| 非空Evidence与知识入库 | PASS | 新Evidence5条：ROUTE3、DURATION2；生产整理形成5张新知识卡，均来自同一来源 |
| 有用玩法比较与攻略生成 | BLOCKED | 活动投影0，没有派发规划模型，也没有伪造七天内容 |
| 本次新攻略预览、取消、采用、导出 | SKIPPED | 没有合格规划结果，不能把历史或合成验收充当本次成功 |
| 本次非空资料、终态和额度恢复 | PASS | 页面刷新、正常服务重启、独立禁网进程均恢复同一结果；任务与账本未变化 |

## 真实调用和逐轮结果

| 操作 | 本次上限 | 实际用量 |
|---|---:|---:|
| 小红书连接 | 1 | 1 |
| 小红书搜索 | 3 | 3 |
| 小红书正文 | 6 | 6 |
| 项目模型 | 13 | 12：提取6、上下文审核6、规划0 |
| 高德地点/路径 | 0/0 | 0/0 |
| embedding、报价及其他旅行业务接口 | 0 | 0 |

账本计数与新产生worker的HTTP审计一致：extract-worker和review-worker各6个，每进程model_http=1，共12。所有提取诊断为HTTP200、finish_reason=stop、http_attempts=1、retry_count=0；所有审核COMPLETED、http_attempts=1、retry_count=0。没有重测连接、自动重试或新开第二次验收。未用的第13次模型额度未消费，也没有转作其他用途。

| 查询轮次 | 目标 | 观察候选 | 正文读取 | 新接纳项 | 查询后剩余缺口 |
|---|---|---:|---:|---:|---|
| 1 | 初始全部缺口 | 20 | 2 | 0 | 路线、玩法、时长、交通、季节、来源对照、选择面 |
| 2 | 路线 | 20 | 2 | 5 | 玩法、交通、来源对照、选择面 |
| 3 | 玩法 | 20 | 2 | 0 | 玩法、交通、来源对照、选择面 |

共观察60条候选，按来源去重后45个。六篇正文没有检出相同正文副本；不是已经证明作者独立。每轮的20个去重候选不能相加当作全局唯一数。

## 逐来源审核与缺口

以下S1至S6只是本次读取顺序，不是公开来源标识；不提交原文、标题、账号或token。

| 来源 | 过滤后原文字符数 | 候选/定位通过 | 接纳 | 待审 | 拒绝 | 最终提取状态 |
|---|---:|---:|---:|---:|---:|---|
| S1 | 392 | 10/10 | 0 | 5 | 5 | PENDING_REVIEW |
| S2 | 150 | 4/4 | 0 | 4 | 0 | PENDING_REVIEW |
| S3 | 313 | 9/9 | 0 | 5 | 4 | PENDING_REVIEW |
| S4 | 520 | 12/12 | 5 | 3 | 4 | PARTIAL_SUCCESS |
| S5 | 87 | 5/5 | 0 | 3 | 2 | PENDING_REVIEW |
| S6 | 344 | 10/10 | 0 | 5 | 5 | PENDING_REVIEW |

字符数通过生产canonical→catalog→payload路径本地重建；catalog先执行既有outbound_blocks过滤，再生成片段目录，均小于6000字。六篇完整度均为PARTIAL_TEXT；图片未分析，不能将短正文当作图文笔记的全部内容。定位全部通过只证明选中了现有文字，不代表上下文语义已通过。

拒绝20条的程序原因：ROLE_MISMATCH8、INVALID_REFERENCE4、UNVERIFIED_IMPORTANT_FACT4、NOT_TRAVEL_EVIDENCE3、DURATION_SCOPE_MISMATCH1。

待审25条的程序原因：CONTEXT_CONDITION_OMITTED5、UNVERIFIED_IMPORTANT_FACT4、ROLE_MISMATCH4、CONTEXT_UNCERTAIN3、INSUFFICIENT_CONTEXT3、CONTEXT_REVIEW_REQUIRED2、DEPENDENCY_UNRESOLVED2、CONTEXT_TIME_UNCERTAIN1、CONTEXT_SUBJECT_OMITTED1。5条接纳均为MODEL_CONTEXT_SUPPORTED。这是模型提议经过程序检查后的来源上下文参考，不是外部事实或旅行可行性核实。

最终Coverage仍有PLAY、TRANSPORT、SOURCE_COMPARISON、ACTIVITY_SCOPE四项缺口。ROUTES、DURATION及条件中的SEASON为SUPPORTED_REFERENCE；季节标签不等于当前或未来日期适用。玩法选择面目标5项只是研究启发规则，不是每天必须排满。只采信一个来源，不能声称多来源对照或独立作者已经验证。

### 仍未解决的产品问题

生产路径 `planning.materials.references` 能恢复这5条参考，`planning.materials.activities` 对同一集合返回0，`planning.automatic.run_task` 因空活动池在MATERIALS阶段停止。当前活动投影主要识别序列或明确地点标记，不能把整句路线背景随意拆成确定活动；本轮没有把地点提及升级为Evidence，也没有放宽范围或上下文检查。

因此本次发现的不只是“尚缺交通”：在仅有已采信路线/整体参考的情况下，普通入口仍无法给出用户期望的初步玩法比较。页面能够诚实解释缺口，但这不是攻略内容改善。后续应先用保存的最小结构和合成同类输入，区分“可引用的方向概览”与“可规划活动”的通用门槛，并复核待审原因；是否能安全改善仍需单独范围和回归。本次不追加业务代码、重新审核模型调用或站点读取，不手填活动来绕过阻塞。

## 部署、页面和恢复

运行版使用代码基线3f714d4，静态资源仍为 `index-tlXfX-qL.js` 和 `index-G8D3n-fG.css`，未覆盖旧静态备份。真实页面显示BLOCKED原因、60/45候选、6篇正文、1个采信来源及四类缺口，与数据库和正常生产view一致。

任务终止后，正常停止已确认的8768进程33960并重启为30408，仍使用原 `.local/p04-preview/preview.sqlite3`。没有disconnect、删除profile或新开研究。页面刷新完成本机会话连接后恢复同一旅行；没有自动重派发任务。

两个独立进程以只读SQL连接调用生产PlanningService和Library，socket.connect、DNS和子进程均被禁止。各恢复5条参考与5张知识卡，原7天、交通UNKNOWN和缺口未变；知识检索额外使用no_raw守卫，禁止原文、候选、模型历史兜底。两次快照的旅行状态、任务状态及全部操作账本摘要逐字一致，网络及子进程尝试均0。恢复的是非空资料和失败终态，不是不存在的新攻略。

一致性备份与当前逐行比较：原37条Evidence、8张知识卡、26个旅行、25个job、20个continuation、80条操作、13次提取、8次审核、12份正文、227个原文片段全部保留且旧行未变化。新增后分别为42、13、27、26、21、102、19、14、18、258。旧失败、旧采用版和历史授权未改写。

正常使用地址：`http://127.0.0.1:8768/`。服务已保留，验收页面停在本次结果。服务运行时重新打开入口：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py open
```

服务停止后启动同一工作区：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

浏览、刷新和查看记录不产生外部调用；本次没有点击“继续补充研究”或更新建议。任何新的真实研究都不属于本次单次验收。

## 观测与资料保护

实际账本以本次任务的 `continuation_operations` 为准；连接、搜索、详情、模型请求与浏览器网络事件分别报告，不相加为HTTP总数。

| 浏览器context观测项 | 实际值/范围 |
|---|---|
| measurement / scope | OBSERVED / context_events_since_attach |
| browser_navigation | 16个顶层导航请求事件：LOGIN1、三次SEARCH各3、六次DETAIL各1 |
| total_requests | 2018个request事件，含资源及可能被拦截/失败的请求，不代表实际发出2018次 |
| response_status | 200：1921；301：6 |
| finished_requests / failed_requests | 1927 / 88；各类事件口径不要求相加等于request数 |
| 实际发送请求、传输字节、整机/完整浏览器网络 | NOT_MEASURED |

导航指标来自is_navigation_request与主frame判定，包含重定向导航请求，不等于page.goto调用次数或新增搜索数。三次搜索窗口各有3个顶层请求且总计6个301；不能把16记成10，也不能把3次业务搜索扩报成9次。TOTAL含窗口外204个资源请求；上下文计数不是仅含搜索正文接口的计数。没有对照实测，不能据本次数据声称站点总流量已减少或这些额度是防封保证。

重启前后serve审计model_http/amap_http/external_dns/external_socket/blocked_external全部0。新模型worker合计12次HTTPS模型请求，主服务、task-worker与job-worker的Python socket审计不覆盖它们所启动浏览器的网络；因此单进程零指标不能用来宣称本次所有网络为0。

本地备份、任务标识、必要正文、模型诊断和页面截图均位于忽略目录，不进入Git。本轮没有新攻略导出；历史私人导出保留在本机。报告仅提交脱敏计数、状态及问题结论，不提交原文、账号截图、token或私人攻略数据。

本轮未调用小红书写工具；没有stealth、fingerprint、代理或验证码绕过。私人本机研究不宣称已经取得平台/作者授权，现有rights basis保持UNKNOWN。

## 检查、变更和收尾

本次真实验收不修改生产代码、提示词、事实标准、历史结果或数据库既有行。继续沿用代码批次已执行的1359项离线回归、mypy99个源文件、前端10份脚本及类型/构建检查；这些不是本次真实成功成绩。本轮新增的是只读实际结果核对、独立禁网恢复、服务重启与页面复核，辅助脚本和截图均在忽略目录。

只提交本脱敏报告。本轮实际运行tools/validate_pack.py，12/12项通过；其生成报告仅时间戳变化，恢复原时间戳以保留历史报告。git diff --check通过。明确暂存清单及完整未推送范围的密钥/认证/profile/真实SQLite/原文扫描在Git收尾执行；不提交本地实际数据。三个原有未跟踪T03报告保留。正常推送原功能分支，不合并master、不发布稳定版；最终本地/远端SHA及检查结果在本次交付消息核实。

本轮git diff摘要：新增1份验收报告；生产函数修改0。唯一真实任务已停止，不消费剩余1次模型额度，不进入下一轮开发。
