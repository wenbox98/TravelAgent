# P11 搜索循环实施记录（持续更新）

2026-10-10。当前状态：代码回归通过，尚未完成真实两轮攻略验收。任务书为 [missionList/checkList](../docs/mission-search-agent-loop.md)。定时任务保持停用，根会话直接实施。

## 问题与实现

- 2026-10-11新真实A生成仅用已审核资料，实际来源0、模型3，HTTP200/67.58秒、接纳2方案，说明d690255范围修复已真实生效。根会话实看首案仍有大坝路线候选、住宿镇被排两小时游玩和旧本地复核标签，已取消预览，revision51、采用v1哈希不变；不能算完整攻略PASS。
- 本批修复：`activity_content.preceding_subject/heading_subject`区分动作前缀与精确地名；`knowledge.planning.templates`保留旧动态模板索引再追加新主语，`automatic.material_pool`仅在同卡、未锁定且新主体有审核玩法时去重旧动作名前缀。生产只读快照曾暴露KNOWLEDGE_BINDING_CHANGED，现已保留旧模板修正，预检大坝正确为CONTENT_REFERENCE；不改卡hash、原文、旧采用版。`advisory-guide-1.12`强调玩法同名候选优先、住宿基点不得凑成定时游玩及返程只是AI可选建议。
- `guide_revalidation.view/check_adoption`与`guide_view.project/export`绑定当前作业/草稿身份：新模型预览不继承旧复核标签，取消恢复原标签；导出始终展示采用版自身性质，新正常采用清除旧复核标记。原作业历史保留；内部state标记增加draft_hash，domain/OpenAPI/SQL无变更。
- 实际验证：四组相关合成回归94项通过93.17秒；新增同卡去重/锁定两例2项通过0.38秒（独立新增，不重复计入94）。Ruff通过、mypy112文件通过。首轮沙盒临时目录WinError5；主机测试先50通过1失败（预览影响旧导出，补修），再80通过1失败（测试误读未公开adopted_version，改读持久状态），最终全部通过。全为离线合成和只读生产预检，无新外部请求；真实新规划与A后段验收仍待执行。

- 2026-10-11真实普通页面又发现权限收窄缺陷：请求明确“仅用当前已经审核通过的资料……不再搜索、不读取新正文”，模型理解正确，但`cache_only_requested`旧正则只识别“不再搜索或读取新正文”，未覆盖顿号和重复否定；新许可错误保留5/20，程序目标守卫将GENERATE改派RESEARCH_GAP。根会话发现后立即页面停止；实际新增CONNECT1/SEARCH1/MODEL2，DETAIL0，采用版未改，A累计7/21/65，错误账本不删除。修复识别普通已审核资料指令及重复否定，在`agent.tools`再阻止来源调用，受限时改为已有资料生成并说明缺口；不依赖模型自觉遵守。此项是实测FAIL及修复，不冒充成功，后续须部署并真实验证零来源流程。
- 权限修复验证：`test_goal_agent.py / test_cached_material_permission.py / test_cached_body_reprocess.py`最终85项通过70.11秒，覆盖实际重复否定写法、假设/引用不当授权、零来源许可、监督模型选GENERATE或错误RESEARCH_GAP均完成缓存生成且来源调用0。Ruff通过，标准mypy112文件通过。编写时静态检查发现局部导入不可用于run作用域，已移到模块导入并重新验证；前次83项运行也通过，最终增加两种错误研究决策回归后85项。全为合成离线，不代表真实新答复已完成。

- 2026-10-11补充：A最新缓存分析实际读取977/584字两篇（预检751字材料未在该作业读取），新增15条独立审核信息，但主语投影漏掉带时间与定位图标的前提、自然保护区后缀；“索道上山”还被误当作竞争游玩主体。`activity_content.preceding_subject/reviewed_subject_names/content_references`修复精确主语衔接并排除既有通用交通占位；`lodging.researched_areas`补“继续住”，显式要求审核通过，拒绝否定/假设。原知识卡身份、hash及审核保持；不改写原文、不采用来源时钟、不添加外部事实。`advisory-guide-1.11`标记新解释版本。只读生产预检可见2项新增具体玩法及木鱼镇住宿；真实A规划仍待完成，现存方案CONTENT_FAIL。
- 本批验证：四个相关合成文件最终103项通过（21.50秒），Ruff及配置范围mypy112文件通过；此前受限临时目录WinError5，正常本机测试先因新夹具缺evidence_links/合法card_id及旧夹具未标review_status出现7失败、再2失败，修正夹具后通过，未放宽审核门槛。补通用交通回归后重新103项通过。无新搜索/正文/模型/地图请求。实际差异约7文件，包含实现、回归、任务书和本报告，最终以提交差异为准。
- B当前已在普通页面本地复核保留的真实回复，预览、取消保持v2，再预览并采用v3（revision34，3天7项目），原生浏览器下载31,588字节；实际文件与生产采用版导出SHA256一致。该操作是显式本地复核，不是真实模型重新回答。旧古德寺公交段仅为一般历史参考，不能证明移除古德寺后的当前路段已核实；B最终恢复与适用性检查仍保留缺口。私有证据保存在.local/root-p11-review，不提交正文或导出全文。

