# P10 普通新旅行入口收尾与私人试用交接

日期：2026-10-08。基线：`e0f4d65010388ab463d3f20960ef7e34066c40d0`；分支：`feature/g1-live-llm-validation`。本轮修复普通新旅行的本地选材冲突，不新增研究质量、模型质量或稳定发行结论。历史 G1 NOT PASS、原 P10 PARTIAL 和失败记录不变。

## 结论与关闭口径

| 项目 | 结果与证据 | 边界 |
| --- | --- | --- |
| 普通新旅行历史入口缺失 | 可关闭：默认 `knowledge_first=true` 的真实 API 创建路径，修复前历史候选为空；修复后显示有效历史组合 | 没有改默认创建参数规避；没有目的地、活动名、来源或旅行 ID 特判 |
| 历史活动误走卡片采用校验 | 可关闭：基线正常选历史组合后采用得到 `GUIDE_REFERENCE_UNAVAILABLE`；修复后独立来源校验、采用、导出通过 | 仅通过实际选材确定路径，卡片验证未删除 |
| 本地选材被外部授权区隐藏 | 可关闭：显式“先用已有资料”包含资料卡、历史组合、主动查找入口 | 许可未开/已关闭也可本地使用，显示研究入口不会派发 |
| 取消、作用范围和版本保护 | 可关闭：可逆选材快照；组合内层取消保留外层引用；采用前撤销/变更拒绝 | 整体背景不下放为逐站属性；UNKNOWN 不变 MATCH |
| 正常页面本地闭环 | 新独立验收旅行完成选择、取消、重选、采用；生产导出结果另存，后端独立禁网恢复通过 | 历史活动和历史建议复用，没有新模型生成；浏览器下载落盘未确认，页面与独立进程恢复均通过 |
| 内容相关性、玩法帮助程度 | 留给实际私人试用判断 | 本轮不丰富看点、不增加内容质量门槛 |
| 未验证能力 | 新目的地真实研究质量、明确市区需求的真实适配、当前开放/预约/交通/票价 | 合成泛化回归不是新目的地实站通过 |
| 真正阻塞检查 | 未发现凭据泄漏、旧版本覆盖、未知金额当零、无界外发或正常本地入口阻塞 | 不宣称完整私人版、G1 或稳定发行通过 |

## 通用实现与契约

- `PlanningService.get/action`：空白普通旅行同时暴露历史选材能力；`material_filter` 仅保存本旅行筛选，不关联许可；本地选材参与预览/取消/采用。
- `local_materials.begin/cancel/entry/reference_binding`：只保存必要选材状态，保留来源版本指纹，取消不会恢复或复制旧许可；非空草稿不能被跨类型选材覆盖。
- `workbench.reuse_options/reuse/local_contents`：同账号、同目的地和旅行类型；测试材料默认排除；来源撤销、原文主动清理、卡片关联与版本变化仍受检查。历史活动不复制旧预约、锁定、人数/天数/交通或采用状态；日序初始化为可修改的第 1 天，时段未定，原日序仅记为历史参考。
- `materials.references`：复用引用再次检查撤销与指纹变化；`knowledge.planning.attach`：卡片仍走自己的 verify，增加可取消选材与测试来源属性。
- `guide_view.project/export`：同源投影明确历史复用；整体背景及条件按原范围保留，不增加独立来源计数。
- `LocalMaterials.vue`：明显的三条选材路径、空候选解释、显式测试筛选，选后及刷新后收起；`PlanningPanel/OperationPanel/KnowledgeLibrary/AdvisoryGuide` 连接正常页面，旧草稿和未保存编辑保护保留。
- `PlanAction` 增加 `material_filter/include_test`，`PlanView` 增加 `local_materials`，前端类型和 `contracts/domain.schema.json` 同步。没有数据库迁移，schema 仍为 16；重新生成 OpenAPI 后无内容变更。本批以明确的契约变更提交收尾。

## 修复前后与泛化回归

