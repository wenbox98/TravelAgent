# 知识卡与原引用去重补修

日期：2026-10-09。基线：`fd0f9c85f0e71857133d14d55eeca88be061d36b`。分支：`feature/g1-live-llm-validation`。

## 复现与边界

页面复核发现已选知识卡与原研究的相同内容分别显示。先用自编同源引用复现：期望1点，实际2点，测试FAIL。真实库只读核对确认知识卡指向原claim，同源、同位置、同条件、同角色；部分卡未单独保存source_version，但其受校验的原locator保留了版本前缀。

本轮小红书连接/搜索/详情/浏览器、模型、高德、embedding、报价请求均0。没有读取浏览器草稿、刷新原用户页面、代发送或应用未提交内容。没有改原数据库、知识卡、采用版、历史失败或账本。没有把内容点数量当新增来源或Coverage。

## 通用修改

| 文件/符号 | 规则 |
|---|---|
| research/reference_identity.py: groups、representative、aliases | 同source_id、来源版本、精确locator、主题、仅空白规范化正文、必要条件、作者角色、审核性质、时长范围及完整对象关系才分组。条件顺序保守保留；不删除标点或词语。版本缺失的已验证SOURCE_REFERENCE卡只可由原locator的`:chars:`前缀恢复版本；其他未知血缘不合并。 |
| planning/reference_overview.py: project、choices、export | 一组显示一份正文，citation_ids和bindings保留所有真实引用；路线依据亦合并相同摘录，未分配数量按完整绑定计算。旧单引用选择只有版本及该引用绑定仍准确一致才映射到当前组，来源改变仍失效；排除优先。 |
| planning/conversation.py: action | 撤回、排除、恢复清理同组旧别名选择，避免旧记录令恢复失效；只在正常用户动作下写选择，不批量迁移旧库。 |
| planning/private_payload.py: payload、assemble；questions.py: payload | 同一事实的一份有效别名即可承载兴趣；发送的选择只能引用本次实际通过过滤的必要条目。没有任何有效引用则本地阻止；不能用不同事实替代。完整绑定仍在选择记录中，原SourcePolicy、来源数及6000字限制保留。 |
| providers/llm.py: OpenAICompatibleProvider.structured；reference_identity.model_payload | 先对完整原输入做敏感数据检查，再只压缩传输表示；同一正文发送一次并提供reference_aliases。内部冻结输入和确定性事实校验仍保留全部ID，不改旧请求。不同来源的同文及不成立的别名提示不能被合并或传播。 |
| AutomaticPlanning.vue、planning-api.ts | 展示一份内容及其全部引用，不重复正文；不自动选择或发起更新。 |

契约补充为现有开放投影中的可选citation_ids、alias_options，以及内部模型传输的reference_aliases；不新增数据库迁移、模型输出schema或外部权限。来源对象关系和审核标准不放宽。去重不会增加旧余额；输入长度仍按原规则保守检查。

## 实际回归

修复中曾有3项专项失败：两个合成夹具分别只有路线、没有交通条目，与测试预设不一致；另一个测试发现实际HTTP序列化仍使用原payload。已纠正夹具选择和真正传输路径，未通过删除事实校验使其通过。

- 去重专项最终15 PASS，包含同源知识卡+原claim、10种差异/未知血缘不误合并、真实知识整理器与no_raw、实际Provider请求序列化、旧选择→撤回→重选→排除→恢复及非空进程恢复。
- 相关模型传输、选择、问答、知识库、建议攻略、Coverage和正文深度回归：158 PASS、2 warnings，111.27秒。最后的别名安全限制与模型传输再次专项：43 PASS、2 warnings，2.97秒。
- ruff PASS；mypy 103文件PASS。前端10组PASS，新增SSR断言同一摘录只渲染一次且两条引用都在；TypeScript和构建PASS。
- 先前基线完整1413项PASS记录保留；本次低影响补修没有机械重跑完整套件，也不把相关检查数量当作新的全量结果。

主要命令：`python -m pytest -q tests/integration/test_reference_deduplication.py`；相关回归同时覆盖test_llm_provider、test_research_depth、test_reference_selection、test_cached_questions_and_overview、test_knowledge_library、test_advisory_guide、test_advisory_context、test_planning_conversation、test_advisory_research_coverage。前端执行`npm test`及`npm run build`。文档检查执行`python tools/validate_pack.py`。

## 真实缓存与部署

只读新投影：底层11条引用全部保留；7个正文点合并为4个，7个引用绑定保留；2个来源。没有添加新玩法，仍是交通/时令参考。正常API仍返回6条直接Evidence引用，旧任务仍BLOCKED、选择0，不把修复写成旧任务成功。

另行在本机检查真实生产payload：内部5条、传输5条、别名组0。该当前知识输入本来没有重复，不能声称真实模型输入减少了；合成HTTP验收才明确验证2份同文压缩为1份并保留全部引用。没有派发真实模型请求。

同一8768部署核对：index、`index-CbarXorM.js`及`index-DkBUiq64.css`与构建/运行目录/实际HTTP返回逐字节一致。只在活跃任务0时正常重启本项目服务，保留旧哈希资源，未打开或刷新原用户页面。原61张表逐表一致，业务调用审计差值为空，健康接口200；启动构造自检ready=true、browser_sessions=0。独立本地HTTP客户端启用外网拒绝，external_calls=0。

最终运行PID12548；正常API再次确认4点、6条直接引用、原BLOCKED状态、选择0。文档契约检查12/12 PASS，273个Markdown相对链接有效。所有统计均为本批实际核对，不把真实历史请求算成本批新调用。

没有全系统抓包；其他应用网络为NOT_MEASURED。真实新攻略质量、真实模型规划质量、站点访问减少比例均未验收，G1不变。

## 使用与收尾

地址：`http://127.0.0.1:8768/`。页面保持运行。用户未发送草稿继续留在原浏览器；本批不替用户刷新。需要重新启动时：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

只显式暂存补修代码、合成测试、契约说明和报告，保留原三份未跟踪T03报告。提交前及完整未推送范围扫描配置秘密、真实正文、凭据、数据库、profile和敏感运行产物；功能分支提交推送，不强推、不合并master。完整提交和远端SHA在最终交接给出。

`git diff --cached --stat`：14 files changed, 514 insertions(+), 42 deletions(-)；包括去重生产逻辑、模型传输、选择一致性、页面、合成回归及文档报告，无真实业务数据变更。暂存区安全扫描14个文件，未发现秘密、真实正文或禁止产物。