- 首页恢复真实暴露历史研究扫描重复校验导致15秒超时。`preview.api.index`接入原`view_cache`，不放宽逐条证据校验，不跨请求缓存。相同数据库只读入口测量13.368→5.110秒（42研究、37有合格资料）；新增真实API合成测试覆盖同请求共享、跨请求重新加载和删除失效，16项通过2.72秒、Ruff通过，无业务网络请求。16196d6地图修复已推送部署，A/B重启前后采用hash/条件/账本一致；最终内容与下载继续，不能宣布完成。

- 2026-10-11真实B采用v2保存成功，8项具体引用且东湖只步行、返程弹性留白。有限地图实际消耗2地点/1公交路径，返回一般参考约35分钟；古德寺候选显示暂停开放，待调整。关键地图前端沿用15秒等待，后台成功后页面仍报超时：`CriticalMap.act`改为有限120秒并发出pending，`PlanningPanel.mapPending`阻止轮询与冲突操作且使旧读取失效；确认只在实际草稿/选段改变时撤回。`flow_api.key_leg`用请求内校验复用，数据库变化继续使复用失效。新增`tests/critical-map.mjs`实际执行组件watch和异步pending交互，全部网页测试通过；地图/缓存19项合成回归通过8.90秒，Ruff通过，构建通过（首次沙盒WinError5/EPERM均保留，主机隔离环境重跑）。真实地图没有自动重发；下载、A内容与两轮整体验收仍未完成。

- 最新真实A零来源生成消耗3次模型，HTTP200返回两个合法七天方案，却被“不是报价或已核实票价”的并列否定误拒。`arrangements._check`只剥离精确否定宾语，`advisory.VERSION`升至1.9；相同句内肯定核实、保证、价格数字和旅程分钟数仍拦截。新增3组预算条件回归，攻略与覆盖82项通过/34.35秒，Ruff通过；初次误指定不存在的测试文件无测试执行，随后用实际文件重跑。原真实回复只读本地重验接纳2，不是模型重新作答；当前仅3个活动有具体玩法引用，住宿仍单片区，A内容未验收。累计6搜索/21正文尝试/56模型含已记录错误超范围采集，账本不修改。B尚未运行。

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

## 真实A局部生成未达到内容目标及修复

8980d85已部署，PID38712、静态index-jOHaArM1.js。原授权和操作不变，显式合并后只增加理解/监督/生成3次模型，没有再查站点。14:30UTC生成一个局部建议，活动仅覆盖前4天，第5、6天为GAP，住宿UNDECIDED且没有片区。累计3搜索/11正文/23模型，仍有2搜索/9正文。此次内容验收FAIL，不是第一轮攻略通过，也不能把局部生成等于核心完成。

修改符号：agent.decision_payload/run/tools、search_strategy.context/proposal_gaps、automatic.material_pool/card_context/_partial_recovery、lodging.researched_areas、advisory.payload/validate、guide_view.project/export、preview.service.view_cache/_cache/_load_cache、PlanningService.get、PlanningPanel、AdvisoryGuide及网页类型。未改模型输出字段契约；住宿片区复用已有area_ids，增加来源投影。

完成判断现在检查实际缺口；未覆盖的命名项目进入不同查询建议。生成后的缺失天数、只有名称的玩法和多日住宿片区不足会反馈下一轮，而非只凭结构合法结束。两步无进展仍允许最后一次局部整理并明确停止；不重发失败HTTP。候选池保留锁定项目，分散不同来源的命名玩法，通用换乘/抵达步骤不挤占名额。住宿片区来自当前已审核正文的逐字地点短语，保留历史角色和条件；否定/通用地点排除，使用片区须带对应引用，排除或撤回的引用不能继续呈现。未知晚数、房间数、是否纳入费用不阻止暂定片区比较，不转成预订确认或已知价格。

