# 运行中服务中断诊断与恢复

2026-10-10；基线`ecd988762d4784425bd13417576f572353a625fa`。

本轮恢复同一8768工作台，修复异常中断后的状态收敛和页面提示。新模型、小红书、高德调用全部0。以前的正常重启PASS不代表意外退出PASS；本轮也不宣称原退出根因已经修复。

## 真实中断证据

恢复前先只读保存61张表、8654行、完整SQLite备份、目标任务关联记录及430个审计文件。账号资料、业务ID、原文和审计原文仅保存在Git忽略的私人目录。

- 原服务和全部Python进程已退出，8768不可用；数据库主任务仍RUNNING/RESEARCH，研究子任务停在REVIEW。
- 旧许可预留连接1、搜索1、正文1、模型4，失败和未完成请求也计数；没有新建许可、退款或重放。
- 两次需求/监督模型调用完整结束并返回HTTP200。一篇PARTIAL_TEXT已缓存，必要正文416字；提取完整返回HTTP200，保存12条待审候选，状态PENDING_REVIEW。
- 审核只留下HTTP200响应头、BODY_READ检查点，没有完整结果。检查点中的默认UNEXPECTED_ERROR分类不能证明具体发生过哪种异常。
- 新接纳Evidence为0，草稿项目0，没有新生成或采用攻略。待审候选不能当作合格事实。
- 保存的登录状态为LOGIN_AUTHENTICATED，未发现验证挑战记录；不据此证明退出时实时页面没有挑战。
- 原终端会话已不可查询，未取得退出码。对应Windows Application时间窗口没有匹配的警告/错误事件；System只找到无已证明因果关系的DistributedCOM10016。

**退出根因：EXIT_CAUSE_NOT_DETERMINED。** 不推断为休眠、内存不足、模型超时或终端关闭。

## 修改的通用函数和规则

| 生产路径 | 修改 |
| --- | --- |
| `preview/lifecycle.py::interrupt_grant` | 关闭同一许可，收敛活动子任务、未完成提取/审核；保留传输诊断、完成结果、候选及已用账本。兼容旧服务把重启子任务留为无原因CANCELED的情况。 |
| `planning/automatic.py::invalidate, recover, _recover` | 重启和总时限明确标INTERRUPTED；恢复在事务中执行，也清理已关闭许可的活动审核；不派发旧任务。 |
| `planning/suggestions.py::_worker_finished` | worker退出时收敛其提取/审核子记录，保留原因和退出码。 |
| `research/recovery.py::ExtractionRecovery.run_reserved` | 晚到提取不能覆盖中断记录或写候选；异常收尾不改已确定终态。 |
| `research/context_review.py::run_review` | 晚到审核不能覆盖中断；每条接纳事务继续检查许可和任务，保留独立合格结果。 |
| `api.ts::request` | 本地轮询等待上限5秒；原提交默认15秒和幂等保护保持。 |
| `PlanningPanel.vue` | 编辑及等待POST时仍检测连接；自动恢复只发GET。保留输入及未保存草稿，不重发原提交。 |
| `AutomaticPlanning.vue, AgentProgress.vue` | 断连显示进度未知；中断父任务的历史DISPATCHED步骤明确未完成，不能继续声称正在执行。总时限和worker退出分别解释。 |

没有目的地、来源、旅行ID或测试编号特判；没有改变事实标准、额度、模型、提示词或提取协议。没有数据库结构及外部API契约变更，原传输诊断不增加私有字段。

## 实际故障注入

使用独立合成数据库、静态目录、页面和进程，没有对生产8768做故障注入。`tests/helpers/lifecycle_server.py`只用于测试，生产入口不加载。服务和actor的审计钩子禁止外联，落盘外联尝试0。

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| 运行中服务突然退出 | 实际强制结束隔离服务/worker；旧页面虽报连接失败，仍显示正在查资料、正在执行、任务进行中。 | 实际只终止隔离服务，留下合成worker。19:54:04.213终止，19:54:06.905页面已显示连接中断、进度未知、等待连接，未发送文字完整。约2.7秒是此次观测间隔，不是所有环境保证；轮询等待上限5秒、间隔最多3秒。 |
| worker退出7 | 真实子进程退出后审核残留RUNNING。 | 生产supervisor监测实际退出7；正常隔离页面显示后台任务意外停止、未自动重试；步骤明确未完成，审核INTERRUPTED。 |
| worker被kill | 实际OS终止后审核仍RUNNING。 | 真实进程kill用例通过，主任务和审核终止、许可关闭、不重复派发。 |
| 总时限 | 旧实现分类CANCELED，未收敛审核，页面无清楚的总时限说明。 | 真实等待进程配合测试时钟加速跨过生产deadline，得到TASK_DEADLINE/INTERRUPTED、审核收敛。没有缩短产品实际时限或强制cancel Playwright coroutine。 |
| 重启 | 主任务关闭后审核仍RUNNING。 | 同一隔离库恢复主任务及审核INTERRUPTED；材料、候选、输入、账本摘要相同，没有新建worker。未发送文字在恢复和刷新后仍保留。 |
| 审核晚到 | 对中断终态保护不完整。 | 普通RUNTIME审核在回复返回时模拟owner中断，不能恢复COMPLETED或接纳候选。 |

