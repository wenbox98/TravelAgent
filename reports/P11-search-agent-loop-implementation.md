# P11 搜索循环实施记录（持续更新）

2026-10-10。当前状态：代码回归通过，尚未完成真实两轮攻略验收。任务书为 [missionList/checkList](../docs/mission-search-agent-loop.md)。定时任务保持停用，根会话直接实施。

## 问题与实现

- 已核实的山西失败是第二篇真实回复HTTP200、完整结束后第11条topic非法；实际用量1搜索/2正文/5模型，没有耗尽原许可。`research/extractor.py`、`providers/llm.py`现在严格检查外层并逐条隔离不合法claim，合法条目继续独立审核；敏感信息仍阻断。`research/service.py`保留前面有效成果，选择不同正文，不重发失败请求。
- V5新许可在 `agent_contract.limits`、API/Pydantic/schema、持久预算、worker和UI贯通5搜索/20正文/模型null不限次数。`has_capacity`处理无上限的容量判断；旧许可的数值不变。实际次数仍逐次记录，重复指纹仍禁止。
- 回归发现并修复两项兼容缺陷：正文提取层和数据库旧12上限，新增迁移019；V5研究任务漏用`research-step-`标识，导致第二次查询触发唯一性冲突，已在`JobService.create`修复识别，活动子任务的唯一约束保留。
- `planning/search_strategy.py`与`agent.run/decision_payload`记录正面、侧面、目的缺口与真实反馈；按缺口重排搜索。新循环取消固定六轮退出，使用实际无进展/重复退出与局部建议生成。过早结束且尚缺研究视角时有可审计的目标守卫；没有开放浏览器或无限工具给模型。
- `advisory_coverage.assess/CoverageEvaluator`增加V5具体玩法覆盖，候选选择加入对应信号；路线地名不能替代具体体验支持。每轮根据实际结果重新判断，旧全局覆盖并非现实可行性。
- 页面新提交改用V5，显示不限模型次数、实际预算、正面/侧面查询与下一步；高级手动许可支持模型null，不再隐藏20次模型上界。旧任务继续显示原许可。

契约变更见 [V5架构说明](../docs/architecture/search-agent-v5.md)、`contracts/domain.schema.json`、`contracts/openapi.yaml`与迁移019。数据库原行、旧许可与采用版不得重写。

## 实际执行的验证

1. 首批结构隔离、提取和恢复回归：50项通过，合成网络序列，不访问外网。
2. 相关完整回归命令：`.venv/Scripts/python.exe -X utf8 -m pytest tests/integration/test_search_agent_loop.py tests/integration/test_database.py tests/integration/test_goal_agent.py tests/integration/test_goal_research_budget.py tests/integration/test_automatic_planning.py tests/unit/test_evidence_extractor.py tests/integration/test_extraction_recovery.py tests/contract -q --basetemp=.local/pytest-p11-combined-host-20261010-2200`；**179 passed**，123.52秒。包含真实生产worker与合成序列化HTTP200、非法兄弟隔离、整篇无效后读不同候选、敏感阻断、60模型计数、搜索6/正文21拒绝、超过六轮和二十模型后生成、验证码整轮停止，以及v18→v19父子行与外键保护。
3. `ruff check`相关代码和新增测试通过；标准`mypy --no-incremental`检查112源文件通过；`vue-tsc --noEmit`通过。
4. 网页`node --run test`全部通过；`node --run build`宿主构建成功，静态JS为`index-Cdz2k2sA.js`。沙箱首次构建因EPERM未执行成功，宿主重跑成功，无外部业务请求。
5. 中间回归失败如实保留：旧12正文批次拒绝、V5子任务标识漏识别导致第二查询唯一性冲突，均修复后通过。旧v18迁移测试改为显式target_version=18，并另加v19保护测试；没有把期望版本直接改成19来替代旧兼容测试。一次直接传入全部API目录的mypy扩大到不受严格检查的历史模块，产生219项范围错误；使用项目既定配置的标准命令通过，未改无关代码掩盖输出。

尚未完成：部署运行版本与旧数据独立对照、两轮真实普通页面攻略、预览取消/采用保存/导出、当前模式地图和刷新重启复核。任何离线数量都不替代这些验收。真实数据与安全诊断仅在`.local`保存，原三个T03未跟踪报告保留。