局部结果显式续做继承原剩余范围和原到期时间。真实数据库副本验证仍为2/9、MODEL=null、原地图余量保留，旧所有grant/操作原样，网络0；真实库未写入。普通页面只在同次读取内复用已检查的资料，写入计数/其他连接data_version变化失效，新请求重新校验。实际A页面本机分析9.846秒→2.619秒，重复底层加载18次→3次；只读状态超时5秒→15秒。

实际验证：最后针对性5文件80项通过154.89秒，最终展示/导出和天数覆盖70项通过27.52秒（有重叠，不相加冒充独立数量）；mypy112文件、ruff、全部网页测试及66模块构建通过，最终静态index-CQbSTY3r.js。首次测试沙盒临时目录WinError5未运行；第一次新增缓存测试的代码插入位置错误导致NameError，修正测试后15项通过，再纳入80项与最终回归。一次网页类型检查发现新增来源字段未声明，补齐planning-api类型后构建通过。合成测试均禁止网络。

下一步部署本批并从A普通页面继续原2/9，核对实际攻略内容、预览/取消/采用/导出；再做B武汉3天公交步行真实完整流程。完整交付仍未通过，任务书所有真实验收项保留未勾选，定时任务保持停用。

### 完成判断修复的真实部署与续做

d8669cc2b2f29a34b1727be8af9da5627e31eda9已推送，远端完整SHA一致。空闲时重启8768服务，运行PID31876/启动器22508，静态index-CQbSTY3r.js。A普通页面刷新仍恢复湖北7天、飞机到达、自驾租车和旧局部建议；随后仅点击一次“继续补充研究”，新许可严格沿用原剩余2搜索/9正文、MODEL=null与原到期时间，不修改旧许可和操作。真实第5轮已改为聚焦命名景点的玩法/时长补缺，并读取、独立审核新的不同正文。执行中，尚未生成新的合格攻略，不计为A通过；B仍未执行。私有部署哈希和阶段证据位于`.local/root-p11-review/deployed-d8669cc.json`和`A-completion-repair-started.json`，恢复文件同步当前状态。

上述正文累计数字为许可账本的DETAIL尝试计数，包含此前底层硬上限拒绝但已记账的尝试；不应将其全部表述为成功获得的完整正文篇数。

## 真实A第四次内容失败：玩法误审与主体关联

实际第7轮生成7天局部建议，累计5搜索/20正文尝试/44模型/地图0；搜索和正文余量0。8个选中项目全部ROUTE_CONTEXT，虽然有住宿片区和逐日分配，仍是内容FAIL，未采用。独立读取本轮新鲜正文和实际审核结果发现：模型把EXPERIENCE主题错误理解为必须作者亲历，即使reference_scope=GUIDE_SUGGESTION也以ROLE_MISMATCH拒绝；混合价格/玩法长句另被严格重要事实守卫整体拒绝。

本批修改references.catalog/materialize/validate_reference：新增v2精确短句目录，保留v1原目录完整重建；独立审核读取全父段/相邻句，不删除票价或否定。ReferenceSelection契约显式允许版本/提示成对v1、v2。提取配方reference-selection-v2.0；旧手动历史授权保留v1。llm审核提示明确EXPERIENCE为主题，攻略建议无需声称亲历，个人经历、当前票价/开放/交通事实规则保留。上下文投影只使用已审核、原文精确定位、同父段的主体前提，长度匹配不唯一则拒绝关联；同日标题/路线列表不变成某个景点的特色。PreviewEvidence增加可选clause_context；知识卡保留其来源绑定，旧v1卡不补写。

缓存分析匹配实际PLAY_DETAIL缺口，最多两篇，在当前旅行绑定内优先相关且有具体玩法的正文；不追加搜索、不读新正文、不重置原5/20账本、不重试失败HTTP。整篇条目全部隔离时不再启动空候选审核，保留其他正文成果。候选池在锁定项后优先保留有具体玩法引用的同名活动；住宿地点去掉建议前缀并支持镇/村。

合成验证实际结果：首轮98通过/2失败（新增测试构造重复参数错误、旧测试将单条非法误当整篇结构失败）；随后分开覆盖外层失败与非法条目隔离。扩展回归112通过/1失败，为简化测试卡缺card_id，补齐真实绑定字段后搜索循环11通过101.90秒。最终同段主体/旧v1/契约/住宿42通过4.79秒，审核/去重/候选47通过2.82秒，缓存35通过65.65秒（有重叠，不相加冒充独立数量）。ruff与标准mypy112文件通过。首次沙箱临时目录WinError5，改主机独立目录；一次扩大mypy范围产生历史219项，标准配置通过。真实内容尚未复验，不把这些合成结果当A/B通过。只读数据库副本预检选择本轮新鲜919/941字符两个快照，外部请求0，未涉及此前被拒绝外发的旧特定正文。

