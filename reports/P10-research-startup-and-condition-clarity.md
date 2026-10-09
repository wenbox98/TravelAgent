# 研究启动与本次条件修复

日期：2026-10-09。基线：`f7decb93c288e968aab337c5d5a230f355d46d1e`。功能分支：`feature/g1-live-llm-validation`。

结论：同一8768运行版已更新，零联网启动链诊断和正常页面离线闭环通过。没有新增真实小红书、模型、高德、embedding或报价调用。真实站点新请求尚未复验，不能宣布真实研究、攻略质量或G1通过。

## 原始失败与复现

只读核对用户已经执行的两次真实任务：均建立了有效许可和研究子任务，但不足一秒就以 `JOB_STOPPED_BEFORE_COMPLETION` 失败；搜索、候选、详情、研究记录和研究派发均为0。不是已有缓存充分而跳过研究，也不是目的区域无法解析。另有一次用户已执行的空材料问答消耗模型1次，这属于修复前历史，不是本轮调用；全部记录和用量保留。

原异常只有通用原因码，没有堆栈，无法追溯证明两次原异常的全部细节。保留这一限制，不把后来复现改写成历史已保存证据。

使用启动前一致性副本、原任务配置与生产 `run_job` 路径，禁止网络和子进程并在 `ResearchService.run` 前停止：

- 受限工作进程权限下，两份输入均在 `LiveResearchReader → ProfileStore._validate_path` 的本地 metadata/lstat 处触发 `ProfileError`；未进入研究。
- 普通本机权限下，两份均通过相同构造，抵达研究边界；没有 connect、搜索、浏览器或模型派发。
- 因此复现并解决了与现象相符的权限链阻塞；原历史异常的确切根因仍受旧诊断缺失限制。没有修改 profile 安全规则或放宽文件权限。

真实输入还显示明确自驾后交通为SELF_DRIVE、地图模式仍UNKNOWN。离线复现并修复这一通用不一致。生产子进程页面测试另外发现 Windows 继承终端标准输入可延迟子进程进入脚本，已隔离stdin并隐藏窗口；这是新测试发现，不能冒称两次历史任务的根因。

## 通用函数与规则

| 文件/符号 | 修改及用途 |
|---|---|
| `preview/worker.py: failure_diagnostic, run_job` | 记录启动阶段、受限原因码、异常类型及至多5处代码位置；不存异常文本、路径、局部变量、凭据或站点响应。 |
| `scripts/product_preview.py: main` | 正式serve派生零联网research-preflight，按实际服务权限检查本地reader构造；保留服务自身live-import隔离。 |
| `planning/network.py: install` | 自检允许必要导入，同时拒绝浏览器进程及所有外部调用。 |
| `planning/suggestions.py: launch` | 子进程stdin/stdout/stderr隔离，Windows隐藏窗口，保留原一次派发与账本。 |
| `planning/automatic.py: revise, task_view` | 自驾条件同步地图模式；反向条件撤回冲突；失败后仍显示子任务停止阶段。 |
| `planning/conversation.py: view, question`、`flow.py: get` | 按真正可用资料生成提示；空资料不提供比较/推荐；未知条件说明用途且不阻止初步研究；“先给建议”走显式更新。 |
| `planning/questions.py: create`、`preview/api.py` | 空材料问答在授权和预留前本地拒绝，不空耗一次模型额度。 |
| `planning/critical_map.py: view` | 已知交通和仍待兼容的地图方式分别说明，避免已知自驾仍被要求重新回答交通。 |
| `TripConditions.vue`、`PlanningPanel.vue` | 主页面区分生效条件、未提交编辑、可暂未定项和历史采用版；本地保存/取消、刷新恢复、版本保护；编辑时阻止派发与切换。 |
| `AutomaticPlanning.vue` | 启动故障、零派发和资料缺口分开显示；空材料不出现比较快捷入口。 |

不按目的地、来源、旅行或测试编号写生产分支；不新增业务功能、数据库字段或正式领域/API schema。既有来源审核、作用范围、版本、授权和额度检查保留。新测试helper仅存在tests目录，不被产品命令导入。

## 修复前后与泛化

新增三个针对性回归先执行：修复前3 FAIL（自驾地图模式不同步、启动失败没有分型、空材料问答没有阻止模型派发），修复后通过。

