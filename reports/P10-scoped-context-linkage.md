# P10 范围化内容关联与定向收尾

## 范围与基线

基线 `cf889bfc36ddf3fe07cc4fd2bc700f041875bc21`，实际分支 `feature/g1-live-llm-validation`。同一8768入口、原SQLite16工作库、原静态目录，开工快照为37条Evidence、8张知识卡、23条任务。未重新研究、多日模型验收或修改旧门禁。G1保持原NOT PASS。

本轮修复通用关联：直接地点引用、整体对象背景、未关联来源补充分开。没有目的地、景点、来源或旅行标识专用分支，没有向数据库手写活动或攻略，没有修改历史导出。

## 诊断链与真实依据

本机检查最新城市场景的两条已接纳记录：一条ROUTE、一条EXPERIENCE，来源性质均为GUIDE_SUGGESTION。二者的已审核对象定位相同，规范化正文版本相同；路线明确列出的成员包含当前两个选中项目。这里证明的是来源中的同组线索，不能据此认定行政归属、每站特色或作者亲历。

原链路损失有两处：`preview.projection.project` 内 statement 未投影原 `route_association`；`private_payload.payload` 只按活动直接 evidence_ids 保留引用，整体体验因不逐字提及每个成员而消失。没有重新请求模型识别关系或修改原审核。

私人完整诊断保留在 `.local/p10-linkage/claim-chain.json`、`original-planning.json` 和 `production-payload.json`，不提交Git。最终请求前独立禁网构建真实生产payload：2条必要引用、1个来源、1条GROUP_BACKGROUND、2个目标；按来源文本/条件/对象及重复背景计数151字，小于6000字。直接活动标签仍为ROUTE_CONTEXT，未提升为CONTENT_REFERENCE。新P07许可绑定该背景关系，关闭的旧许可不能使用。

## 通用函数、规则与契约

| 位置 | 修改与边界 |
| --- | --- |
| `preview.projection.project::statement`、`PreviewEvidence` | 保留审核对象和source_version；版本使用已校验canonical locator前缀，含正文规范化版本/类型/哈希。 |
| `scoped_context.anchor/derive` | 审核对象+版本+明确路线成员建立整体关系；明确主体支持直接内容；同源共现只作未关联补充。同源多个项目不重复计数。 |
| `private_payload.payload/assemble`、`discovery.model_references` | 普通、提及和混合输入分别保留直接引用及必要背景，继续过滤、SourcePolicy与字符上限。提及不升级为Evidence。 |
| `scoped_context.attach_context` | 重复携带的背景文字也计入上限，超限拒绝，不裁掉条件。 |
| `workbench.authorize/DailyBudget.check_payload/reuse`、`materials.references` | 新许可绑定背景ID；正常历史复用明确保留必要关系引用；不扩权旧许可、不恢复旧额度。 |
| `knowledge.organize.prepare`、`Library.get`、`knowledge.planning.card_references/payload` | 新整理卡保存同审核对象的必要关系；原卡不自动迁移，缺元数据未知。卡片/来源版本和撤销检查保留，清原文后的合成隔离测试受no_raw约束。 |
| `GuideContextUse`、`advisory.validate/apply` | context ID、目标集合、用途、简短理由；程序展示原条件和角色，模型不再重复抄写。逐方案验证，错误关联不带过独立合法方案。 |
| `guide_assessment.references`、`guide_view.project/export`、`AdvisoryGuide.vue` | 整体背景、直接内容、AI取舍与未知分开；取消/采用、改选后和导出时重算。 |

规则为scoped-context-1、scoped-use-1.1、advisory-guide-1.6.1；协议仍v4。domain schema增加可缺省DTO字段；生成器确认OpenAPI路由无需变化。SQLite16不迁移，旧模型回复、审核和采用内容不回写。

## 真实请求与误判修复

通过普通页面追加1次模型许可，其他额度0；旧许可保持CLOSED。必要数据只发给原配置 `api.deepseek.com`，未测试连接、未重试。120秒响应/180秒总截止保持。

唯一请求HTTP 200，12.0482秒，`http_attempts=1`、`retry_count=0`，结构完整，返回1个方案。最初规则1.6以 `GUIDE_CONTEXT_SCOPE / context_uses.reason` 拒绝，原FAILED记录保留。