22ffc10e92e86e6a8bb24a8733d5247186933298已提交推送，远端完整SHA一致。空闲时备份数据库并重启，当前PID32800/启动器35756，schema19、quick_check=ok、foreign_key_check=0，静态index-CQbSTY3r.js。普通A页面一次发送明确缓存分析请求，旅行条件未改，已进入缓存提取与独立审核；新许可全部站点/地图范围0、模型null。此时A仍未通过，B未运行，采用和导出仍待实际验证。

### 缓存真实复验仍不足：玩法主体误作路线依赖

两篇缓存实际新增8条，经新理解/提取/独立审核/监督/生成共7模型，累计51模型，站点/地图未增加。生成两个七天建议仍缺具体玩法，A未通过。只读数据库副本定位11条实际被保存层拒绝，均ROUTE_ASSOCIATION_WITHOUT_ACCEPTED_ROUTE；此错误被上层统一投影为DEPENDENCY_UNRESOLVED。模型给玩法指定当天标题/主体，程序却将任何object_span_id变为route_association，要求另有相同对象的ROUTE。

context_review.check_decision规则6：独立审核的非路线主题、不同主体锚点仅作为精确条件保留；真实ROUTE/DURATION/TRANSPORT、自指对象和旧审核版本1保持原路线依赖，不放宽价格/开放/交通事实。已有review_replay只对已保存REFERENCE提议运行新规则，原拒绝/待确认决定不升级，旧审核、候选、批次、许可、操作均不改。两份本轮新鲜审核回复在数据库副本复核新增5+4条，来源和模型请求0；不是模型重新回答，不涉及此前禁止外发的旧特定正文。

实际验证：首轮64通过/2失败；保留自指对象历史依赖后65通过/1失败，剩余为API返回可选clause_context默认值而直接字典未带默认值的比较差异。曾误判为测试日期差异，尝试统一时钟无效，已撤回；按相同PreviewView API契约投影比较持久读取，102项通过6.07秒。包含新四种主题的保存、真实路线孤儿拒绝、复核幂等及旧记录逐字段不变。ruff、标准mypy112文件通过；沙盒临时目录WinError5，使用主机独立目录，没有删除旧数据。部署后仍须核对实际内容、预览取消采用、导出，B未运行。

候选投影继续修复：references.clause_context只投影statement之前同父段的精确已审核条件，原完整conditions仍保留；activity_content.reviewed_subject_names/materials.activities从前置主体生成明确地点候选，禁止日标题/假设/否定/其他段关联；candidate_from_name保留原名或已审前置主体的完整绑定。玩法/取舍原主体保存修复本身不会自动生成地点，数据库副本先证明此层缺失，再验证三峡人家、三游洞、三峡大坝进入候选。automatic.material_pool改为先完成当前具体内容优先级内部的来源分散，再处理仅路线名称，避免第一轮来源分散先占满12项。

已执行相关62项回归3.62秒，候选池3项0.35秒；第一次指定不存在的测试路径，未执行，随后核对路径执行。新回归要求同段后续地点仍在完整条件中但不成为玩法主体，日标题、假设、否定不生成候选，同源第二条玩法不被路线名称挤掉。只有本地修复和副本验证，真实A/B验收尚未通过。


### 玩法主体进入规划候选修复回归

短句目录v2揭露了旧合成输入只选择第一短句的问题：住宿的好处与限制、同段第二个玩法都未被测试模型选择。修正合成模型为显式选择完整条件与两个独立玩法，未降低生产审核门槛。第一次组合回归55通过1失败（后续选不同玩法的旧fixture已无未选玩法）；修正后研究深度18项通过。此前同组合中的契约、引用选择、候选优先级、agent loop全部通过；Ruff通过，配置mypy112文件通过。当前服务为部署停机状态，A仍CONTENT_FAIL，B未开始；这些合成结果不等于真实攻略通过。


### 只用缓存仍触发搜索的真实失败与修复

普通页面明确要求不再搜索或读取新正文，理解模型正确，但缓存限制解析仅识别固定短语，目标守卫覆盖GENERATE。立即从页面取消；记录新增CONNECT1/SEARCH1/DETAIL1/MODEL2，原账本不修改。没有把该次操作当成合规通过。授权前支持普通联合禁令，并以V5合成真实worker证明读源次数0；假设与引语不当成限制指令。89项合成回归19.60秒通过，Ruff与mypy112文件通过。缓存投影改为一次解码，完整审核、引用、写入失效规则保留；诊断读取耗时由16.28秒降至10.40秒（cProfile条件，状态已取消有变化，不作为精确同状态性能基准）。空闲备份before-cache-scope-fix.sqlite3，当前停机部署；A及B仍未验收。


