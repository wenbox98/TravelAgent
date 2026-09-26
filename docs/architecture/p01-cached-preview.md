# P01：已审核缓存到本机选择预览

这是 T06 缓存草案、T07 选择事务和 T09 本机页面的子集，不代表三个原任务整体完成。G0 沿用历史结果，G1 NOT PASS；不推进 G2–G4 或 D1/D2。

## 正常入口

`scripts/cached_preview.py` → `main.create_app(preview=PreviewConfig)` → `/api/v1/preview` → `PreviewService` → SQLite、SourcePolicy、EvidenceRepository、SourceContentStore、ClaimAssessment → 既有 `build_directions` → Vue。

没有 ResearchService、live reader、sidecar、提取器实例或模型实例，不读取 Work 写的 Markdown 攻略。必须显式指定数据库、scope、模式和私人工作目录；不扫描磁盘，不加载模型凭证做探测。默认 dev.py 控制面未配置此缓存 API。

原库首次通过 SQLite online backup 建立独立工作副本；以后只恢复该副本，不覆盖副本、不刷新来源。自动更新工作空间内容是后续事项。本轮不删除或改写原库、profile、账本。

## 投影与条件

- 读取当前 scope、当前 research revision 最新完成报告的 source/claim handles，不按目的地扩展整个资料库。
- 旧及最新 SourcePolicy 均需允许读取与保留派生材料；正文策略与有效期由内容仓储复查。`load(purge=False)` 只隐藏过期内容，不在页面读取时删除原文。
- Evidence 必须为 WORK_REVIEWED，对应候选仍 ACCEPTED 且 claim/source/scope 一致，再以 `audit_grounding` 重验正文定位与片段。待审、拒绝、缺审核和失效来源不展示。
- 复用来源内已审核对象关联；其他局部体验、时间和交通留在兴趣线索，不借共有地名跨源拼接。标题只作来源标识，不从标题推定天数、年份或夜数。
- option_id 绑定 scope、research、对象及 Evidence 集合；依据文字或条件变化通过 Evidence 摘要阻止旧确认。路线、来源日序、交通和季节条件保留证据引用，展开可见原条件、角色、定位与片段 ID。
- 同源同主题同文字只算一个观点，不增加独立来源数。来源独立性、实际总耗时、费用保持未知。
- 仅在同一关联对象中存在至少两个、自 Day1 连续且无重号的标签时推导日序数量，标 DERIVED_FROM_SOURCE_SCHEDULE。单独 Day1 或 Day4 不推导全程天数；多对象标签不合并。

未知预算和人数不阻塞草案。有限规则只解析明确天数、驾驶意愿和“国庆”原始表达；多研究命中需从列表选择。冲突、双重否定或模糊约束只提出一项澄清，不猜测。最多两项带解释的问题；已知或已选择暂不确定的条件不反复问，仍可主动修改。“不想开车”不等于只接受公共交通，包车仍未知。用户五天不自驾不改变来源自驾、日序或季节。

## 选择事务与恢复

SQLite v11 只增加 preview_sessions、preview_receipts。用户输入、偏好、确认项、预览项与 revision 独立保存。BEGIN IMMEDIATE 事务绑定 expected_revision、scope、mode、research revision 和 Evidence 摘要。预览不覆盖确认项，取消保留原项；同幂等键同体返回同一会话的最新安全视图，不重复变更，异体返回 409。旧 revision、无效 option 和变化的研究不能确认。

读取时重新生成允许显示的资料；策略撤销立即隐藏，变化时 stale=true，保留原确认标识并要求重新打开研究。Vue 串行提交并检查请求 generation／返回 revision，旧返回不覆盖新状态。刷新从数据库恢复，后端重启不启动研究。

## HTTP 与安全

已实现 GET `/api/v1/preview`、POST `/api/v1/preview/sessions`、GET/POST `/api/v1/preview/sessions/{session_id}`；输入输出严格白名单 DTO 与现有 domain.schema/openapi 同步测试，其余原业务路径仍是设计契约。

绑定 127.0.0.1，复用精确 Host/Origin 与 CSP。启动输出五分钟有效、单次 loopback bootstrap 入口，交换 HttpOnly、SameSite=Strict cookie 后 303 跳到无票据首页。写操作验证精确 Origin、CSRF 和幂等键。随机会话密钥仅保存在私人工作目录，前端不持久存 token；重启同工作目录可复用本地 cookie。这与小红书认证无关，不接触平台 Cookie。

生产构建由 API 同源提供，无跨域放宽、CDN、远程字体、原图或头像。Vue 插值转义，不使用 v-html。来源链接只含公开笔记 ID，不带访问材料、不预加载，验收不点击。错误不反射入参、数据库路径或异常原文；API 与 bootstrap no-store，访问日志关闭。

## 备份、迁移、回滚

首次从只读原库 online backup 到 workspace/preview.sqlite3，包含已提交 WAL 数据。升级前另存 before-v11-from-v10.sqlite3。迁移使用既有事务和外键校验；失败即回滚，原库无需升级。

回滚先正常停服务，保留当前副本和选择；用升级前备份建立新的私人工作目录，由兼容旧 schema 的代码打开。不要对原库执行降级 SQL、删除原文或账本。再次启动只恢复副本，不重置任何额度。

## 尚未完成

普通 EvidenceExtractor 和 ResearchService 默认仍使用 extraction v2；T06.6 指定追加授权 worker 显式使用 v3。P01 不提取，因此不是普通新资料入口的 v3 接线验收。上下文审核仍为 Work-assisted，并非产品自动语义审核。

缓存未命中后的自动研究、普通入口 v3、可行性、地图接驳、报价、KnowledgeCard 与原文生命周期均留待后续。选择成功只表示兴趣确认。运行和验收见 [P01 报告](../../reports/P01-cached-overview-preview.md)。
