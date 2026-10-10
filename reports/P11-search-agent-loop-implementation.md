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

部署已完成：运行提交3c7afcff6e6195ed3c5fb07e7f02bd82c11c9c18、Python PID25380/启动器21540，健康检查200、HTML引用index-Cdz2k2sA.js，schema19、quick_check=ok、foreign_key_check=0。私有备份与代码/静态哈希清单在`.local/root-p11-review`。部署后对照：原8797行缺失0、修改0，新增schema_version行1；原三个T03哈希不变；445个旧审计文件不变，ui-requests-15416.json随旧进程运行正常增长，单独保留差异，不宣称全体审计哈希不变。

真实A已从普通页面新建独立旅行，原话为湖北区域7天、飞机抵达后租车自驾、比较武汉/宜昌/恩施、具体玩法/顺序/住宿片区/衔接，日期人数预算暂未知。页面一次提交已推进至模型理解、正面搜索与新正文读取。尚未完成：两轮真实普通页面攻略、预览取消/采用保存/导出、当前模式地图和刷新重启复核。任何离线数量都不替代这些验收。真实数据与安全诊断仅在`.local`保存，原三个T03未跟踪报告保留。

真实A执行中刷新发现新故障：另一标签页轮询山西旧旅行会覆盖共享localStorage的ta-current-trip，使湖北页面刷新后显示山西，看起来像任务停止；数据库证明湖北仍是原任务/原许可运行。新增`current-trip.ts`按标签页sessionStorage恢复，localStorage仅作为新标签页的初始选择；PlanningPanel读写统一使用它。双标签页轮询/刷新、新标签页和存储拒绝的功能回归通过，网页全部测试与构建通过（index-eXhr7V7k.js）。只热更新静态资源，不中断正在执行的真实研究；修复后真实刷新复核仍待执行。

## 真实A发现的第二个阻断：缓存卡版本合并

本轮真实A未通过：新查1次、正文4篇、模型10次、地图0次。正文提取均HTTP200正常结束；独立审核产生8条新有效信息，但研究整理同时升级一张旧缓存路线卡的活动拆分，合并使用旧绑定失败，父任务BLOCKED（KNOWLEDGE_STALE_OR_DELETED），尚未生成攻略。不能把子任务完成或离线测试通过称为攻略通过。

修改automatic.merge_research：新研究有效卡和仅entities/activities发生变化的相同事实卡可重绑未锁定草稿；原文本、条件、来源、权利、审核及原绑定hash均需相同，最新卡仍经Library验证。锁定、撤回、删除、无关语义变化仍拒绝。严格Library.get未放宽，采用版不改。增加显式合并修复续做：先本地合并已完成子任务，再创建只含原剩余额度的后继许可，保留旧失败/旧操作和原到期时间，不自动重试网络、不重读4篇，不把继承研究计作新正文。新连接因旧浏览器已关闭按一次实际记账。恢复正面查询历史以便下一步侧面补缺，并阻止同查询重复。页面区分程序版本衔接错误与用户改条件。

验证：修复边界与既有研究/规划相关59项离线回归通过（129.79秒，新增兼容分支后的定向回归另记）；真实数据库副本复现旧STALE，再新合并12活动/7有效卡，原grant原样、外部请求0、真实库未写入。mypy112文件、ruff、全部网页测试和66模块构建通过。Windows受限临时目录WinError5由本机独立新测试目录解决，没有清理/删除旧数据。刷新实际返回湖北A且任务ID/用量未重复，完整重启恢复尚未验。

下一步：部署当前修复，用页面“合并已读资料并继续”执行剩余范围4/16的A续做；完成有效攻略及保存导出后再进行B全流程。A或B失败必须继续修复或明确外部阻断，不以本报告代替两轮验收。

最终定向回归：7项全部通过，包含缓存活动拆分兼容、未锁定重绑、锁定/删除/无关变化拒绝、显式续做幂等、原grant/操作原样与有限地图余量继承。

## 真实A第三个阻断：底层读取器仍为旧3/6

0c711b8部署并从普通页面显式续做，旧grant/20条操作逐字段不变，新许可仅剩余4搜索/16正文及原到期时间。实际进入侧面住宿/接驳查询，再进入正面游玩时长查询。累计3搜索/11正文/20模型时再次PARTIAL，RESEARCH_BUDGET_EXHAUSTED，未生成或采用。新许可实际仅用搜索2/正文7，尚剩2/9，不能解释成正常额度耗尽。

根因：LiveBrowserBackend.search/detail硬编码3/6；LiveNetworkObserver窗口白名单同样只支持到3/6。业务层与合成MultiReader测试覆盖了5/20，却没有覆盖真实后端的扩大边界，是本轮验证遗漏。修复worker→LiveResearchReader→LiveBrowserBackend逐层传入当前许可，旧许可仍保持原范围，观测白名单支持到5/20。没有增加无限采集或自动重试。显式恢复仅对严格匹配历史硬上限诊断、仍有剩余额度且已产生审核成果的故障开放；访问拒绝/登录/验证/模型失败继续阻断。保留第7篇被拒绝的已记账读取，不返还或重置用量。

已执行离线验证：test_live_page、test_live_observability和原合并回归146项通过17.17秒；新增硬上限恢复/访问拒绝边界后test_research_merge_recovery11项通过26.81秒；test_research_live_adapter52项通过0.28秒。包含真实后端合成页面第5搜索/第20正文实际调用、6/21访问前拒绝、完整观测窗口、5/20与续做2/9参数贯穿、旧范围3/6保持。标准mypy112文件、ruff和66模块网页构建通过。真实A和B仍未完成，不能据这些离线结果宣称通过。
