# P10 后续：通用建议逻辑修复

日期：2026-10-07（用户时区 Asia/Shanghai）。基线 `1aad83a88cc5eae11fc4009b987dbd91931a74fe`，功能分支 `feature/g1-live-llm-validation`。开始无未推送提交、无相关工作区改动，保留三份未跟踪 T03 报告。任务是修复通用生产路径，不是修订某一份攻略。

## 范围与结论

修复覆盖需求解析 → 资料用途 → 建议输入/校验 → 逐日覆盖 → 改选 → 页面/导出。没有按目的地、景点名、来源 ID、旅行 ID 或阶段编号设置生产分支；测试中的目的地和活动是参数化输入。没有手填真实第二天、修改主数据库、改写历史回复/门禁/已导出文件或恢复任何额度。

本轮项目模型、小红书 connect/search/detail/browser、高德地点/路径、embedding 和报价请求均 **0**。已有许可未重开。模型新协议仅在 Fake 和离线生产 worker 中验证，不能声称新的真实回复已能生成优质两日攻略。历史 P10 PARTIAL、G1 NOT PASS 均保留。

## 先复现，再修改

新增 `tests/integration/test_guide_coverage.py` 后，未改生产代码先运行：**16 failed**。

| 修复前问题 | 最初复现数 | 修复后对应断言 |
|---|---:|---|
| “一日”未识别；“十二天”被截作二天；轻松节奏未传入生产条件 | 9（3 目的地 × 3 说法） | 正确 1/2/12 天，pace=RELAXED，首项时刻仍为空 |
| 所有活动在第一天，2/3/5 天请求没有缺日判定 | 3 | 保留合法提议，分别标出未覆盖日，不宣称完整 |
| 模型输入没有资料用途和当前目标日序 | 1 | material_support 与 planning_context 同步进入生产输入 |
| 改选删除第二天项目，没有重评估缺日 | 1 | 预览立即显示第 2 天缺口；取消恢复原版，不改采用版 |
| 旧回复投影不能识别两日请求只安排首日 | 1 | 只读投影显示缺日，输入对象不变 |
| 删除某天项目后仍显示该天“两项目之间”用餐 | 1 | 当前投影/新组合删除失效餐饮；明确休闲日可以保留合理用餐 |

最初 16 个用例修复后全部通过。后续扩展到 52 个通用用例；不把合成 Fixture 成功冒充真实攻略成功。

## 通用函数与规则

| 生产位置 | 修改 |
|---|---|
| `guide_context.number/request_quantity/from_request` | 解析当前明确中文/数字天数、人数、房晚及轻松意图；区分日历日期/序数/区间/上限/冲突，未知不硬填。保留未知时刻、交通和步行 |
| `private_payload.assemble` | 最小活动输入带 provenance/reference_kinds；不扩大到原文、地图返回或私人端点 |
| 新 `guide_assessment.references/materials` | 只读已绑定本地引用/知识，保留角色；分别评估名称、路线组合、有活动内容参考、未确认和合成。名称数量、地点身份和采用模式不会升级为体验 |
| `advisory.payload/PROMPT` | 明确当前 required_days/pace、素材用途，以及来源日序不等于目标日序；引导跨日重新组织现有活动或明确休闲取舍，不要求精确时刻/完整地图 |
| `GuideDayChoice`、`GuideProposal/GuideContent` | 可选 day_choices：REST、SELF_ARRANGED、GAP，必须带理由。不是程序自动填充，不等于已取得用户同意；旧记录缺字段仍可读取 |
| `guide_assessment.meaningful/day_coverage/assess` | 识别具体非活动日与空占位，逐日列出项目/休闲/自行安排/缺口；用餐和住宿金额不算游玩覆盖；内容充分性与日序覆盖分开 |
| `advisory.validate/apply` | 保留逐方案引用、事实、范围、硬约束审核；增加日选择重复/越界/项目冲突及理由断言检查，独立合法建议带 assessment 保留，不因缺一日丢弃所有活动 |
| `suggestions.run_worker` | 新建议的结构/引用通过不再自动等于完整结果；有内容或覆盖缺口时使用 PARTIAL，仍允许正常预览/采用。旧 job 状态不改写 |
| `arrangements._check` | 仅无锁定首项的 ADVISORY 可以先休闲再于后一天安排活动；详细排程与锁定首项原规则不变 |
| `advisory.check_transition/verify_current/combine` | 保存、改选、采用和导出复核日序；新增项目不沿用同日旧空日说明，删项后重新计算缺口，不自动补新项目 |
| `guide_assessment.current_dining` | 删去无项目且无明确取舍之日的旧用餐建议；不足两个项目不继续说“两项目之间”，餐饮不掩盖覆盖缺口 |
| `PlanningService.get`、`guide_view.project/export` | 当前引用、当前选择和相同规则产生页面/导出评估；历史采用对象与已有导出文件不回写 |
| `AdvisoryGuide.vue`、TypeScript DTO | 展示每日日序、素材用途、必要引用片段、局部结果状态；允许正常页面填写休闲/自行安排取舍。模型提议比较也显示缺日 |

