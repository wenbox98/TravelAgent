# 首次模型理解与有界工具循环

基线 `0e2fa62058ed9d822e87c866a014b88aa910de27`，功能分支 `feature/g1-live-llm-validation`。本批为通用生产逻辑修复，未按目的地、景点、来源或旅行ID特判。历史 G1 保持 NOT PASS；真实模型语义与研究质量为 NOT_MEASURED。

## 复现与修改

旧普通入口先以规则解析条件再启动固定研究流程，首次并没有独立模型理解记录。到达飞机与当地租车自驾没有分开，换成其他目的区域、中文天数和不同表述也可能留下驾驶/交通 UNKNOWN。后续正则分类不能充分解释否定、纠正和假设。这是生产路径缺陷，不通过修改已有旅行数据修复。

| 生产文件/符号 | 通用改动 |
|---|---|
| `planning/agent_contract.py`: Understanding、Decision、understanding | 版本化理解与单工具决策；逐字段原话定位、类型与意图约束，简短审计摘要 |
| `planning/agent.py`: intake_payload、apply_intake、decision_payload、tools、run | 理解后提交条件；到达/当地交通分开；六轮有界决策；实际工具结果回传；选择、排除、锁与当前引用进入新输入 |
| `planning/agent_model.py`: create、run、binding | 单次耐久模型子任务、120秒供应商超时、180秒外层等待、前后 revision/权限/引用检查；晚到结果不能提交 |
| `planning/automatic.py`: start、_create、action、task_view、run_task | V3普通入口、同grant顺序子任务、聚合各轮来源/计数；V2兼容保留；取消/重启不重派 |
| `planning/conversation.py`: action | V3提交先理解再处理；保存幂等回执，丢响应后只读恢复能确认原提交 |
| `preview/worker.py`: run_job；`research/service.py`: run | 多轮共用reader与一次连接；累计详情编号；严格审核及独立合格结果保留 |
| `planning/agent_map.py`: execute、invoke | 只经当前授权的服务端业务包装器；使用同一账本，公共候选需确认，模型不收地图返回 |
| `planning/suggestions.py`: launch；`planning/network.py`: install；`scripts/product_preview.py` | 按版本选择worker角色；模型子进程单请求，浏览器仅研究角色；保持同一8768与工作区 |
| `flow_models.PlanDraft`、`advisory.payload`、`guide_view.project/export` | 新增 arrival_transport/rental 的未知默认值；规划、页面与导出分别显示两段交通 |
| TripIntake、TripConditions、AutomaticPlanning、AgentProgress、PlanningPanel | 首次待理解、原话依据、逐轮进展、真实预算和可选单段地图授权；保留未提交草稿及采用流程 |

首次与后续 V3 的模型请求都真实经过 configured_provider/structured 入口。规则只提供暂定展示及原有上限分档，不作为最终理解。单独输入的目的区域为程序持有的用户字段；不能伪造原话位置。没有机场、私址、人数、预算、日期时不补猜。

生成有用提议后本任务不继续采集或生成另一份；采用仍由用户明确操作。未生成或后续失败时保留合格资料、历史提议与真实缺口。问题和假设不修改已确认偏好，缓存答复保留引用。事实审核、逐方案约束和来源作用范围未放宽。

## 契约与额度

新增 `PRIVATE_GOAL_AGENT_V3`、理解/决策 DTO、本机 agent-map DTO/路由和 arrival_transport/rental。同步 domain.schema、openapi、导出器和 [架构契约](../docs/architecture/goal-directed-private-planning.md)。SQLite 18 只调整唯一索引：历史研究仍单grant单任务；V3可顺序创建多个model/research-step，同一grant仅一个活跃agent研究/模型子任务。迁移测试检查历史行及账本不变，第二个活跃子任务失败时预算预留回滚。

没有增加旧总额度：初次仍模型9或13、搜索2或3、正文4或6、连接1；后续仍模型5、搜索1、正文2、连接1。理解、每轮监督、提取、审核与生成都占这份上限。每个gap工具至多一篇新正文，不承诺读满总上限；不能据此宣称“最多6篇均可读完且生成”。默认地图0，单独勾选才是地点2/路径1。所有历史失败、用量和已关闭许可保留。

## 离线证据与失败分类

真实 OpenAICompatibleProvider 的请求序列化由自编 Wire 接收，socket/DNS禁止外连。完整链为 intake → supervisor → extract → context review → supervisor（看到实际采信数和引用）→ planning → supervisor/FINISH。这验证生产协议和输入，不是 DeepSeek 实站结果。

新增测试覆盖不同目的区域、天数、交通表述，否定/纠正/假设、伪造引用、独立目的字段、同一reader第二次研究、验证后停止并保留第一篇合格材料、无地图许可、旧generation晚到、重复动作早停、当前选择与排除、缓存答复引用、同grant迁移/并发边界、独立进程禁网恢复。页面测试继续使用真实构建、HTTP入口和生产子进程，Reader/模型/Amap为自编离线边界；没有手填运行库。

