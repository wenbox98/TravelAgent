# 路线方向与主对话更新验收

日期：2026-10-09。开发基线：`c016cf44af2c0ea4439b4c23f1cf0c4fdd1f68c0`，功能分支 `feature/g1-live-llm-validation`。

本轮收尾方向拆分、当前取舍进入更新、明确修改的一次发送和状态一致性。全部真实业务外部调用为0。此前已授权的东北研究已结束，本报告不重跑、不挪用其剩余额度；真实研究数据与计数见 [独立记录](P10-northeast-live-validation.md)。G1仍为NOT PASS，当前路线参考不是完整攻略。

## 修复前问题与通用规则

| 修复前 | 生产修复后 | 验证 |
|---|---|---|
| 同一来源的三条已证明路线合并成一张卡 | 按来源、对象文字、作用范围、定位及作者角色拆分；三个方向仍只计一个来源 | 合成对象投影及实际缓存页面 |
| 同源时长容易附到不相关对象；引用变更后旧选择可能沿用 | 时长/取舍必须与同一已证明对象关联，完整绑定和规则版本变化使选择失效 | 同名异定位、跨来源及绑定变化回归 |
| 只有路线参考时，选方向不能启用更新 | 路线选择、排除、撤回和恢复有独立状态；当前有效取舍进入缓存问答、研究焦点和覆盖重评估 | 页面按钮、真实生产payload只读检查及合成worker |
| 明确修改也先问答，再确认，再点更新 | `submission_intent` 对明确修改直接解析、锁定校验及有界更新；纯问题/假设只问答；模糊提议一次确认并更新 | 正常Vue页面合成全流程及API回归 |
| 任务刚完成后，立即发送偶发版本冲突 | planning GET在同一事务读取任务和对话，地图展示在事务外 | 全量回归实际复现后修复，确定性并发测试 |

规则不依赖城市、景点名、来源ID、旅行ID或验收编号。参数化回归更换目的区域、天数和对象数量（1/3/5）；跨来源不拼接、同名不同定位不拼接。明确输入与假设分流不靠目的地关键字。没有已证明关系仍保持未知，没有具体活动不制造日序或景点。

## 修改文件和符号

- `planning/reference_overview.py`：`VERSION`、`object_key/project/choices/focused/derive/view/export`。投影升级为 `local-route-overview-3`，保留旧历史，不把旧版取舍静默迁为新版通过。卡片标题、作者角色、条件摘要与时长来自合格引用。
- `planning/conversation.py`：`ConversationAction`、`LOOP_CONSENT`、`submission_intent/action/model_context`。统一提交、一次确认并更新、逐方向排除/恢复；冻结当前有效取舍，保留原锁定、版本、generation和幂等检查。
- `planning/automatic.py`：`coverage`、`AutomaticService._create/action`。覆盖评估包含合格宏观路线，具体更新优先缓存；后续有限研究上限独立于首次大范围研究，不恢复旧预算。
- `planning/questions.py`：`payload/create/run`。当前条件、有效路线与排除进入最小输入；实际发送引用以外的路线不进入允许选项。仍执行逐来源策略与6000字过滤，结果只作建议，不入Evidence。
- `planning/private_payload.py`：`assemble`。排除方向对应引用及活动不能漏入规划；锁定冲突拒绝，全部活动被排除时保留阻塞，作用范围不扩散。
- `preview/jobs.py`、`preview/worker.py`：`JobService.create`、`run_job`。研究请求带最新交通条件和当前路线焦点；领取及每次I/O前重校路线绑定，旧结果不能写入新取舍。
- `planning/flow_api.py`：`install_flow.read`。同一状态快照读取，修复完成状态与旧对话版本混合的竞态。
- `AutomaticPlanning.vue`、`PlanningPanel.vue`、`planning-api.ts`：统一发送入口、紧邻对话的输入框、默认最多三个简明卡片、可撤回取舍、一次确认并更新，详细引用和次数折叠。
- `contracts/domain.schema.json`：新增动作和版本化许可枚举，API路径不变，数据库无需迁移。相关架构契约、README、测试同步更新。

## 执行检查与失败记录

修复期间首次完整检查为2失败/1380通过：契约尚未重新生成、浏览器测试早于新前端构建结束；准备完成后分别复验。第二次完整检查为1失败/1384通过：正常Vue测试捕获任务完成后下一次发送的版本冲突。定位为状态读取跨快照，新增确定性并发回归并修复生产GET。

最终受限进程的一次测试尝试因Windows临时目录清理权限出现466个setup错误/920通过，属于测试环境错误，未记为通过；改用获准的本机离线执行。最终结果见下方收尾记录。

已执行：

