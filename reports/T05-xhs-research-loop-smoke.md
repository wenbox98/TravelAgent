# T04.2 + T05 实现与有限 Smoke 报告

状态：离线实现 PASS，最终有限实站尚未运行。

基线 T04.1：`d3645464bfb5a6921bbca137faf37cb27334f35e`。工作分支：`feature/xhs-research-loop`。

用户要求的首步正常 connect 已完成；用户确认“已登录”，本地状态 AUTHENTICATED。随后正常关闭浏览器，保留专用 profile。开发期间没有搜索或详情访问。

实现范围与用途边界见 [T05 设计说明](../docs/architecture/t05-research-loop.md)。本报告将在全部离线门槛通过后填入唯一一轮 1 search / 2 detail 以内的真实观测；失败或暂停照实保留，不增加额度重试。

## 离线结果

统一执行完整 tests（T01～T04 回归 + 本轮新增）：**580 passed / 0 failed / 0 skipped**，4.36 秒，2 条既有依赖弃用提示。首轮 534 passed / 37 failed，修复 Fake 初始化和语义 JSON 比较断言后 579 项通过；再补来源许可在搜索期间过期、排序前重新校验的回归后 580 项通过。类型检查与 Ruff 的初轮问题也已修正。

Ruff PASS；Mypy PASS（31 个模块）；契约测试包含在 pytest；文档包 12 类检查 PASS，171 个链接有效；git diff --check PASS。默认 CLI 运行零浏览器、零网络。没有调用模型服务或真实搜索/详情来修复离线问题。

| 用户验收项 | 覆盖文件与结果 |
|---|---|
| R01 / R02 / R03 | research_service / research_planning：充分缓存零 connect/search/detail、部分缓存定向 gap、查询去重，PASS |
| R04 / R05 | 同 source 一次 detail、LLM 排序失败确定性降级，PASS |
| R06 / R07 / R08 | evidence_extractor：引语和 block 校验、图片缺口、发布日期不替代旅行时间，PASS |
| R09 / R10 / R11 | research_service：提前停止、搜索/详情预算，PASS |
| R12 / R15 | verification 停止、revision/generation 晚返回禁止提交，PASS |
| R13 / R14 | 5 天/不自驾追加条件，保留证据且 0 预算不联网，PASS |
| R16 / R17 | resource_policy / live_observability：图片 abort 仍计 event，document/xhr 等保留，PASS |
| R18 | 同 source 一次技术 fallback 消耗 detail budget，限制/身份错误不 fallback，PASS |
| R19 / R20 | 未测网络 null、敏感 sentinel 与摘要隔离，PASS |
| R21 / R22 | PARTIAL_TEXT 保留、报告列明确缺口、图片缺口缓存保留，PASS |

实现文件：research 下 models / planning / service / store / extractor / live / smoke；providers/llm 与 mock兼容层；v3 SQLite 迁移；显式 scripts/xhs_research_smoke.py。现有 EvidenceBundle / EvidenceClaim / SourcePolicy 及 claim 枚举复用，未新增重复证据契约，也未扩展公共 HTTP 路由。