### 页面慢读取覆盖预览与采用版本

普通页面预览A后首次采用报STALE_REVISION，DB仍保留revision34合法预览；刷新读取后再次采用，DB确认revision35、采用v1、预览标记清除。页面PlanningPanel.poll在busy期间仍发读取，晚返回可覆盖已保存的新revision；apply未拒绝较旧版本。新增plan-snapshot.acceptsPlanSnapshot并用于apply，busy期间不启动轮询。同版本进度和不同旅行切换仍允许。新增延迟读取竞态回归，全部npm test通过；npm run build首次沙盒spawn EPERM，按主机权限重跑通过，静态index-BTS0vzsF.js。后台B真实任务仍正常运行，不重启。无新业务请求；私有DB/旧采用/账本/T03未修改。A本地复核采用只证明保存链路，仍缺玩法与住宿；B真实内容未验收。前批否定报价修复的mypy112文件实际通过。


### 采用版原生文件下载

实际页面Blob导出提示成功，但两次受支持下载事件均未确认文件，不能判为下载成功；内部下载页被浏览器策略禁止，未绕过。新增flow_api.download_guide，通过原export_guide生成相同Markdown并返回UTF-8附件；原JSON出口保留，普通页面使用原生同源下载链接，取消点击即成功提示。OpenAPI与攻略契约同步新增路径；不改变domain或SQLite。合成接口验证文件字节与JSON完全相同、采用版未改、认证401、外源403、no-store；test_advisory_guide.py 30项通过16.20秒，Ruff、mypy112、全网页测试与构建通过。初次混合验证命令工作目录误设为apps/web，Python/Ruff未执行；随后在正确仓库目录实际补齐。静态index-DydIdkRa.js已构建但未部署；B仍在研究，不重启。A采用v1仍内容不足，下载文件验收待部署后执行。

### 正文兴趣保存等待超时与资料重复解析

A普通页面点击一次正文兴趣，15秒后显示本机等待超时，未重复提交。随后DB会话版本22→23、页面出现撤回兴趣，证明原选择最终保存；草稿/采用版哈希和操作账本不变。不能把超时误认为后台任务停止，也不能接受这种等待为正常体验。B同期间正常推进到5搜索/17正文尝试/30模型，未中断它部署。

修改preview.service.cached_view/_cache/_load_cache、planning.materials.references/_references、research.reporting.build_directions/_statement、quality.confidence_level、content_store.audit_grounding：同一请求复用已投影引用并返回独立副本；SQLite本连接total_changes或外连接data_version变化失效，另一个请求重做完整校验；报告只解码已验证DomainModel一次。逐条原文/审核/权限检查保留，但不再为每条已验证原始claim重新验证相同包外壳。无契约或数据库变化。

实际验证：cached_overview、planning_conversation、research_depth、advisory_guide共71项通过20.82秒，含读取复用、返回值隔离、写入过期、外连接权限撤回、逐字引用与选择保存；Ruff通过，mypy112文件通过。直接基线包与当前包对同一A状态使用与HTTP相同只读快照，耗时6.899秒→2.766秒，revision35一致；原始对比留在.local/root-p11-review/read-performance-comparison.json。早期未使用快照的分析受B外连接写入影响导致缓存多次失效，23秒不作为可比基准。首个基线临时包因PROJECT_ROOT相对位置失败，显式绑定同一仓库后成功；没有业务网络调用。当前仍未部署；与351a471下载修改一起等待B空闲后部署。A和B完整内容验收仍未通过。

### B完整研究后的内容链路失败与修复

B普通页面一次提交正常结束PARTIAL：CONNECT1/SEARCH5/DETAIL20/MODEL34/MAP0，真实6轮包括2个侧面查询、3个正面查询、一次生成。第1轮正文独立审核无接纳，保留NEEDS_REVIEW；其余审核保留信息，没有HTTP失败重发或人工登录挑战。HTTP200生成接纳2份三天方案，但仅1项具体引用、住宿未形成片区，内容FAIL。原始诊断与完整保存结果位于忽略目录B-first-result.json，不提交正文。