没有添加新供应商、知识功能、后台自动研究或新的固定许可。资料不足仍能开始建议；不要求每天有多个景点，也不强制每天排满。

## 充分性与约束的准确含义

- NAME_ONLY：只用于地点选择和暂定节奏，不能生成看点或作者体验。
- ROUTE_CONTEXT：已有组合/来源动线参考；不据此宣称有充分玩法内容或已适配当前多日需求。
- CONTENT_REFERENCE：当前绑定的已审核 EXPERIENCE 文本中，存在超出名称/路线串的内容。保留作者计划、攻略整理等原角色；不改为亲历，不证明实时开放/可行性。
- COVERED：目标日序均有项目或明确休闲/自行安排取舍，仅表示分配已交代；内容仍可 LIMITED_CONTENT，现实可行性继续 UNVERIFIED。
- GAP/未知天数：保留局部合法结果，标 PARTIAL；不会补“第二天自由活动”后称完整。
- 轻松多日却集中首日且存在缺日，产生重分配提示；已知停留下限超过六小时仅为软节奏提醒，不加未知路程为零，也不作为生成硬门槛。

资料内容判断与休闲理由检查都是保守结构/占位检查，**不是对任意自然语言语义的证明**。复杂说法可能继续被标为有限内容/缺口，不声称已解决全部自由文案理解。模型下一次真实生成能否合理分散活动，本轮未联网验证。

## 泛化与反例

新增回归包含：

- 目的地换为成都、苏州、海边小城及海岛说法，执行同一解析规则；两条 P10 原请求仅作普通输入，无分支。
- 天数 1/2/3/5 的覆盖矩阵，活动数 1/2/4/9，合计 16 种组合；少项目多日可用明确休闲取舍覆盖，名称依然不会变成丰富内容。
- 十二天正确解析；三到五天、三天或五天、最多七天、大概十二天保持未知；日期“10月7日出发，玩三天”只取三天。
- 明确休闲与泛泛“自由活动/根据实际情况自由活动/自行安排待定”分开；GAP 不因有文字就通过。
- 无首项锁定可先休息再游玩；加入首项锁定后冲突被拒。超范围日和伪造房态/预订说明拒绝，另一独立合法方案保留。
- 只有名称的 EXPERIENCE 标签、纯路线串、PLAN_PATTERN 均不升级为真实活动内容；作者计划角色保留。
- 生产 Fake worker → 同一提议预览/取消/再预览/采用 → 导出 → 独立进程 DNS/socket 禁用恢复；局部结果为 PARTIAL，内容、采用版和导出相同。
- 前端组件渲染检验缺日、休闲、名称资料、局部提示与安全转义；类型与构建通过。未用真实页面触发研究或采用动作。

## 历史输入只读复核与保护

以 SQLite `mode=ro` 读取当前库中的 P10 绑定输入和采用对象；调用相同生产解析、资料用途和投影函数，DNS/socket 禁用。只保存新的匿名诊断摘要，没有重新导出或改写攻略。