原因是新增正则误把明确否定推断的理由当作肯定传播：模型表示不能由整体背景推断各站特色/人流。已保存回复没有据此断言各站特色。修复为按分句检查受限否定谓语和范围对象，转折后的肯定断言仍拒绝，不能因出现“不”放过整句；其余事实、引用、范围与锁定检查保持。该修复适用于任意对象，不匹配本次真实文本或标识。

33项定向禁网回归通过。原输入和原回复经完整生产校验零联网复核，规则1.6.1接纳1、拒绝0、无normalization。这是LOCAL_REVALIDATION，不是第二次模型生成或Work人工审核，也不把旧失败改成成功。

## 回归证据

修改前先运行生产投影/载荷测试：2失败，分别复现对象元数据丢失和目标背景缺席。修改后两例通过；最初输入仍为协议2的建议前置数据，之后测试显式使用建议模式继续验证页面、内容标签和工作流。

| 语义 | 结果 |
| --- | --- |
| EXPERIENCE明确指向地点，不含路线箭头 | PASS：按明确主体关联。 |
| 整体体验未列出所有子地点 | PASS：背景可用，地点特色标签不升级。 |
| 不同对象、不同来源/版本、同名与子串 | PASS：不能串联；只同源的无关系项留作独立补充。 |
| 未审核/待审材料 | PASS：不进入已审核背景。 |
| 否定、季节、未亲历、条件 | PASS：原文及角色/条件保留；否定关系句与肯定断言分开检查。 |
| 普通/地点提及/混合生产输入及页面 | PASS：合法背景保留，提及仍NAME_ONLY。 |
| 账号/SourcePolicy/材料许可/已关闭旧许可 | PASS：不允许外发的材料不可派发；不借用旧额度。 |
| 模型虚构ID/目标/向下传播 | PASS：错误方案拒绝，独立合法方案保留。 |
| 删除项目或替换选择 | PASS：目标集合重算，无相关项目无背景，旧采用版不写回。 |
| 单一来源支持多个节点 | PASS：source_count仍1。 |
| 派发后撤销来源/改选/关闭许可/更新卡片 | PASS：Fake实际进入调用后制造变化，晚到结果不能采用。 |
| 知识卡清原文、旧卡缺元信息 | PASS：隔离合成库清理后no_raw仍可构建已保留关系；旧卡不猜补。主库未清原文。 |
| 不同目的地与原P10日序/预算/柔性时间 | PASS：参数化与原全量回归，保留原两日成果。 |
| 页面/导出与独立进程禁网恢复 | 合成生产链PASS；真实页面结果见下节。 |

初轮全量1272通过；随后范围否定句修复增加8例。所有最终代码、页面和导出改动后，全量 **1280通过、0失败、0跳过**（262.45秒），33项范围关联定向用例包含在内；另运行关联/住宿复核导出专项49通过。没有用早期测试结果替代最终回归。

验证入口：`.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider --basetemp ..\p10-linkage-final4`；Ruff、配置范围Mypy（91文件）、`tools/export_preview_contract.py` / `tools/validate_pack.py`、`git diff --check`、前端`npm.cmd test`和`npm.cmd run build -- --outDir ../../.local/p10-linkage/web`。前端8套脚本、类型与构建通过。Python仅保留两项已有依赖弃用警告；前端有已有SSR cssVars提示，无跳过失败测试。最终原始测试输出在私人 `final-all-tests.txt`。

## 部署、页面与恢复

使用同一 `scripts/product_preview.py serve --open`。最终部署代码 **7e90457ac914850f06926407a164693d47ddeb8d**，advisory-guide-1.6.1，前端`index-3jr4I9F7.js`，SHA256 `82fc514e1e3fc2a30f77c2d61dd56c4dc9fe0f95d373c85ec11078f34033321c`。最后服务PID27552，原工作库、SQLite16不变。运行库与静态文件核对记录保留在私人deployment.json；旧静态版本和一致性数据库快照仅用于受控核对/回滚，不恢复预算。

正常页面已显示原城市场景的整体背景、原条件、来源性质、2个组合线索和不向地点特色传播的限制。多日旧版依然为2天4项目，本轮无第二个场景模型调用。

