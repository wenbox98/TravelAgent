# 普通输入提交反馈与安全恢复

日期：2026-10-09。基线：`7f64cb599d5cabfeff6236f0a34d3071c0bdd15a`。分支：`feature/g1-live-llm-validation`。

本轮只修复正常旅行输入和主对话的提交反馈、草稿保留及响应恢复。真实模型、小红书、高德、embedding和报价调用全部为0；没有提交用户当前未发送的旅行想法，没有重开历史许可。既有路线材料和G1 NOT PASS不变，本报告不是新的真实攻略验收。

## 问题与通用规则

用户反馈页面宣称可用 Ctrl / ⌘ + Enter，但按下后无法判断是否提交。检查确认：旧界面在连接/认证未就绪时仍宣传快捷键；父组件的忙碌和编辑拦截可能直接返回；发送没有明确区分本机接收和后台建议完成。会话消息也没有完整的本机草稿保留。

审查中另发现中间实现的问题：把断线/5xx记为结果未知后，只凭当前投影的intent_key解除阻塞。若请求根本没送达，重连和刷新永远找不到该标识，就没有安全继续入口。现改为先只读恢复；找不到时提供显式手动继续，保留原请求正文、地址及幂等标识。已有服务回执在版本检查前命中，任务领取仍只允许QUEUED一次；未接收才执行原操作。没有清空未知意图、换新标识或后台重试。

| 场景 | 当前行为与已执行验证 |
|---|---|
| 加载、认证失效、空输入 | 按钮及快捷键提示实际阻塞原因；不发送POST |
| 点击/快捷键后本机响应较慢 | 立即显示“正在提交”“尚未确认接收”；再次按键不重复发送 |
| 中文输入法确认、长按、普通换行 | 不误提交；正常Ctrl/Meta快捷键可提交 |
| 未保存条件 | 输入框附近说明先保存；真实旧详细旅行的可编辑天数字段回归通过 |
| 明确首次4xx拒绝 | 保留输入、显示拒绝原因；不会把拒绝说成接收成功 |
| 已接收但回复丢失 | 保留原意图；读取状态或整页刷新确认接收，无新POST |
| 未送达请求 | 刷新只GET；明确点击“继续确认原提交”才沿用原标识/正文提交 |
| 继续确认时认证拒绝 | 不能证明原请求未接收，保留原标识；恢复后继续同一原请求 |
| 发送之后又编辑文字 | 只清理已确认接收的原文字；不同的后续草稿保留 |
| 接收成功后旅行列表刷新失败 | 保持已接收结论，不把成功误报为需要重发 |

规则不按目的地、来源、旅行ID或测试编号分支。没有更改来源审核、模型事实标准、预算或规划门槛。

## 修改文件和符号

- `apps/web/src/intake.ts`：`submitShortcut`忽略重复按键和输入法事件；`readMessage/storeMessage`按旅行保留未提交会话文字。
- `TripIntake.vue`：`blocked/buttonLabel/start/keyboard`、输入法状态、输入附近反馈及只读恢复/手动继续事件。只有实际可提交时才宣传快捷键。
- `AutomaticPlanning.vue`：`blocked/sendLabel/notice/send/keyboard`、分旅行消息草稿、接收确认后精确清理原文字。历史消息相同本身不再被当成新草稿已提交的证明。
- `PlanningPanel.vue`：`feedback/submissionFailure/reconcileSubmission/pendingMatches/pendingSession/offerSubmissionRecovery/resumeSubmission/acknowledgeMessage`；`load/automatic/talk/create`分别反馈拦截、提交、接收和恢复。主任务/会话任何一方未知时，阻止新业务意图派发。读取恢复状态时如遇认证错误，可通知原入口重新连接。
- `tests/helpers/submission_ui.py`及`tests/e2e/test_submission_feedback.py`：真实构建的Vue页面、禁外网合成服务、延迟/拒绝/未送达/回复丢失/整页刷新/后续编辑/旧条件拦截回归。
- `tests/helpers/entry_ui.py`：适配真实不可提交提示，明确拒绝使用422模拟；5xx不再伪称确定未接收。
- `apps/web/tests/automatic-planning.mjs`：SSR加载新增草稿辅助函数。README补充正常使用与安全恢复说明。

API路径、请求/响应契约、数据库schema均未改变。沿用现有服务器幂等协议，没有新增回执清理或预算重置。

## 执行检查及失败记录