- Python定向回归（对话一致性及正常Vue端到端）：9通过，23.14秒。
- Ruff：通过。
- mypy：102个源文件通过。
- 前端10组测试：通过；Vue类型检查及Vite构建：通过。
- 合成新增回归：逐对象绑定、单次明确修改、假设不改条件、一次确认更新、选择/排除进入最新输入及研究焦点、幂等、晚结果隔离、非空重开恢复。

最终全量Python回归：**1386通过、2条依赖弃用警告，239.32秒**。文档验证：12/12通过；123个领域定义、217处契约引用、45个API操作和268个Markdown链接通过离线结构校验。最终前端10组测试再次通过。没有失败或跳过被记成通过。

实际命令（仓库根目录；前端命令在 `apps/web`）：

```text
.venv/Scripts/python.exe -X utf8 -m pytest tests/integration/test_planning_conversation.py tests/e2e/test_automatic_workbench.py -xq --basetemp E:/workSpace/travel-agent-project/.test-tmp-route-racefix
.venv/Scripts/python.exe -X utf8 -m pytest -q --basetemp E:/workSpace/travel-agent-project/.test-tmp-route-final-authorized
.venv/Scripts/python.exe -m ruff check apps/api tests/integration/test_route_direction_iteration.py tests/integration/test_planning_conversation.py tests/helpers/automatic_fakes.py tests/helpers/automatic_ui.py
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -X utf8 tools/validate_pack.py
npm.cmd test
npm.cmd run build
```

## 同一8768实际缓存验收

保持原数据库及历史采用版。通过普通页面本地派生、选择、排除、撤回、恢复与导出：3个路线方向、1个来源、5条已采信引用；具体活动0、采用版空、旧自动任务仍BLOCKED。主旅行仍为7天、驾驶未知，未为了测试直接改数据库或制造活动。

本地测试暂选其中一个方向并排除另一个，均可在页面撤回，不是长期偏好。选择后更新入口可用。已输入但未发送「只有5天，不想自驾，按当前方向更新建议」。独立只读进程按真实生产函数构造输入：最新5天/不自驾、当前选择与排除、2条最小引用、1个来源；排除方向引用不在模型允许集合。没有创建任务、消费额度或发送模型请求。

正常关闭并重启同一服务后，路线版本、取舍、页面投影和导出指纹一致；最后的状态快照修复也已加载到8768，再次刷新和独立进程验证通过。实际下载Markdown与生产导出内容一致。恢复探针拒绝socket、DNS和子进程，尝试数均为0。保留11张受保护表全部逐行哈希与计数：Evidence 42（此前37加本次真实研究5）、来源18、策略1、抽取尝试19、审核14、候选175、知识卡13、操作102、许可21、自动任务2、研究任务26。仅普通本地会话、路线投影和动作回执按页面操作新增，不改历史审核或账本。

启动命令（已运行时直接用页面）：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

本机地址：http://127.0.0.1:8768/ 。原工作库与静态回滚副本保留；截图和最小payload只在Git忽略的本机私人目录，不提交真实资料。

## 调用与剩余阻塞

| 本轮修复 | 实际业务调用 |
|---|---:|
| 小红书连接/搜索/详情/浏览器 | 0/0/0/0 |
| 项目模型 | 0 |
| 高德地点/路径、embedding、报价 | 全部0 |

计数依据为无新worker派发、原账本逐行不变及禁网恢复探针；本轮服务全量网络事件、实际出网字节仍NOT_MEASURED。Git推送与本机页面访问不计业务调用。合成测试中的模型和地图通过不等于新增实站验收。

当前可交付：更细的有依据路线比较、本地取舍、清楚的主输入、缓存输入的版本化闭环及零访问恢复。仍不能交付完整东北攻略：只有宏观路线/时长，玩法、交通和独立来源对照不足。关键地图段没有两项合格具体活动，实站问答与地图也未在本轮执行；不得用更多PARTIAL标签宣称内容改善。

如用户另行批准，可仅验证一次缓存路线问答：同一最小公开引用及当前5天/不自驾取舍，既有DeepSeek，模型最多1次，全部站点/地图调用0；这将是独立追加许可，不使用此前余额。批准前停止真实派发，不继续扩大功能。

## Git与交接

暂存仅包含本轮生产代码、契约、合成测试和中文文档共23个文件；旧三份未跟踪T03报告保留。暂存内容安全扫描23个blob，覆盖本机已配置凭据和真实正文片段匹配，发现0项；没有提交数据库、profile、原文、页面截图或私人诊断。提交后还需扫描完整未推送范围，再安全推送原功能分支并比较完整SHA，最终同步结果随交接给出。

`git diff --stat`摘要：生产路径8个Python文件、前端3个文件、领域契约1个文件、前端及Python测试5个文件、README/架构文档/验收和校验报告6个文件。变更集中在对象拆分、取舍绑定、统一主输入及快照一致性；无数据库迁移、外围产品功能或真实外部派发。