修改activity_content.heading_subject/reviewed_subject_names/reviewed_clause_subject/content_references、lodging.researched_areas、knowledge.planning.templates、Library.for_evidence、automatic._refresh_scoped_knowledge/card_context/merge_research。编号、勾号、竖线标题与已审同段前主体支持精确地点；标题负面/假设/路线及跨文档限制保留。知识卡自身已审内容可按完全相同citation绑定；其他条目仍要求同source/version/document。旧卡只追加精确主体模板，不改旧身份、哈希或已有索引。按本次证据精确查询卡，取消将知识库浏览前60条误作研究池；已有草稿只在显式V5继续意图重投影，锁和采用版保持。住宿支持已审标题下的明确片区列表和完整“一带”，不推断商家或当前运营。

只读实际数据核对：B候选12项都有具体引用，住宿江汉路步行街/黄鹤楼周边/江汉路；A候选4项具体引用、宜昌住宿带与恩施市区。无新业务请求、DB写入或模型回答，不能算真实复验。初次回归发现合成card_id格式、来源标题遗漏与伪造claim_id不满足真实证明链，修正fixture；一次误指定不存在测试文件未执行。验收继续由普通页面零新增搜索/正文生成、预览取消采用下载与恢复完成，仍保留A/B内容FAIL。

执行content_pipeline、guide_lodging_revalidation、scoped_context、knowledge_library、search_agent_loop、automatic_planning组合：146通过，1个新增测试错误地漏计原有合法卡而失败（76.54秒）；修正断言为完整集合后该项实际通过0.89秒。未降验证规则。Ruff通过、mypy112文件通过。改动8个实现/测试文件268行新增18行删除，另同步任务书和本报告；未改外部契约或SQLite结构。业务外部请求0，后续仅Git功能分支同步。

### 缓存资料刷新后授权快照不一致

8bb9d91已部署，PID8756/启动器29672、静态index-DydIdkRa.js、schema19。B普通页面仅缓存生成实际在GENERATE阶段BLOCKED，原因为PLANNING_UNAVAILABLE；新增2次模型用于理解与监督，规划模型未派发，新增搜索/正文/地图0，累计5/20/36。独立只读核对payload合法，但含46个新知识绑定，grant冻结于刷新之前，DailyBudget.check_payload正确拒绝超快照资料。不是模型预算耗尽，不重试原失败任务。

automatic._bind_cached_knowledge在明确V5缓存选择后同步当前运行任务的资料绑定。验证同scope/session/task/generation及有效未关闭许可；仅允许原卡、本次附属已审核证据、原卡同源背景或当前明确发现的本地候选。Library与verify继续验证原文、权限、哈希、撤回、版本。更新仅knowledge_bindings，原limits、过期时间、已用账本和旧许可完全不改，不更改DailyBudget.check_payload守卫。无数据库或外部契约变化。

新增test_cached_material_permission使用真实生产资料整理、普通对话、新许可、worker和合成HTTP回包串联，验证旧快照确实拒绝、显式刷新后生成可选方案、来源调用0、旧许可逐字段不变，以及关闭/错scope/错generation拒绝。专项5通过9.64秒；随后与search_agent_loop、automatic_planning、knowledge_library、cached_body_reprocess合计101通过141.73秒。首次沙盒临时目录WinError5，改为主机独立禁网测试目录；Ruff通过、mypy112文件通过，git diff --check通过。部署前已确认活动任务/子任务均0并备份当前数据库，quick_check=ok、外键异常0。真实B重新生成待验，A/B仍未完整通过。

A原生下载实际文件28,090字节；独立以保存的采用版重新导出，SHA256均0ea94ee3ef1bb7d3e9500dd04333f6c1daf298942a72fc0bd3610ab695e5f95f。下载文件内容一致，不代表内容质量通过；原始文件与私有证明留本机，不提交Git。

### B真实生成、采用与提交等待修复

debefb2部署后，普通页面一次明确缓存生成：理解、监督、规划3次真实模型，新增站点/地图0，B累计搜索5/正文20尝试/模型39。生成1份合法三天9项方案，每项有CONTENT_REFERENCE，住宿江汉路与黄鹤楼周边，东湖只安排一次。页面预览后取消，DB确认原12项草稿恢复、采用为空、账本不变；再采用后revision19、采用v1、draft/adopted哈希一致，AIR/PUBLIC_TRANSIT/NO/NO保留。私有证据B-reviewed-generation-result.json、B-after-preview-cancel.json、B-adopted-nine-verified.json。不算完整通过：东湖源引用仍建议骑行，本次要求步行；第三天下午返程余量、地图、原生下载、重启恢复仍待核对，A内容仍FAIL。