本轮曾从正常入口建立一个空的独立测试旅行；它默认进入知识库模式，页面未提供已有非知识卡组合复用入口，因此未用它绕过正常流程。最终回到既有城市场景，通过原版本机制保存新建议；空测试旅行保留，没有活动、外部许可或派发。该日常复用可发现性问题不在本轮扩展修复。

页面验收：显式本地复核→预览→取消→再次预览→采用→下载新Markdown全部PASS。取消时草稿逐项等于旧采用版；采用后版本2，历史版本1与开工快照相同。原任务仍FAILED，新LOCAL_REVALIDATION接纳1单独展示。本轮没有填写AI建议或改写回复。

页面和导出旧提示曾将所有本地复核写成“空费用规范化”，已通用修正为原输入/保存回复的本地重新校验，不声称本次发生了不存在的规范化。初次导出保留，最终由正常页面另存新文件，没有编辑攻略内容。

恢复验收：最终版本正常停止/重启后，页面恢复2个活动、1条整体背景、1条AI取舍理由；独立进程以只读SQLite且socket/DNS禁用，逐项比较采用内容、来源作用范围、角色、条件和Markdown，与重启前快照/正常下载完全一致。刷新/状态/导出不派发模型或地图。私人证明包括cancel.json、pre-restart-final.json、recover.json及city-restored.png。

启动：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.\.venv\Scripts\python.exe scripts\product_preview.py serve --open
```

页面 `http://127.0.0.1:8768/`。如服务已在运行，不启动第二个实例；页面本机会话过期时正常重开入口，不复制Cookie或凭据。

## 调用与保护

本轮累计模型1/1；XHS connect/search/detail/browser、Amap、embedding、报价、连接测试和自动重试全为0。worker审计测得模型HTTP1、外部DNS1、TLS socket1，Amap0、blocked_external0。站点请求为项目级实测/账本/允许列表交叉核对，不代表监控用户整台电脑或其他浏览器标签；全系统流量和字节量NOT_MEASURED。

启动、预览/采用、重启恢复的4个本机serve进程审计均为model_http/amap_http/external_dns/external_socket/blocked_external=0；唯一worker的这些计数依次为1/0/1/1/0。新增continuation_operations恰为1个MODEL，预算已关闭，旧累计用量没有重置。

原37条Evidence、8张知识卡、旧来源/正文/审核、旧任务与预算操作逐行核对保持；6份私人旧导出哈希相同，C2状态原样。新增只有正常页面的许可、派发、收据和当前城市场景版本记录。原始失败保留，不修改历史采用版和导出。安全扫描不打印密钥，仅检查明确暂存文件和完整未推送提交范围。

## 内容改善和仍有缺口

改善是用户可以看到这一组为何可能适合其兴趣，以及如何按松紧取舍；不再只有名称和停留数字。它仍是单来源攻略整理的整体体验，不足以支持两个地点各自的独立特色、当前人流或城市核心范围。当前可提供有用的局部私人建议供用户评审，不能因此冻结或发布完整私人版。

现实交通、开放、价格与当前人流未核实；交通/时刻未知只需明确披露，不阻止建议展示。缺少逐地点看点及地域适配依据仍影响攻略质量；本轮不抓新文、不挪额度补齐。自然语言规则是保守有限检查，不声称证明任意理由的事实正确性。

真实新攻略仅由正常导出程序生成，留在`.local/p10-linkage/city-adopted-guide.md`，不提交真实内容。最终用户答复给出实际玩法与取舍，不以标签计数替代。

## Git 与停止

代码提交：

- `426ec5c244d355415ae906a3c19e6d7623bf71de`：投影/范围关联/卡片/契约/页面/回归。
- `756106ae49a6d748b27d1946fdbddd1ebd6fd424`：否定关系句误判与规则版本。
- `7e90457ac914850f06926407a164693d47ddeb8d`：本地复核的页面/导出一致说明。

本报告另行提交。代码累计diff为23文件、+1352/-110，另加本报告；完整最终diff及推送回执保存到私人git-sync.json，并在最终答复提供报告提交后的本地/远端完整SHA和GitHub commit/compare链接。扫描范围为整个基线至最终HEAD，非只检查最后文档提交。

原三份未跟踪T03报告不动，不合并master，不发布稳定版。实测额度已关闭，8768保留供用户查看，开发停止。