`tests/integration/test_local_material_entry.py` 共 25 个参数化实例；前端 `tests/local-materials.mjs` 验证真实默认创建参数、实际组件 setup 和渲染。

| 用例 | 修复前 | 最终结果 |
| --- | --- | --- |
| 普通默认创建，有历史活动、无卡片 | FAIL：`reuse_options=[]` | PASS：入口可见，无许可可选 |
| 同一默认入口选历史活动后采用 | FAIL：409 `GUIDE_REFERENCE_UNAVAILABLE` | PASS：保留来源、正确采用并导出 |
| 仅卡片/仅历史/都有/皆无 | 新增回归 | 四种组合 PASS，有说明和其他入口 |
| 目的地、账号、类型、来源撤销、版本变化 | 新增回归 | 不串场；旧候选 key 失效；预览后撤销阻止采用 |
| 开发测试筛选及原文已清理的卡片复用 | 原有和新增回归 | 普通资料不受测试开关影响；已清理来源不从原文兜底 |
| 整体背景、独立来源计数与未知范围 | 原有和新增回归 | 保留条件/范围；未将背景复制为每站特色 |
| 本地取消、内层组合取消、无/关闭许可 | 新增回归 | 原草稿/引用/锁定不丢，未启用真实外发 |
| 换目的地、同名活动、1/2/3 项及不同天数 | 新增合成回归 | 当前明确条件优先，旧天数、交通、预算、预约不继承 |
| 非空恢复后的选材收起 | 实现中发现首次挂载展开 | PASS：实际组件 setup 与页面恢复核对 |