| 历史输入 | 新通用规则只读结果 | 原内容 |
|---|---|---|
| 城市一日 | 解析 1 天/轻松；LIMITED_CONTENT，NAME_ONLY，无缺日 | 原 1 项不变，未补看点 |
| 区域两日 | 解析 2 天/轻松；PARTIAL，第 2 天缺口；3 项均 ROUTE_CONTEXT | 原 3 项仍在首日，没有手写第二天 |

保护核对覆盖真实数据库文件、两份历史 MD 和原静态目录共 20 文件，SHA-256 完全相同。主库未迁移、删除、覆盖或改数据；原服务/8768静态未替换，旧许可/用量未变。测试写入只发生在仓库外独立的合成测试 SQLite，不接触业务库。

新前端构建位于忽略目录 `.local/p10-generic-web`，供开发验收；未把“测试构建通过”说成当前8768已升级。私人只读诊断在 `.local/p10-generic-replay.json`，原文和真实ID不提交 Git。

## 契约、验证与提交

规则版本 advisory-guide-1.5，评估版本 advisory-assessment-1，响应协议仍 v4。新增 PlanDraft.pace、GuideDayChoice、day_choices 及派生 assessment；后端模型、domain schema、前端 DTO 和本说明同一显式契约提交。OpenAPI 路由不变，SQLite 16 无迁移。旧 schema 响应继续读取，旧 worker 输入/版本失配仍走现有过期保护，不静默重判历史失败。

最终命令（仓库根目录；npm 构建在 apps/web）：

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -q --basetemp=../p10-generic-final-2 -p no:cacheprovider
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy
npm.cmd test
npm.cmd run build -- --outDir ../../.local/p10-generic-web
.venv\Scripts\python.exe tools/export_preview_contract.py
.venv\Scripts\python.exe -X utf8 tools/validate_pack.py
git diff --check
```

最后生产修改后的全量结果为 **1237 passed，2 warnings，170.23 秒**，包括新增 52 个通用回归；Ruff PASS，Mypy 89 个源文件 PASS，8 个前端测试脚本 PASS，Vue 类型检查/Vite 48 modules 构建 PASS。文档/契约 12 项 PASS（117 个 domain 定义、201 个引用、248 个 Markdown 链接），OpenAPI 只标项目已有的结构检查，不伪称完整外部验证。差异检查通过。

完整输出仅留本地忽略目录。过程中出现的沙箱临时目录 WinError5、构建子进程 EPERM 用授权的本地执行解决；测试初稿的 pytest 保留参数名和子进程导入路径已修正，没有修改保护规则。最初缺失新报告链接的文档检查在文件完成后重跑，不充作成功。此前一轮 1237 PASS 之后还补齐了新 worker 的 PARTIAL 状态，因此重新执行上述最终全量，没有拿修改前成绩代替。剩余两条 Python 依赖弃用警告和前端既有 SSR 编译提示保留。

按明确文件清单暂存，扫描全部未推送 Git 对象中的凭据、运行库、profile、真实来源/正文和敏感诊断后推送原功能分支。不合并 master、不发布稳定版。diff 与最终提交/远端 SHA 在收尾消息中返回。

本轮 `git diff --stat`：20 files changed, 1053 insertions(+), 31 deletions(-)。主要增量是通用评估模块及 52 项离线回归，不含运行数据。

## 尚未解决与停止点

1. 本轮没有新增内容；城市来源本身不足不会由代码修复变丰富。
2. 没有新真实模型请求，不能证明修改后的提示和结构已让真实模型给出优质多日结果；原新津攻略仍缺第二天。
3. 自然语言复杂日期、节奏与理由只做有限解析/保守检查，不能保证任意表达都准确；页面仍允许明确修改。
4. 内容参考与日序覆盖都不等于交通、营业、预约或报价已验证；本轮也不增加这些前置门槛。

通用逻辑修复与离线验证到此收尾。后续真实生成须另有明确许可；不消耗 P10 剩余次数，不进入外围功能。