开发期间新增旧详细条件回归曾因定位隐藏字段超时失败：测试还未展开“修改条件”，且过早撤销创建请求的测试拦截。修正测试中已有详细模式的准备和实际展开步骤；没有删除dirty guard覆盖，也没有修改正常新旅行的建议模式默认值。此失败不计为通过。

已执行：

- 恢复定向页面回归：1通过，12.36秒；补齐认证及精确草稿清理后，最终普通入口/自动工作台/提交恢复三项：3通过，35.62秒。
- 前端10组离线测试通过；Vue类型检查和Vite构建通过。
- Ruff全仓检查通过；mypy 102个源文件通过。
- 最终全量Python回归：1387通过、2条依赖弃用警告，370.72秒；失败0、跳过0。
- 文档验证：12/12通过，269处相对Markdown链接有效；123个领域定义、217处契约引用和45个API操作的离线结构检查通过。

实际命令（前端在`apps/web`，其余在仓库根目录）：

```text
npm.cmd run test
npm.cmd run build
.venv/Scripts/python.exe -X utf8 -m pytest tests/e2e/test_submission_feedback.py tests/e2e/test_workbench_root_entry.py tests/e2e/test_automatic_workbench.py -q --basetemp E:/workSpace/travel-agent-project/.test-tmp-submit-recovery-final
.venv/Scripts/python.exe -X utf8 -m pytest -q --basetemp E:/workSpace/travel-agent-project/.test-tmp-submit-full-final
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -X utf8 tools/validate_pack.py
```

页面回归使用独立合成SQLite、只读校验及自编适配器。浏览器拦截非本机请求；服务禁止出网并记录live imports。最终合成服务出网尝试0、真实XHS模块导入0。未送达的首次任务在手动继续前任务数0，继续后1；多次消息异常恢复后仍只有4个预期缓存问答任务，没有重复任务。

## 同一8768部署、数据保护与操作

更新前保留SQLite一致性备份和原静态目录，只在Git忽略的本机私人目录存放。将新哈希资源复制后最后切换首页，后台API未改，无需停止原服务。实际HTTP首页及两份资源逐字节等于最终构建：`index-CFQ4O2nW.js`、`index-Bmp6LqQo.css`；health返回200。

通过现有本机启动器正常签发并打开新入口，不绕过认证、不输出短时入口值。实际8768页面刷新后，原旅行、路线方向和历史失败继续可见；新建入口空输入按快捷键立即显示“未提交：请先写下旅行想法”，未创建旅行。验收页保留供查看。用户Edge页由另一聊天占用控制，本轮未修改其输入或替其提交；重新打开原浏览器入口沿用同一origin/profile，本机草稿保留逻辑有合成刷新和后续编辑回归覆盖，不将未直接取得的Edge草稿复核宣称为PASS。

部署及页面检查前后，主库61张表的逐行哈希和计数完全相同，包括原Evidence、来源、知识卡、用户选择、任务、失败及全部账本。79份原服务指标文件无变化；当前服务记录model_http/amap_http/external_dns/external_socket/blocked_external均为0。未启动新的业务worker或小红书浏览器。浏览器或系统全量出网字节及事件仍NOT_MEASURED；Git同步不是业务调用。

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

地址：http://127.0.0.1:8768/ 。服务已运行时同一命令只打开有效入口。正常操作：填写想法后点击按钮或Ctrl/⌘+Enter；等待“已接收”再看任务进度。结果未知先读取状态；只有仍找不到原接收记录时才手动继续原提交，不需要复制Cookie、清空数据库或反复新建旅行。

## 剩余限制与Git

这次没有运行任何真实模型或研究验收，没有因此改善已有真实攻略内容或改变G1。浏览器本机存储被用户清空、损坏或禁止时，跨刷新草稿/原意图恢复不作保证；不要通过清空存储解除未知结果。高级本地模式的旅行创建不属于新增业务任务恢复协议，原接口行为保留。下一次真实请求仍须已有适用许可，本轮没有扩大许可。

收尾按明确文件清单暂存、扫描配置凭据和真实正文片段，扫描完整未推送提交范围后安全推送原功能分支并核对完整SHA。不合并master，不提交运行库、profile、原文、截图或私人诊断；旧三份未跟踪T03报告保留。实际Git结果与diff摘要在最终交接给出。

`git diff --stat`摘要：12个文件，前端4个生产文件及1个前端测试、3个Python合成测试文件、README和3份报告；变更集中在提交状态、草稿与幂等恢复，无API/数据库迁移。暂存12个blob安全扫描0项发现，覆盖本机已配置凭据及真实正文片段；最终提交范围复核和远端完整SHA随交接返回。
