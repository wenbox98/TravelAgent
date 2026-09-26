# P01：缓存驱动的本机选择预览

执行日期：2026-09-26。**P01 本机缓存选择预览 PASS**。真实缓存→正常 API→Vue 页面已接通，完成条件选择、预览、确认、改选、取消、刷新与后端重启恢复。G0 仅沿用历史结果，**G1 仍 NOT PASS**，不宣称 G2/G3/G4 或 D1/D2 通过。

基线 `065dab05107a434fcca7c3adda0c66effa16719d` 为祖先；继续 `feature/g1-live-llm-validation`。开工没有未推送旧提交，沙箱内 Git 受本机代理阻塞，获准直接执行远端只读核对后确认远端完整 SHA 与基线一致。未关闭 TLS、未强推、未合并 master。原三份未跟踪 T03 报告保留。

## 实际交付

缓存预览从配置库和 scope 读取，不扫描全盘、不读 Work 手写攻略、无硬编码真实地区/来源/路线/数据库路径。既有 Vue 骨架和 API 同源静态服务得到扩展，没有替换技术栈或添加依赖。

| 符号/位置 | 本次行为 |
|---|---|
| preview.service.PreviewService | 当前研究 revision/report handles、来源策略和审核候选校验，持久用户偏好及选择事务 |
| preview.projection.project/source_schedule/parse_preferences | 复用已审核对象关联，短证据与条件投影，日序和实际耗时分开，有限意图解析 |
| preview.api.install、main.create_app | 同源白名单 API、bootstrap/cookie/CSRF/幂等、安全错误 |
| SourceContentStore.load(purge=False) | 展示只读复查，过期隐藏而不执行删除 |
| SQLite migration 011、Preview DTO | 独立会话/回执，不写研究、正文、审核或额度表 |
| App.vue、EvidenceList.vue、api.ts、style.css | 缓存入口、草案/日段、条件依据、选择差异、恢复与窄屏布局 |
| scripts/cached_preview.prepare_workspace | 原库只读 online backup，副本升级前备份，恢复同一工作目录 |

契约、备份和回滚详见 [P01 设计](../docs/architecture/p01-cached-preview.md)。T06/T07/T09 仅标注本次子范围，原任务未整体完成。

## 真实私人副本验收

验收使用隔离的私人 SQLite 副本。迁移前已保存原库所有表行摘要；副本 v10→v11 后，除 schema_version 与新增选择表外，原表摘要完全相同，外键错误 0。原库仍保持原版本，25 条 Evidence、3 个 SourceContent、73 个 BodyBlock、全部旧授权/失败/操作账本不改写。

页面实际可见 **5 个来源内对象：1 个七日作者草案对象 + 4 个攻略日段对象**。这不是五条完整备选路线，也未把五个日段凑成已确认的五天四晚。单独 Day1/Day4 不推算全程时间；作者七个连续日序标 DERIVED_FROM_SOURCE_SCHEDULE，实际总天数、车程、停留与用户适配均未知。独立来源数未知，记录数不等于独立事实数。

页面中的地点顺序、来源计划/攻略性质、交通与季节条件、必要短摘录全部由程序从审核链生成；标题天数没有自动成为正文证据。旧记录缺新角色枚举的保留 UNKNOWN 和原有条件，不补写历史审核。

| 实际操作 | 结果 |
|---|---|
| 从已有研究列表打开，预算/人数未知 | PASS；4 个可选既有研究记录，选定研究有 25 条证据/3 来源/5 对象 |
| 保存五天、不想自己开车 | PASS；只更新用户偏好，所有来源字段和引用不变，不重复问已知条件 |
| 不自驾适配提示 | PASS；列门到门、移动、停留与接驳缺口；不声称公共交通可行或绝对不可行，包车未知 |
| 预览 A→确认 A | PASS；明确是兴趣确认，feasibility 仍 UNVERIFIED |
| 预览 B→取消 | PASS；确认项仍 A |
| 再预览 B→确认 | PASS；保留五天/不自驾并提交 B，展示兴趣与缺口增删保留 |
| 页面刷新 | PASS；选择/偏好/证据/缺口一致 |
| 停止第一个后端、启动第二个后端 | PASS；复用本机会话与私人副本，无研究触发，恢复非空结果完全一致 |
| 未命中缓存 | PASS；保留输入并提示未启用新资料研究，无合成回填 |
| 桌面与 390px 窄屏 | PASS；无横向溢出，私人截图仅在忽略目录 |

首次验收通过后，补充七日对象优先展示、恢复研究选择器及改选预览定位，再用最终页面完整复验，通过结果一致。每轮各启动一个普通本机 UI 测试浏览器，与 XHS BrowserSession 严格区分。没有平台页面、搜索、详情、图片或模型请求。

## 网络与安全证据

最终一次验收的浏览器页面请求事件 **22 次，均为本机页面/API/静态资源**；另有仅 loopback 的健康等待和 API 状态断言，不把 22 称为整次进程总请求数。页面外部资源请求 0、脚本异常 0；上下文路由拒绝外部地址，未发生拒绝尝试。普通 UI 浏览器 1 个，XHS 浏览器 0。