合成测试通过真实构建页面、HTTP API和独立生产supervisor/研究/提取/审核/规划子进程路径，只替换外部I/O与合成配置，不用线程runner代替启动链。先制造构造失败，验证0派发和清楚的失败原因；空材料问题被本地拒绝；再提交新的明确自驾意图，正常到达CONNECT、SEARCH、DETAIL、提取、审核与建议结果。旧失败原样保留，无自动重放。

条件编辑取消保留原7天；未保存9天草稿刷新恢复且阻止切换/派发；显式保存为5天后刷新仍为5天，调用数不增加。390px页面无横向溢出。另用两个不同合成目的区域、天数未知和9天输入验证：空缓存及交通/人数未知仍进入研究，不把未知当否定或把缺口当用户错误。

所有合成浏览器和worker均拒绝外部请求；测试里的CONNECT/SEARCH等是合成适配器事件，不是真实站点验收。

## 实际检查

已执行：

- `.venv\Scripts\python.exe -X utf8 -m pytest -q tests/e2e/test_research_dispatch.py tests/integration/test_research_startup.py`：7 PASS，2条既有依赖警告。
- `.venv\Scripts\python.exe -m ruff check .`：PASS。
- `.venv\Scripts\python.exe -m mypy`：102个源文件PASS。
- `npm.cmd test`：10组前端检查PASS。
- `npm.cmd run build`：PASS，63个模块。
- 最终构建后重新执行 `tests/e2e/test_research_dispatch.py`：1 PASS；页面与独立子进程闭环、历史失败保留、条件刷新恢复及零外部调用再次通过。
- `.venv\Scripts\python.exe -X utf8 -m pytest -q --basetemp E:\workSpace\travel-agent-project\dispatch-final-tests`：1395 PASS，2条既有依赖弃用警告，488.70秒；无FAIL/SKIPPED。最后的前端故障分类保护另经最终构建与SSR回归通过。
- `.venv\Scripts\python.exe tools\validate_pack.py`：12/12文档、契约与合成数据校验PASS，不代表实站通过。
- `git diff --check`：PASS。

## 8768部署与保护

确认旧服务属于本工作区且没有运行中任务后正常停止，保留数据库与旧静态资源；部署新资源并最后替换入口文件。用普通本机权限执行唯一启动命令，新服务PID25148，实际派生的自检PID11708：ready=true、BrowserSession=0。serve和preflight的model/amap/DNS/socket/blocked_external计数均为0。

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

入口：[本机工作台](http://127.0.0.1:8768/)。服务保持运行，不重复启动；本机会话失效时同一命令签发新入口。启动不重新执行旧任务或恢复额度。

健康检查200。实际提供的index、JS `index-YEjJul_k.js`、CSS `index-DdmwGlnc.css`与最终构建逐字节一致。用户原页面独立刷新后已看到当前7天/自驾、生效条件区、未知项的补充原因、历史与采用版区分，以及历史零搜索的启动故障说明。没有点击研究或修改用户条件。

启动前后原库61张表逐表行数及内容SHA256完全一致，活动、Evidence、审核、采用版、历史失败、选择和账本均未修改；原operation-audit计数没有增加。私有副本、堆栈诊断、截图和数据库只保存在Git忽略的本机目录，不入Git。

## 使用与剩余限制

首页“本次已生效条件”是下一次操作使用的当前值。修改后先保存或取消；日期、人数、预算等可暂未定，页面说明以后补充的用途。旧消息不代表当前偏好，采用版在明确采用前不会被本地编辑覆盖。

空材料时没有可比较的方案，不会花一次模型请求来回答“为什么推荐”；需要用户以后明确发起新的有界研究。失败记录保留，不能靠重启、刷新或点击读状态重试。启动自检仅证明本地构造可用，尚未证明当前站点登录、搜索、详情或真实内容质量。没有新增真实调用授权前，本轮停止于修复和离线验收。

`git diff --cached --stat`收尾快照（报告最后补记前）：25 files changed, 669 insertions(+), 28 deletions(-)。主要新增为受限启动诊断、条件组件及独立进程页面回归；无依赖、正式schema或真实资料变更。

明确文件清单暂存25项；扫描暂存内容和完整未推送范围、当前配置密钥及原文片段，findings=[]。未包含profile、认证入口、真实数据库/正文、截图或敏感诊断。推送按原功能分支执行，不合并master；最终提交及远端完整SHA以交接消息为准。原三份未跟踪T03报告保持不动。
