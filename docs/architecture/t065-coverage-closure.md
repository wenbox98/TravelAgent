# T06.5：有限补充与第一份粗略攻略

本阶段固定 continuation=`t065-coverage-first-plan`，前序为 T06.4 所在研究。入口为 `scripts/private_research_smoke.py --live --t065`；沿用原私人 SQLite、专用 profile 与 OBSERVE_ONLY。启动先查询已接纳证据并保存缺口计划。不是重新运行旧来源。

## 必要修复与契约变化

- CandidateSelector 的区域名硬过滤改为标题/请求地点/查询上下文的排序。没有区域名但有行程信号的查询结果可作为弱候选；无行程信号且无地点依据的结果不进入。query_context 不进入 Evidence；请求 destination 只是缓存检索标签，不证明笔记涉及当地，正式结论须经过正文定位及 Work 上下文复核。没有 IP 属地字段或地名归属词典。
- 短报告逐条显示已审核条件、已有旅行日期及正文完整度；无路线时仍显示可用的局部体验。已给定的天数/交通不再重复询问。局部活动时间不作为整趟天数。
- 合成复现确认：旧 build_directions 会合并跨源同名方向，并漏接跨段落明确归属。现按 source_id 隔离；新增可选 ClaimAssessment.route_association：source_id、object_quote、object_block_id、object_locator、scope（WHOLE_TRIP/SEGMENT）。对象必须是同一正文的逐字锚点，同时加入条件与定位链；Work 必须检查明确的主体/归组关系。没有这种审核记录时不因相邻段落、相似文本或同篇文章合并。非路线关联须在同源已接纳 ROUTE 中存在相同对象，否则事务回滚。
- 可选 reference_scope=AUTHOR_RECORDED_TRIP 只用于经 Work 复核并保留原文条件的作者当次经历；不要求必须具有精确到日的日期才能记为历史经历。此时 Freshness 为 HISTORICAL，不证明当前可执行性。价格/开放/预约仍为 CURRENT_UNVERIFIED，不能使用此字段绕过。未带新审核字段的历史 Evidence/报告不变，grounding v2 逐字及上下文标准不变。
- 提取提示只增加缺口优先级：路线、整趟天数、交通和区别性体验优先于泛泛情绪句；不改模型、响应格式、候选 schema 或逐字约束。

规则澄清反例：作者明确“2024 年秋天我自驾用了四天”可作为那趟自驾经历；不能推出用户五天不自驾可行，也不允许“现在道路开放/免票”凭历史标记升级为当前事实。新关联展示规则记为 T06.5；旧成绩保持原样。

## 耐久额度与截止

SQLite v9 新增 research_continuations 和 continuation_operations。固定授权只允许 connect=1/search=1/detail=2/model=2，前序配置、账号范围、120/180 秒设置不可变；必须匹配已消费的 T06.4 模型配置。按来源去重并在派发前持久预留，异常也不退还；不接受新的 run id 重启该批次，不级联删除额度。清理缓存也不恢复授权。

普通新来源先保存 SourceContent/BodyBlocks，再预留 ExtractionRecovery attempt。supervise_continuation 接到共享 supervise_reserved：子进程明确继承 timeout=120，180 秒外层截止，超时终止并回收自有 worker，仅协调未完成状态；已提交候选/证据不覆盖。worker 验证固定授权及配置，只允许原 DeepSeek 服务，不导入浏览器。每个新来源最多一次，模型传输失败停止后续派发；无可用文字的图像依赖详情不调用模型，正常传输但没有合格证据可在剩余额度内读另一新来源。

原批次、3 条已接纳 Evidence、旧失败与追加授权原样保留。本阶段不重置旧预算、不测试模型连接、不进行模型排名/审核/报告生成；不重读旧详情。一个普通 BrowserSession，结束正常关闭并保留 profile。

## 质量与交付边界

各方向逐字段关联，来源之间不交换时长和交通；现有 G1 阈值不变。Coverage 的聚合 SUPPORTED 不证明每个方向齐全，各方向 unknown 和 DIRECTION_ASSOCIATION 仍阻止过早充分。有用的局部材料可以展示，不能把缺口掩盖成完整行程。

真实内容只在私人 SQLite 和 `.local/t06.5-live/`。公开报告仅匿名来源、计数和必要摘要。独立进程禁网恢复非空证据/条件/lineage，并生成首轮报告和五天不自驾的零预算增量报告。context request events 不等于实际 wire/bytes；缺测保持 NOT_MEASURED。

产品待办：WORK_REVIEWED 仍依赖开发 Work 逐条复核，不是无人值守产品能力。后续须定义自动审核与待审核边界；本轮不增加多 Agent 审稿。KnowledgeCard、成功入库后的原文清理及独立清理入口仍是后续设计，本轮不实施、不删除核对用原文。
