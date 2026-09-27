# P05.2 公共地点发现与暂定安排

本批继续使用现有私人主页面、PlanningService、MapAction、preview_jobs 和 research_continuations。数据库保持 schema 15；没有新授权框架或阶段入口。历史 G1 NOT PASS 不变。

## 契约变更

- PlanAction 增加 `discover_places`（纯本地）与 `use_leads`（采用为暂定项目）。PlanView 增加 `place_leads` 和 `discovery_available`。
- `planning.discovery.version=1` 在现有 preview_sessions.state_json 中保存独立地点投影，并保留进入此路径前的采用版。名称绑定 source/content/hash、规范化精确位置和必要 parent 上下文；重新读取通过 SourceContentStore 的政策、过期和完整性检查。
- Activity 增加 `discovery_ids` 和 `SOURCE_MENTION`；MapPlace 增加独立来源标签。发现 ID 不是 Evidence ID，也不改变 source claims、审核或独立来源数。
- 现有新批次记录绑定原旅行和已授权内容 ID。CONNECT/SEARCH/DETAIL=0，MODEL=3，MAP_PLACE=6，MAP_ROUTE=2。生产识别只用本地路线连接词和公开地点后缀；识别模型未使用，也没有可挪用的重试槽。规划 `INITIAL_PLAN`、`ADJUST_PLAN` 各一次，预留失败计数，第二次要求已采用 AI 版及显式改选。
- 研究任务按它自己的历史 continuation 读取/取消/采用，避免新用途许可使旧待审状态消失。

## 含义和限制

发现只证明名称出现。保守语法会漏掉自由叙述或别名；不会用常识补全。必要过滤上下文、私址/标识、虚构、注入、明显限制会隔离；否定评价、假设和角色未知另行保留。现有 ROLE_MISMATCH 不修改。

地点可在活动采用前查询。唯一同名、同地区且类型一致时程序建议匹配；歧义由用户在现有候选组件中选择，确认后收起。来源声称市区与客观地理核实分开：来源匹配不升格为地理 MATCH，同一行政市也不升格；明确范围外线索保留 MISMATCH。用户接受 UNKNOWN 仅是本次范围意图，临时草案始终展示缺口。

规划接收经再次定位校验的名称和必要过滤上下文、当前非敏感约束；不接收真实地图返回、坐标、地址、历史审核标签。固定条件仍由安排协议 2 和程序持有，逐方案检查引用、时间、交通、预约和事实限制；采用不新增 Evidence。单个身份已检查的地点足以形成有限草案。

真实地图只在进程内。持久化的身份状态是此前输入决定及不可反推 provider 标识的摘要，不保存返回内容；重启页面明确地图过期，草案和来源含义保留，GET/保存/采用/刷新/重启不派发。路段只允许已采用活动顺序中的相邻同日项目，未选择线索不会增加交通边。未知通行、停留和接驳从不计零。

## 验证

`tests/integration/test_place_discovery.py` 直接运行页面使用的 PlanningService、PrivateFlowMapService、worker 和 API 路径；材料与地图均自编，网络禁用。覆盖待审/拒绝保留、精确定位、危险上下文、跨源/快照/账号隔离、单项 UNKNOWN 草案、独立方案保留、采用/取消/改选和跨进程零访问恢复。旧 P05.1 续读仍由原回归覆盖。实测结果另见批次报告。