最终命令与检查：

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -q --basetemp=C:\Users\admin\AppData\Local\Temp\travelagent-handoff-20261008-final2 -o cache_dir=.local/p10-handoff/pytest-cache
.venv\Scripts\python.exe -X utf8 -m mypy
.venv\Scripts\python.exe -m ruff check apps/api/travel_agent/planning apps/api/travel_agent/knowledge tests/integration/test_local_material_entry.py
# apps/web 下
npm.cmd test
npm.cmd run build -- --outDir ../../.local/p10-handoff/web-final-2
```

最终全量：1305 passed、0 failed、0 skipped，176.84 秒；2 条已有依赖弃用警告。配置范围 mypy：92 文件通过；Ruff 通过；前端 9 组脚本通过，vue-tsc 与 Vite 构建通过。tools/export_preview_contract.py 已执行；契约、文档与差异检查通过。

中间失败如实保留在私人日志：首次将 pytest 临时 profile 放在 Git 仓库内，触发现有隔离检查（25 failed / 40 errors / 1239 passed），改用仓库外临时目录后通过；另有沙盒权限/构建 `spawn EPERM`，正常用户权限重跑。原文清理历史筛选和嵌套取消问题均在本批离线回归中修复。前端 setup 测试首次模块引用转换失败，修正测试加载器后通过。误将 mypy 扩到整个 API 的一次运行产生 209 项、30 文件错误；该命令超出现有配置范围，不作为本轮通过项，不顺手扩大整改。

## 正常页面与数据保护

使用原 `.local/p04-preview/preview.sqlite3`、`.local/workbench-web`、8768；开始检查无活动任务、无非空未采用草稿，先用 SQLite backup 保留一致性副本和旧静态目录。没有修改历史 SQL 数据来凑验收。

普通按钮新建独立的开发验收旅行，默认知识优先、无许可。原库可用材料均带测试标记，因此默认显示 0 卡片/0 历史组合；显式包含后为 8 卡片/10 历史组合。选择最新两活动组合：2 活动、1 合法整体背景、1 独立来源。天数/人数/交通/步行意愿未定，范围仍 UNKNOWN；保留历史 60–90 / 30–60 分钟建议和各 15 分钟休息，没有新模型提议。取消恢复原空草稿，重选并采用为本旅行第 1 版。页面模型和研究按钮未授权、不可派发，未创建非零许可。

页面“导出采用版 Markdown”返回成功。自动化等待下载事件超时、标准下载目录未找到新文件，故浏览器下载落盘尚未确认；不能仅凭成功提示宣称下载通过。另将生产 `guide_view.export` 的原样结果保存为私人 `local-reuse-adopted-guide.md`，没有手改内容，未覆盖旧导出，不进 Git。重启前后该 Markdown、采用草稿、来源引用和背景投影完全一致。

以 Ctrl+C 正常关闭本任务服务，再运行同一 `serve`。独立只读进程禁止 DNS/socket，读取原库调用生产服务，恢复 2 活动/1 背景与全部引用、采用版/导出完全一致，无任务或许可。新的正常入口已在应用中打开，页面恢复同一采用版、两项停留建议与合法背景，选材区收起。旧标签直接导航 bootstrap 被浏览器策略阻止，未规避；沿用正常入口成功打开后继续核对。页面展示测试属性、未知范围/交通/步行及未授权状态；研究/模型按钮禁用。

逐表比较开始备份与当前库：所有旧行原样保留。37 Evidence、8 卡片、10 原文内容/209 段、24 旧任务、19 延续批次、76 旧操作记录及全部审核/失败/采用版本未改变。只新增 1 个正常 UI 旅行（22→23 会话）及 7 条页面操作回执（286→293）。12 份已盘点私人旧导出哈希不变；主库未清原文、未删除 profile。

## 外部调用与测量口径

本轮项目模型 0；小红书 connect/search/detail/browser 0/0/0/0；高德地点/路径 0/0；embedding、模型下载、报价 0。未建立许可、未消耗旧余额、未重测连接或重试。

依据：本轮服务进程的 operation-audit 计数 `model_http/amap_http/external_dns/external_socket/blocked_external` 全部为 0；旧业务任务与 continuation_operations 全部保持不变；恢复进程明确禁止网络；页面只执行本地 API。没有启动小红书服务/浏览器。前端和离线测试使用合成/Fake 或本机 HTTP。

这些是项目进程计数及数据库核对，整机抓包、整机连接数和总字节为 NOT_MEASURED；不报告整机零网络。Git 同步单列，不属于旅行业务调用。

## 使用与部署

[私人试用说明](../docs/private-advisory-quickstart.md)。唯一启动命令（已有服务无需重复运行）：

```powershell
Set-Location E:\workSpace\travel-agent-project\travel-agent
.venv\Scripts\python.exe -X utf8 scripts\product_preview.py serve --open
```

地址：<http://127.0.0.1:8768/>。最短路径：新建独立旅行 → 先用已有资料 → 选择卡片或历史组合 → 预览/取消/采用 → 导出。测试资料需显式包含；外部许可独立设置，本批没有开通。

运行版实际静态资源为 `index-DcqMK81a.js`，正常重启进程 PID 33120，沿用原工作空间和数据库；后端生产文件与本批源码哈希核对一致。通过恢复页 DOM 实际核对 JS 为 index-DcqMK81a.js；已部署资源 SHA256 为 8b20dba16e2a144781242b456d80ae5b862d02ebb5767ef0f54715db6866421e。页面全图和入口截图仅保存于忽略的私人目录，不进 Git。

## Git 与停止条件

`git diff --cached --stat`：24 个文件，895 行新增、34 行删除，包含生产入口/引用校验、契约、25 个新增回归实例、前端组件验收和交接说明。完整待推送范围检查了文件类型、凭据模式、本机已配置密钥精确匹配及缓存正文片段，未发现泄漏；真实导出与诊断均留在忽略目录。推送结果与完整 HEAD/远端 SHA 在本次最终交接回复列出。

原三份未跟踪 T03 报告不动。只逐文件暂存代码、合成测试、契约和说明，私人数据库/正文/导出/截图/诊断、profile 与凭据均不暂存。安全扫描完整待推送范围后提交推送原功能分支，不合并 master、不强推、不关闭 TLS、不发布稳定版。完成后停止主动开发，保留本机页面供试用。
