# XHS PoC 真实 Smoke Test 报告模板

> 真实测试前保持 NOT_RUN。禁止记录 Cookie、token、xsec_token、二维码内容或真实小红书原文数据集。

- 测试日期：
- 应用 commit：
- upstream commit：
- 平台/网络环境：
- 输入：`国庆从成都去川西玩`
- live 模式是否显式开启：

## 登录
- 首次连接：PASS / FAIL / BLOCKED / NOT_RUN
- 是否要求复制 Cookie：必须为否
- 是否遇到 verification/challenge：
- 重启后会话复用：

## 研究消耗
- search_operations：
- detail_operations：
- page_navigations：
- site_http_requests：COMPLETE/PARTIAL/UNAVAILABLE + 数值
- cache_hits / cache_misses：
- candidate_count / selected_candidate_count：
- evidence_count：
- stop_reason：
- insufficient_evidence：

## Evidence 完整度
- FULL_TEXT：
- PARTIAL_TEXT：
- SUMMARY_ONLY：
- METADATA_ONLY：

## 增量复用
追加输入：`我只有5天，而且不想自驾`
- 新增 search/detail：
- 复用 Evidence：
- 只补了哪些 gap：

## 异常与限制
- 登录/验证问题：
- 页面解析问题：
- 证据缺口：
- 下一步建议：