实际经历并修复的失败：

- 活跃job旧唯一索引阻止第二个模型子任务：增加明确的SQLite18索引契约；不删除旧job。
- 内联离线Provider观察器残留已关闭子DB：离线派发复制Provider，模拟生产每个子进程独立生命周期。
- 新进度组件SSR测试加载器不识别Vue子组件：补齐编译与进度/失败断言。
- 旧页面断言仍把假设当条件更新、把缓存任务算成新增搜索：改为检查五天保持不变及当前grant站点计数0。
- 子进程页面发现新入口丢响应后无法确认回执：生产入口保存 conversation_intent_key，新增重复提交/只读恢复回归。
- 迁移/地图测试的初稿误用QUEUED父任务或错误view字段：修复合成测试准备与断言，没有改宽生产权限。

沙箱下曾出现临时目录WinError5和Vite spawn EPERM；使用获批的本机离线执行后正常完成，未改ACL或安装依赖。曾扩大mypy到未纳入项目标准范围的脚本，触发现有未注解/PyYAML stub错误；项目规定的107文件范围通过。不是业务外部调用失败。

执行检查：

- `python -m pytest -q --tb=short --basetemp=...`：首轮 1440 PASS / 3 FAIL（上方页面断言与回执问题）；最终 **1447 PASS，2项既有弃用警告，397.30秒**。未跳过失败来凑通过。
- 新增目标/上下文/地图测试：19项分别通过；三个本机页面验收分别通过。最终全量结果优先于单独检查。
- `npm.cmd test`：10组页面测试通过；`npm.cmd run build`：TypeScript与Vite构建通过。
- `python -m ruff check .`、`MYPYPATH=apps/api;integrations/xhs-sidecar python -m mypy`：通过，mypy检查107文件。
- `python tools/export_preview_contract.py`、`python tools/validate_pack.py`：通过，129定义、221引用、46路由结构检查。

## 部署和数据保护

同一 `.local/p04-preview/preview.sqlite3` 与 `.local/workbench-web`，不新建工作库、不覆盖用户草稿。部署前确认旧PID12548、原前端资源、SQLite17、活动任务0，作一致性备份及静态回滚副本；原61表与开工快照逐行一致。正常关闭旧进程后，资产先复制、index最后替换，旧资产保留。迁移18后61表仅schema_version新增一行，其余60表逐行一致：54条Evidence、24个来源、22张知识卡、32条job、7条历史task、131条操作账本全部保留。

首次受限启动PID27404的构造自检因ProfileError未通过，未访问网站。改为获批的本机用户执行环境后，专用profile构造自检通过；没有改ACL、复制会话或提高Windows权限。最终PID36432，TokenElevation=false，浏览器会话0，健康200，活动任务0。与构建目录、运行静态目录和HTTP返回三方核对一致：`index-Itto-JmR.js` SHA256 `ffdeabe83845af9932fbab0763dfac42f621fb80d93889e64430f38204cab5e2`；CSS `index-DRy8SRU_.css`。本机备份、比对结果与源码/资源核对仅存在Git忽略目录，不提交业务数据。

本机继续使用同一个入口：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

已运行时直接用 http://127.0.0.1:8768/ ，无需重复启动。需要恢复本机登录入口可执行同一脚本的 `open`。本批不替用户提交未发送草稿，也不重跑历史失败。

## 网络、剩余问题与交接

本批业务实站请求：小红书connect/search/detail/browser **0/0/0/0**，DeepSeek **0**，高德地点/路径 **0/0**，embedding/报价 **0**。本机回环HTTP和离线页面测试Chromium不计作小红书浏览器。生产审计相对开工快照的model_http/amap_http/external_dns/external_socket/blocked_external增量均0，无PID复用歧义；新增角色只有serve和零访问research-preflight。浏览器会话0为启动构造自检实际测量；真实网站浏览器network/navigation未测，不冒充测量值。

真实理解质量、真实来源数量/攻略深度及新循环高德整链均 NOT_MEASURED，不宣称私人稳定版或G1通过。图片/视频未分析；材料和交通缺口依然可能导致局部建议。地图候选需人工确认时循环停止，后续使用既有关键路段显式流程，尚非全自动地图闭环。缓存充分时V3仍需要理解和监督次数；五次后续上限可能只能保留新材料而无法同时完成新提取及规划，真实停留缺口不能抹掉。

仅在功能分支显式暂存代码、合成测试、契约与报告；安全扫描覆盖暂存与完整未推送提交范围，匹配本机已配置密钥及真实正文片段，不打印匹配内容。三份原T03报告保持未跟踪且字节不变。本地/远端完整SHA与提交链接在交付消息核对，不合并master、不发布稳定版。

`git diff --stat` 摘要：46个文件，新增V3理解/监督/地图桥/模型worker、进度组件、迁移、契约、离线与页面回归和报告；实际提交统计以本批Git提交为准。没有运行数据、图片、原文或凭据文件。