服务退出不等于所有worker同时退出；浏览器无法确认时明确说未知。本轮actor不执行业务；恢复关闭旧许可并阻止晚到提交。没有增加常驻监控，也不宣称消除了所有进程退出原因。

## 实际检查结果

- 修复前5个定向用例失败：恢复后的审核残留、退出后的审核残留、真实非零退出、真实kill、deadline分类。
- 相关离线回归117项通过：`test_extraction_recovery.py`、`test_model_context_review.py`、`test_automatic_planning.py`、`test_cached_body_reprocess.py`、`test_goal_agent.py`。
- 原子恢复后，生命周期/自动规划/审核56项通过；增加旧版本兼容及普通审核晚到用例后，最终生命周期12项通过。数量重叠，不相加作为独立测试总数。
- Vue组件检查、TypeScript检查及最终Vite构建通过。最终资源`index-DOGqthOZ.js`、`index-Cleq0VSU.css`。
- 修改文件ruff通过。mypy配置API及sidecar导入路径后，仍有未修改基线错误：`research/cached_reprocess.py:60`的`old=[]`缺类型注解；Git基线代码相同。该检查不写为全通过。
- 没有重新运行全部历史测试，不改写旧结论。

可复现命令（仓库根目录；新的隔离目录必须不存在）：

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_worker_lifecycle.py -q --basetemp=../interruption-recheck-host
.venv\Scripts\python.exe -X utf8 tests/helpers/lifecycle_server.py prepare --workspace .local/lifecycle-new-check
.venv\Scripts\python.exe -X utf8 tests/helpers/lifecycle_server.py serve --workspace .local/lifecycle-new-check --port 18778 --dispatch nonzero
```

测试actor只在该目录出现`release-worker`文件后退出7。测试页面使用对应启动生成的本机入口。终止前核对进程命令行属于该隔离目录；不得用于生产服务。所有本轮隔离测试进程已清理。

## 部署、数据与零外部调用

正常关闭原8768，保留原静态目录作私人备份；以现有`product_preview.py serve`和原库后台启动新版。服务PID15416、launcher PID22476；health HTTP200，构造预检ready=true、browser_sessions=0。没有用故障注入杀生产服务。

- 正常8768页面已打开并恢复新旅行，显示服务重启、未自动重放，历史DISPATCHED步骤显示未完成。
- 恢复前61张表/8654行没有新增或删除；只改对应1条主任务、1条研究子任务、1条许可和1条审核的中断状态、原因、结束时间。
- 新旅行完整state_json、旧A/B完整会话与采用版、全部资料/Evidence/候选/历史审核/账本保留；提取仍PENDING_REVIEW，12条候选仍待审。
- 430个旧审计文件内容保留；所有metrics文件累计对比，model_http/amap_http/external_dns/external_socket/blocked_external增量均0；小红书connect/search/detail/browser新增全部0。
- 三份原未跟踪T03报告hash不变；原导出保留。不重新读取正文，不恢复旧额度。

本机地址：`http://127.0.0.1:8768/`。需要重新打开有效入口时，在仓库根目录运行：

```powershell
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

服务已运行时只重新打开入口。用户主动发送才创建正常有限操作，本轮没有代为发送新研究。

## 结论与剩余问题

状态收敛、断连提示、输入保留、意外worker退出及重启不重放通过上述定向实际验证。退出根因仍未知，不能保证以后不再退出。新旅行还没有可用攻略，缓存正文和待审候选只是未完成资料；G1和原内容质量结论不变。

保留上述基线mypy问题。本轮停止于恢复与生命周期修复，不续做被拒的缓存模型阶段，不合并master或发布稳定版。

## Git diff 摘要

补记本节前实际执行`git diff --cached --stat`：14个文件，436行新增、25行删除。涉及5个API文件、4个前端文件、3个测试文件及README/本报告。只暂存明确清单；真实数据库、原文、profile、日志和三份T03报告不在提交中。