本次提交前端15秒等待超时，后台随后接收并完成，未再次发送。定位planning.conversation._action启动V5提交前先运行整页plans.get但结果无用；移到V5早返回之后。preview.service._load_cache同请求复用来源包与内容快照，沿用total_changes/data_version失效；content_store.audit_grounding只复用由实际原文/DOM/完整度/内容身份和引用版本组成的目录，各条定位、上下文、manifest、哈希仍逐条核对。原文或绑定或statement范围篡改仍拒绝。advisory_coverage.assess在V5具体内容覆盖时复用researched_areas的精确已审住宿标题关联，过滤冲突；旧coverage行为保持。无外部契约或数据库变更。

0640170已推送且完整远端SHA核对一致；部署前活动任务0、备份before-read-coverage.sqlite3、完整性ok/外键0，运行PID36784/启动器24584，静态DydIdkRa。普通页面重启恢复B采用v1与AIR/PUBLIC_TRANSIT/NO/NO，A采用v1/AIR/SELF_DRIVE/YES/YES均精确不变。B新自由修订一次接收并完成SUFFICIENT，3新真实模型，搜索/正文/地图0；累计5/20/42。8项具体内容、三天分配和住宿引用完整，东湖仅步行、楚河汉街备选、第三天下午返程余量写入建议，未覆盖旧采用。原文“骑行”仍被AdvisoryGuide和Markdown无标签重复作主说明，容易与本次选择混淆；删除已有content_references时的重复highlight，本次assumptions在活动之前展开，原文和完整条件仍保留在清晰标记的来源参考内。无业务数据或契约变化，没有新模型重发。

本次呈现修复：advisory_guide/content_pipeline共54通过17.55秒，Ruff通过；全部npm test通过，新增SSR证明“本次只步行”在项目之前且骑行原文只出现于来源标签。npm run build初次沙盒spawn EPERM，主机重跑通过，产物index-BxQxkswY.js/index-BX5EKmRk.css。B预览、下一版采用下载、地图与A内容仍接续，不宣称任务完成。

执行cached_overview/reference_selection/private_source_content/planning_conversation/goal_agent/cached_material_permission合成回归112通过23.28秒；mypy112文件、Ruff通过。新住宿覆盖与读取/引用57通过3.58秒（重叠，不累计成独立总数），Ruff通过。首次沙盒临时目录WinError5导致fixture与清理错误，主机独立临时目录运行通过。只读cProfile B读取7.376秒→4.516秒，前后会话状态有变化，不作为同状态精确性能基准。原本页超时与改后普通提交效果仍须真实复验。本批不发新的业务请求，后续Git同步、空闲备份部署和B内容修订接续。
# 2026-10-11：备选比较误拒修复（尚未完成两轮验收）

武汉真实修订要求将开放未确认的地点移出必去，仅作备选。模型HTTP200、结构有效，返回7项正式安排及1项COMPARE备选；`scoped_context.validate_uses`却要求COMPARE目标必须在正式安排中，触发GUIDE_CONTEXT_REFERENCE。此前采用v2未改变。修复为只有COMPARE允许当前输入目录内、原背景绑定范围内的未安排备选，留下审计，不插入活动或把背景转移为其他地点特色。SELECT/RELAXED_PACING、来源等价、引用、范围及事实校验继续执行。规则与提示升级advisory-guide-1.10/scoped-use-1.5，无数据格式迁移。

修改：`planning/scoped_context.py::validate_uses`、`planning/advisory.py::PROMPT/VERSION`；`preview/api.py`补上AUTOMATIC_ALREADY_RUNNING可执行中文提示；架构与任务书同步。合成测试覆盖备选不插入、背景不转移、非COMPARE不放行、虚构/目录外目标、范围断言、缺引用拒绝及不改写原答复。

验证：隔离主机临时目录运行test_scoped_context.py、test_advisory_guide.py、test_guide_lodging_revalidation.py，93 passed，22.59秒；两条既有依赖弃用警告，Ruff通过。第一条测试命令误写不存在的test_guide_revalidation.py，未运行任何测试，已纠正。直接传入API目录扩大mypy范围产生220项历史模块错误；项目标准`mypy --no-incremental`112源文件通过，未修改无关历史模块。保存的武汉原始答复按新规则只读复核接纳1，外部调用0，原失败/采用版/用量不改写。私人证据`.local/root-p11-review/B-context-recheck.json`，真实答复不提交Git。湖北缓存分析仍运行，部署须等其结束；页面本地复核、下载和两轮最终内容/恢复验收尚未完成。本批差异7文件、72新增/5删除（提交前文档补充可能调整），没有数据库迁移或新业务外部请求。

## 2026-10-11 跨日关键移动与衔接呈现批次