两个后端验收进程安装 Python socket 审计防线，启动前仅创建 asyncio 内部 wakeup；运行期间 socket connect/DNS/sendto 尝试列表均为空。禁止 live reader/sidecar 导入的边界没有被触发，已加载模块中也没有 live reader/sidecar。单元测试另以禁止构造模型/ResearchService 的桩检查正常 API。

因此本轮项目 XHS connect/search/detail/browser=**0/0/0/0**，sidecar=0，外部 model/embedding/reviewer/ranking/report=0，地图/报价=0。没有重置或调用任何旧预算。响应中的 business_calls 表达此缓存路径未派发业务调用；实际支撑另来自审计防线、模块边界、页面请求记录及数据库旧账本摘要，不能把常量 DTO 当作网络测量。

整台电脑 wire 流量、浏览器后台流量、总传输字节均 **NOT_MEASURED**。GitHub 核对与代码推送另计，不声称电脑完全离线。无依赖安装，无小红书/模型连通性探测。

Host/Origin、单次票据、HttpOnly cookie、CSRF、幂等冲突、scope隔离、revision过期、最新策略撤销、审核状态变化和安全错误均有离线测试；真实页面只展示白名单数据，无 API key、Cookie、xsec_token、原始模型响应、完整笔记或数据库路径。合成来源标题及输入 HTML 通过 Vue 文本插值显示，未执行为 DOM。链接无敏感参数且未被自动打开。

## 实际验证

先新增关键失败测试，首跑 8 项因缺少 preview 模块失败，随后实现。过程中修正待审夹具的非法角色关联、合成夹具的 source_type 不一致；未放松审核条件。第一次 Vite 构建被沙箱子进程权限阻止，获准后使用原有锁定依赖构建通过。

- 全 Python 单元/集成/契约/安全/本机 e2e：最终 **907 PASS**（31.25 秒），两项依赖弃用警告。
- Ruff PASS；Mypy PASS（包含新 preview，共 51 文件）。
- `pnpm build` PASS，包含 vue-tsc 类型检查和 Vite 生产构建。
- 真实私人副本 `tests/helpers/preview_ui.py`：两次完整操作及进程恢复 PASS；原库/profile/历史行摘要复查 PASS。
- 文档/契约 **12/12 PASS**（64 定义、24 API 操作）；git diff --check PASS。

profile 初次沙箱枚举因访问范围而静默返回零文件，不能用其摘要证明不变。已保留原检查记录并纠正：取得只读执行权限后可见 975 个文件，最新写入为 04:53:35 UTC，早于本轮迁移前检查 06:55:21 UTC；未启动任何专用 profile 进程，未读取 Cookie 内容。profile 保留且无本轮写入证据，**开工逐文件摘要比较为 NOT_MEASURED**。普通本机页面由默认 Edge 打开，与专用 XHS profile 无关。另修正了一处 Mypy 容器类型注解和前端文件末尾空行，最终检查通过。

## 本机启动

在仓库根目录、已有锁定依赖的 Windows 开发环境，使用自己的配置路径和 scope（真实私有值不写 Git 报告）：

```powershell
Push-Location apps\web
pnpm build
Pop-Location
.venv\Scripts\python.exe scripts\cached_preview.py --source-database <已有缓存.sqlite3> --workspace .local\cached-preview --account-scope <本地scope> --port 8765 --open
```

`--open` 只打开本机一次性入口，自动跳至 **http://127.0.0.1:8765/**；也可从终端复制五分钟有效的入口到浏览器。该本机票据不提交报告、不分享。Ctrl+C 停止后原命令恢复副本中的选择。用户最终交付消息提供本机实际可复制参数。

## 下一阶段与停止

正常缓存展示已经接通。普通 EvidenceExtractor/ResearchService 默认仍为 v2，T06.6 worker 显式 v3；本轮未接新资料研究 v3。上下文审核仍为 Work-assisted，不宣称无人值守审核。

后续只记录：所选方向的真实移动/停留/接驳可行性、普通入口 v3 与审核边界、KnowledgeCard 及原文独立生命周期。本轮不执行，不增加外部请求；原文不删，G1 缺口保留。

## Git 收尾

后端/契约提交 `8588a720c0208a6367f755867b50b31ce530a791`；Vue/本机 e2e 提交 `d00dd2a71ae87e1831a8d557cbc6e61cb8052fee`，验收和使用说明单独提交。所有变更按明确清单暂存。完整基线之后的提交内容版本和 staged 内容均扫描：配置密钥、本机预览会话秘密、运行文件/数据库/图片/二进制、三篇缓存中 932 个连续 32 字原文片段，发现均为 0。真实数据库、正文、私人截图及临时启动入口未入 Git。

预览实际正常启动命令已运行，127.0.0.1:8765 的 health=ok；普通默认浏览器打开了本机入口，服务保留供用户查看。没有新增业务外部能力。远端推送与最终完整 SHA 对比在最终交付消息登记；禁止强推、合并 master 或关闭 TLS 校验。

相对指定基线的 git diff 摘要：**37 files changed, 2718 insertions(+), 60 deletions(-)**。主体为缓存投影/选择事务、严格 DTO 契约、Vue 页面、合成与本机测试及匿名说明；旧三份 T03 报告不在差异中。
