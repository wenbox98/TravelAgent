# 文档包校验报告

执行时间（UTC）：2026-09-26T11:55:22+00:00

**结果：12/12 项文档校验通过；失败 0 项。**

范围仅为 L0：文档、机器可读契约和合成算例。本命令不执行应用测试；应用测试见各阶段 T00～T03 实现报告。本命令没有登录小红书、获取真实票价或构建 Windows 发行包。

| 校验 | 结果 | 说明 |
|---|---|---|
| JSON_PARSE | PASS | 18 JSON files parsed |
| DOMAIN_SCHEMA | PASS | 71 Draft 2020-12 definitions; format checks enabled for fixtures |
| CONTRACT_REFERENCES | PASS | 121 JSON Schema/OpenAPI reference occurrences resolved offline |
| FIXTURE_SCHEMA | PASS | 27 positive objects accepted; 5 negative objects rejected |
| OPENAPI_STRUCTURAL | PASS | 28 operation IDs, local auth, path parameters, write headers and SSE example checked; structural checks, not a full OpenAPI conformance validator |
| MARKDOWN_LINKS | PASS | 226 relative Markdown link targets exist |
| SQL_DRAFT_SMOKE | PASS | SQLite 3.50.4; 20 declared tables (FTS shadow tables excluded), FK checks, synthetic FTS lookup and cascade deletion passed |
| SYNTHETIC_ARITHMETIC | PASS | Synthetic AC=510min, ABCD=760min, ABD=470min; total 240000–270000 fen; unknown amount remains null |
| TEST_TRACEABILITY | PASS | 137 historical design rows, R01–R14 mapped, 12 task sheets; execution status is tracked in implementation reports |
| SYNTHETIC_CORPUS | PASS | 12 non-live synthetic notes and 30 starter prompt variants; not a completed quality benchmark |
| SAFE_DEFAULTS | PASS | Mock-first defaults; comment expansion off; finite budgets; candidate upstream explicitly not release-approved |
| SOURCE_REGISTER | PASS | 19 referenced source IDs present in source register |

## 不能据此作出的结论

137 行历史设计清单保留 initial_status=NOT_RUN；当前执行情况以任务报告为准，不由此命令更新。合成数据计算通过，不等于真实行程可行。Schema 通过不替代语义、安全和集成测试；OpenAPI 只做结构性检查；本命令 SQL 检查仅为 v1 初始模式的内存试运行，v2 迁移另有 T01 集成测试。

真实小红书登录的执行状态见对应任务报告；本命令不执行或判定登录，JSON 中 live_xhs=NOT_RUN 仅指本次文档校验。精准检索节省比例、授权用途、高德/报价可用性及干净 Windows 安装验收仍待验证。

## 重跑

```sh
python -m pip install -r tools/requirements-docs.txt
python tools/validate_pack.py
```