A在b8b247b运行版真实完成SUFFICIENT：仅3次模型、零新来源请求，六项具体玩法均CONTENT_REFERENCE，木鱼镇仅住宿，两住宿片区；普通预览取消后旧采用v1未改，累计7搜索/21正文尝试/71模型。尚未完成整轮验收。

修复critical_map.view与PrivateFlowMapService跨日关键段漏选；只放行显式绑定的相邻跨日段，有限2地点/1路径、当前模式、身份确认、版本与幂等保持。guide_view.project/export新增逐段移动窗口，UNKNOWN不伪称驾车可用，导出仍只用采用版；AdvisoryGuide/CriticalMap及前端类型同步。兼容契约字段说明同步domain.schema/OpenAPI/导出工具，无数据库迁移。

实际验证：Ruff通过；mypy 112文件通过；全13组网页交互脚本及vue-tsc/Vite构建通过。Python首轮37通过/1断言失败（内容相同、会话revision正常递增；修正断言排除revision），最终结果接续记录。生成契约说明首次命令因未配置导入路径失败，改为指定apps/api的本地脚本成功，仅变两字段说明。合成测试无业务外部请求。部署与真实地图/采用导出仍待执行，不能以此批代码宣布完成。

最终Python回归38通过（16.81秒），两项第三方弃用警告；Ruff与mypy112文件通过。网页13组测试、构建通过。导出衔接段明确写“本采用版顺序”，页面写当前草稿，避免混淆。

## 2026-10-11 五天真实失败后的机场与否定金额修复

1e791c9已推送部署，PID32724/launcher40464，静态index-DkICOW0q.js。数据库完整、A/B重启草稿/采用hash/账本未变。A七天已完成预览取消再预览采用v2和原生导出25,179字节精确校验；B新渲染导出32,735字节精确校验。有限真实高德分别查询A三游洞停车接入点→神农顶停车接入点DRIVING约187分钟、B山海关路→黎黄陂路TRANSIT约25分钟，各2地点/1路径无重试、日期未知仅一般参考，不落盘临时返回或写入攻略事实。

五天真实任务只3次模型、零站点/地图，HTTP200但最后PARTIAL/PLANNING_NOT_GENERATED；两提议PLANNING_UNSUPPORTED_FACT。原始诊断显示句子“不是票价、报价或已核实金额”被精确词法守卫漏识别，非额度/网络失败；机场未知被误更新arrival_transport=UNKNOWN。旧七天采用v2和真实失败历史保留。

修改agent_contract.INTAKE_PROMPT/understanding：机场/航站楼/取还车点只是位置，UNKNOWN引用无到达方式或交通方式证据时隔离该一项并记录IGNORED_LOCATION_ONLY_ARRIVAL_UPDATE_V1；其他真实更新正常应用，不修写原回复。显式到达方式未知仍可清除。arrangements._check精确支持最多四个金额名词组成的否定并列宾语，仍逐句拦截价格数字、肯定核实、保证和交通时间；规则locked-arrangement-2.5/advisory-guide-1.13。无数据或API结构迁移。

实际执行test_intake_contract/test_advisory_guide/test_goal_agent：172 passed，24.61秒，两项依赖弃用警告；Ruff、mypy112文件通过。原五天回复只读规则复核接纳2（一个局部/一个支持充分），网络0，不能称新模型回答；新真实五天条件修正/生成/保存及三天假设仍待验。实际下载工具先等待198秒后838秒才返回文件，文件已存在并独立字节校验；不能把工具等待当应用任务运行时长。

## 2026-10-11 明确否定已核实玩法的误拒

8c9d892已授权推送并核对远端完整SHA，部署PID22136/launcher26520，A/B正常恢复hash与账本不变。普通页面新五天请求只3次真实模型、来源/地图0，HTTP200/34.874秒/无重试；AIR到达、5天、当地UNKNOWN、不驾不租正确。唯一提议因“只有名称与组合线索，不能当作已核实玩法”再次PLANNING_UNSUPPORTED_FACT，旧七天采用v2未改，失败如实保留。

locked-arrangement-2.6/advisory-guide-1.14新增明确否定谓语不能/不可/不得/不要/不应＋当作/视为/认定为/认为是＋已核实，仅删除此精确跨度，不豁免整句或后续肯定断言。5组合成回归逐例追加同句肯定已核实、保证、交通耗时与金额，均仍拒绝；攻略与agent回归80 passed/12.49秒，两条依赖弃用警告。Ruff、标准mypy112文件通过。原五天新答复只读复核接纳1份ADVISORY_SUPPORTED，尚未页面预览采用，不称新模型回答。空闲备份before-negative-reference.sqlite3，quick_check=ok/外键0/448操作，A67与B34采用hash不变。
