# v1.1 第一次发给 Codex 的指令

## 当前持续协作规则（优先于下方历史启动示例）

后续每轮 TravelAgent 开发必须 commit + push 实际工作分支，并核对本地 HEAD 与远端该分支完整 SHA，返回 GitHub commit/compare 链接。开始先确认仓库、分支、remote、upstream 和全部未推送提交；扫描密钥、认证材料、profile、真实 SQLite、原文、图片和调试响应，安全后先推送已有提交，再继续开发。只按明确文件清单暂存，保留原有三份未跟踪 T03 报告和未知改动。不得 force push、自动合并 master、直接在 master 开发或盲目 pull/reset/rebase。失败报告与安全修复也要提交推送；网络/权限/冲突阻塞则如实记录 PUSH_BLOCKED。下方初始分支名是历史示例，不要写死为所有后续任务的目标。

```text
你是 TravelAgent 项目的开发负责人。当前版本是 v1.1“小红书研究 PoC 强化版”。

先检查 Git 状态；如果这是已初始化仓库且不存在同名分支，创建 feature/xhs-research-poc。不要覆盖已有业务代码。

按顺序阅读：
1. AGENTS.md
2. README.md
3. docs/architecture/xhs-poc-analysis.md
4. docs/architecture/xhs-poc-design.md
5. docs/03-xhs-access-login.md
6. docs/04-research-efficiency.md
7. docs/16-xhs-screening-spec.md
8. docs/12-task-plan.md
9. docs/tasks/T00-foundation.md
10. docs/tasks/T01-contracts-mocks.md
11. docs/tasks/T02-xhs-sidecar.md
12. docs/tasks/T03-login.md
13. docs/tasks/T04-research.md

本轮先完成两件事：
A. 审查当前文档/契约是否与 v1.1 PoC 设计冲突，列出冲突，不凭空假设真实小红书接口成功。
B. 完成 T00、T01 的离线工程骨架和 mock；真实 XHS 默认关闭。

核心产品约束：
- 模糊需求先给大致攻略，不先逼用户填完整问卷。
- 小红书连接不让普通用户复制 Cookie/开 DevTools。
- 只读；不做验证码破解、代理/IP/账号轮换、stealth/anti-detect、自动点赞评论发帖私信。
- 研究先查 SQLite/个人资料库，再围绕 Evidence Gap 少量搜索；候选先筛后读；同 source 详情最多一次；证据足够立即停止。
- PoC 默认 max_search_operations=3、max_feed_details=6，仅是应用护栏，不是平台安全阈值。
- FULL_TEXT/PARTIAL_TEXT/SUMMARY_ONLY/METADATA_ONLY 必须严格区分。
- 第二次用户追加“只有5天，而且不想自驾”时，优先复用已有 Evidence，只补缺口。
- Cookie/token/xsec_token/二维码内容不得进入 LLM prompt、普通日志或 Git。

先跑 `python tools/validate_pack.py`。完成 T00/T01 后写真实 implementation report，列出 PASS/FAIL/SKIPPED/BLOCKED；不要把 mock 写成线上成功。未经明确要求不要 push/merge。完成后停止。
```
