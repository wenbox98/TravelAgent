#!/usr/bin/env python3
"""Offline document/fixture checks. This is NOT an application or live-service test.
Run from the repository root: python tools/validate_pack.py
Dependencies: python -m pip install -r tools/requirements-docs.txt
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    import yaml
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:
    print(f"Missing dependency: {exc}. Run: python -m pip install -r tools/requirements-docs.txt", file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[dict[str, object]] = []
COUNTS: dict[str, int] = {}


def load_json(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check(name: str, fn) -> None:
    try:
        detail = fn()
        RESULTS.append({"check": name, "status": "PASS", "detail": str(detail or "OK")})
        print(f"PASS {name}: {detail or 'OK'}")
    except Exception as exc:
        RESULTS.append({"check": name, "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"})
        print(f"FAIL {name}: {exc}", file=sys.stderr)


def check_json():
    paths = list(ROOT.glob("*.json")) + [p for folder in ("contracts", "fixtures", "config") for p in (ROOT / folder).rglob("*.json")]
    for file in paths:
        json.loads(file.read_text(encoding="utf-8"))
    COUNTS["json_files_checked"] = len(paths)
    return f"{len(paths)} JSON files parsed"


DOMAIN = load_json("contracts/domain.schema.json")
API = yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text(encoding="utf-8"))


def validator(definition: str):
    require(definition in DOMAIN["$defs"], f"Unknown definition: {definition}")
    schema = dict(DOMAIN)
    schema["$ref"] = f"#/$defs/{definition}"
    return Draft202012Validator(schema, format_checker=FormatChecker())


def check_schema():
    Draft202012Validator.check_schema(DOMAIN)
    definitions = DOMAIN["$defs"]
    for definition in definitions.values():
        Draft202012Validator.check_schema(definition)
    COUNTS["domain_definitions"] = len(definitions)
    return f"{len(definitions)} Draft 2020-12 definitions; format checks enabled for fixtures"


def resolve_pointer(document, fragment: str):
    require(fragment.startswith("/"), f"Unsupported JSON pointer: {fragment}")
    for part in fragment[1:].split("/"):
        key = unquote(part).replace("~1", "/").replace("~0", "~")
        document = document[int(key)] if isinstance(document, list) else document[key]
    return document


def walk_refs(value, current: str):
    count = 0
    if isinstance(value, dict):
        if "$ref" in value:
            ref = value["$ref"]
            require("#" in ref, f"Expected explicit pointer: {ref}")
            filepart, fragment = ref.split("#", 1)
            require(not urlsplit(filepart).scheme, f"Remote reference not allowed in offline contracts: {ref}")
            if not filepart:
                target = DOMAIN if current == "domain" else API
            else:
                require(filepart == "./domain.schema.json", f"Unknown reference file: {filepart}")
                target = DOMAIN
            resolve_pointer(target, fragment)
            count += 1
        for child in value.values():
            count += walk_refs(child, current)
    elif isinstance(value, list):
        for child in value:
            count += walk_refs(child, current)
    return count


def check_refs():
    count = walk_refs(DOMAIN, "domain") + walk_refs(API, "api")
    return f"{count} JSON Schema/OpenAPI reference occurrences resolved offline"


def check_fixtures():
    cases = load_json("fixtures/schema-cases.json")
    for case in cases["positive"]:
        validator(case["schema"]).validate(load_json(case["file"]))
    for case in cases["negative"]:
        errors = list(validator(case["schema"]).iter_errors(case["data"]))
        require(bool(errors), f"Negative fixture unexpectedly accepted: {case['name']}")
    extra = 0
    for policy in load_json("fixtures/policies.json")["policies"]:
        validator("SourcePolicy").validate(policy)
        extra += 1
    for note in load_json("fixtures/research-pool.json")["notes"]:
        validator("NoteCandidate").validate(note["candidate"])
        extra += 1
    budget = load_json("fixtures/budget-case.json")
    for line in budget["lines"] + [budget["unknown_variant"]]:
        validator("BudgetLine").validate(line)
        extra += 1
    COUNTS["positive_contract_fixtures"] = len(cases["positive"]) + extra
    COUNTS["negative_contract_fixtures"] = len(cases["negative"])
    return f"{len(cases['positive']) + extra} positive objects accepted; {len(cases['negative'])} negative objects rejected"


def check_openapi():
    require(API["openapi"].startswith("3.1."), "Expected OpenAPI 3.1")
    require(API.get("security") == [{"LocalSession": []}], "Missing local session security default")
    names = set()
    count = 0
    for path, item in API["paths"].items():
        require(path.startswith("/api/v1/"), f"Unexpected business path: {path}")
        for method, operation in item.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            oid = operation["operationId"]
            require(oid not in names, f"Duplicate operationId: {oid}")
            names.add(oid)
            parameters = item.get("parameters", []) + operation.get("parameters", [])
            actual = {p["name"] for p in parameters if p.get("in") == "path" and p.get("required")}
            require(actual == set(re.findall(r"\{([^}]+)\}", path)), f"Path parameter mismatch: {path}")
            if method in {"post", "put", "patch", "delete"}:
                headers = {p["name"] for p in parameters if p.get("in") == "header" and p.get("required")}
                require({"Idempotency-Key", "X-CSRF-Token"} <= headers, f"Missing write safety headers: {path}")
            require(any(str(k).startswith("2") for k in operation["responses"]), f"No success response: {oid}")
            for response in operation["responses"].values():
                stream = response.get("content", {}).get("text/event-stream", {})
                if "example" in stream:
                    lines = stream["example"].splitlines()
                    body = next(line[6:] for line in lines if line.startswith("data: "))
                    validator("SafeEvent").validate(json.loads(body))
            count += 1
    COUNTS["http_operations"] = count
    return f"{count} operation IDs, local auth, path parameters, write headers and SSE example checked; structural checks, not a full OpenAPI conformance validator"


def check_links():
    count = 0
    for file in list(ROOT.glob("*.md")) + [p for folder in ("docs", "reports", "prompts") for p in (ROOT / folder).rglob("*.md")]:
        text = file.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for target in re.findall(r"\]\(([^\s)]+)(?:\s+[^)]*)?\)", text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local = unquote(target.split("#", 1)[0])
            resolved = (file.parent / local).resolve()
            require(resolved.is_relative_to(ROOT), f"Link outside package: {file.relative_to(ROOT)} -> {target}")
            require(resolved.exists(), f"Missing link: {file.relative_to(ROOT)} -> {target}")
            count += 1
    return f"{count} relative Markdown link targets exist"


def check_sql():
    con = sqlite3.connect(":memory:")
    try:
        sql = (ROOT / "contracts/database.sql").read_text(encoding="utf-8")
        con.executescript(sql)
        require(con.execute("PRAGMA foreign_key_check").fetchall() == [], "Foreign key check failed")
        require(con.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Integrity check failed")
        # Demonstrate FK enforcement without treating this as an implemented repository test.
        try:
            con.execute("INSERT INTO claims(claim_id,source_id,topic,text,kind,locator,support) VALUES(?,?,?,?,?,?,?)", ("bad", "absent", "test", "synthetic", "FACT", "text:1", "UNKNOWN"))
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("Orphan claim unexpectedly accepted")
        con.execute("INSERT INTO source_policies VALUES(?,?,?,?,?)", ("synthetic", 1, "{}", None, None))
        con.execute("INSERT INTO sources(source_id,provider,account_scope,completeness,policy_id,policy_version,fetched_at,is_synthetic) VALUES(?,?,?,?,?,?,?,?)", ("s1", "synthetic", "local", "FULL_TEXT", "synthetic", 1, "2026-09-22", 1))
        con.execute("INSERT INTO chunks(chunk_id,source_id,text,pretokenized_text,metadata_json,content_hash) VALUES(?,?,?,?,?,?)", ("c1", "s1", "合成旅行", "合成 旅行", "{}", "synthetic"))
        con.execute("INSERT INTO chunks_fts(chunk_id,pretokenized_text) VALUES(?,?)", ("c1", "合成 旅行"))
        require(con.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH '旅行'").fetchone()[0] == 1, "Pretokenized FTS smoke failed")
        con.execute("DELETE FROM sources WHERE source_id='s1'")
        require(con.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0, "Cascade delete failed")
        require(con.execute("SELECT count(*) FROM chunks_fts").fetchone()[0] == 0, "FTS delete trigger failed")
        require(con.execute("PRAGMA foreign_key_check").fetchall() == [], "Foreign key check failed after fixture changes")
        declared = len(re.findall(r"CREATE (?:VIRTUAL )?TABLE\s", sql, flags=re.I))
        COUNTS["declared_tables_including_fts"] = declared
        return f"SQLite {sqlite3.sqlite_version}; {declared} declared tables (FTS shadow tables excluded), FK checks, synthetic FTS lookup and cascade deletion passed"
    finally:
        con.close()


def check_arithmetic():
    itinerary = load_json("fixtures/itinerary-case.json")
    require(itinerary["is_synthetic"] is True, "Itinerary must be synthetic")
    for case in itinerary["cases"]:
        n = len(case["selected"])
        minutes = sum(itinerary["activities"][x] for x in case["selected"]) + itinerary["rest_minutes"] + (n + 1) * itinerary["leg_minutes"]
        require(minutes == case["expected_minutes"], f"Minute mismatch: {case}")
        require((minutes <= itinerary["available_minutes"]) == case["expected_feasible"], "Feasibility mismatch")
        require(itinerary["available_minutes"] - minutes == case["remaining_minutes"], "Remaining time mismatch")
    budget = load_json("fixtures/budget-case.json")
    for key in ["min_fen", "max_fen"]:
        total = sum(line["quantity"] * line["unit_amount"][key] for line in budget["lines"] if line["included_in_line_id"] is None and line["category"] != "DEPOSIT")
        require(total == budget["expected_total"][key], f"Budget {key} mismatch")
        require(total // budget["party_size"] == budget["expected_per_person"][key], "Per-person mismatch")
    u = budget["unknown_variant"]
    require(u["status"] == "UNKNOWN" and u["unit_amount"]["min_fen"] is None and u["unit_amount"]["max_fen"] is None, "Unknown amount must not become zero")
    require(budget["unknown_expected_completeness"] == "PARTIAL", "Unknown completeness mismatch")
    return "Synthetic AC=510min, ABCD=760min, ABD=470min; total 240000–270000 fen; unknown amount remains null"


def check_matrix():
    with (ROOT / "contracts/test-matrix.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    require(len(rows) == len({r["test_id"] for r in rows}), "Duplicate test ID")
    tasks = {f.stem[:3] for f in (ROOT / "docs/tasks").glob("T*.md")}
    reqs = set()
    for row in rows:
        require(row["initial_status"] == "NOT_RUN", "Do not label designed application tests as already passed")
        require(set(row["task_ids"].split(";")) <= tasks, "Unknown task in test matrix")
        reqs.update(row["requirement_ids"].split(";"))
    require({f"R{i:02d}" for i in range(1, 15)} <= reqs, "Incomplete requirement mapping")
    require(tasks == {f"T{i:02d}" for i in range(12)}, "Expected 12 task sheets")
    COUNTS["designed_application_test_cases_not_run"] = len(rows)
    COUNTS["codex_task_sheets"] = len(tasks)
    return f"{len(rows)} historical design rows, R01–R14 mapped, 12 task sheets; execution status is tracked in implementation reports"


def check_synthetic_corpus():
    pool = load_json("fixtures/research-pool.json")
    scenarios = load_json("fixtures/research-scenarios.json")
    require(pool["is_synthetic"] and scenarios["is_synthetic"], "Missing synthetic flags")
    for note in pool["notes"]:
        candidate = note["candidate"]
        require(candidate["is_synthetic"], "Real note unexpectedly present")
        require((urlsplit(candidate["canonical_url"]).hostname or "").endswith(".invalid"), "Fixture URL must be non-live")
    require(len(pool["notes"]) == 12, "Expected 12 synthetic notes")
    require(len(scenarios["scenarios"]) == 30 and bool(scenarios["warning"]), "Starter scenarios must explain evaluation limitations")
    COUNTS["synthetic_notes"] = len(pool["notes"])
    COUNTS["starter_prompt_scenarios_not_benchmark"] = len(scenarios["scenarios"])
    return "12 non-live synthetic notes and 30 starter prompt variants; not a completed quality benchmark"


def check_guardrails():
    cfg = load_json("config/defaults.json")
    require(cfg["mode"] == "mock" and cfg["xhs_live_enabled"] is False, "Live must be opt-in")
    require(cfg["bind_host"] == "127.0.0.1" and cfg["xhs_concurrency"] == 1, "Local serialized default required")
    require(cfg["load_all_comments"] is False and cfg["collect_video"] is False, "Unexpected bulk-read default")
    require(cfg["remote_auth_probes_per_generation"] == 2, "Auth probe budget mismatch")
    for phase in ["overview_budget", "refinement_budget"]:
        for key, value in cfg[phase].items():
            require(value <= cfg["session_hard_budget"][key], f"Phase exceeds session budget: {key}")
    lock = load_json("contracts/upstream-lock.json")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", lock["candidate_commit"])), "Invalid candidate commit")
    require(lock["approved_for_release"] is False and lock["artifact_sha256"] is None, "Unverified upstream must not be marked released")
    require(lock["official_xhs_oauth_scope_status"].startswith("UNKNOWN"), "Unverified OAuth status changed")
    return "Mock-first defaults; comment expansion off; finite budgets; candidate upstream explicitly not release-approved"


def check_sources():
    source_text = (ROOT / "docs/14-sources.md").read_text(encoding="utf-8")
    used = set()
    for file in (ROOT / "docs").rglob("*.md"):
        used.update(re.findall(r"\[(S\d{2})\]", file.read_text(encoding="utf-8")))
    for ident in used:
        require(ident in source_text, f"Missing source record: {ident}")
    COUNTS["main_documents"] = len(list((ROOT / "docs").glob("[0-9][0-9]-*.md")))
    return f"{len(used)} referenced source IDs present in source register"


def main() -> int:
    for name, fn in [
        ("JSON_PARSE", check_json), ("DOMAIN_SCHEMA", check_schema),
        ("CONTRACT_REFERENCES", check_refs), ("FIXTURE_SCHEMA", check_fixtures),
        ("OPENAPI_STRUCTURAL", check_openapi), ("MARKDOWN_LINKS", check_links),
        ("SQL_DRAFT_SMOKE", check_sql), ("SYNTHETIC_ARITHMETIC", check_arithmetic),
        ("TEST_TRACEABILITY", check_matrix), ("SYNTHETIC_CORPUS", check_synthetic_corpus),
        ("SAFE_DEFAULTS", check_guardrails), ("SOURCE_REGISTER", check_sources),
    ]:
        check(name, fn)
    passed = sum(r["status"] == "PASS" for r in RESULTS)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = {"generated_at_utc": stamp, "scope": "L0_DOCUMENT_CONTRACT_SYNTHETIC_ONLY", "checks": RESULTS, "counts": COUNTS,
              "passed": passed, "failed": len(RESULTS) - passed,
              "application_tests": "OUT_OF_SCOPE_SEE_IMPLEMENTATION_REPORTS", "live_xhs": "NOT_RUN", "supplier_live": "NOT_RUN", "windows_release": "NOT_RUN"}
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "document-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 文档包校验报告", "", f"执行时间（UTC）：{stamp}", "", f"**结果：{passed}/{len(RESULTS)} 项文档校验通过；失败 {len(RESULTS) - passed} 项。**", "",
             "范围仅为 L0：文档、机器可读契约和合成算例。本命令不执行应用测试；应用测试见各阶段 T00～T03 实现报告。本命令没有登录小红书、获取真实票价或构建 Windows 发行包。", "",
             "| 校验 | 结果 | 说明 |", "|---|---|---|"]
    for r in RESULTS:
        detail = str(r["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['check']} | {r['status']} | {detail} |")
    lines += ["", "## 不能据此作出的结论", "",
              f"{COUNTS.get('designed_application_test_cases_not_run', 0)} 行历史设计清单保留 initial_status=NOT_RUN；当前执行情况以任务报告为准，不由此命令更新。合成数据计算通过，不等于真实行程可行。Schema 通过不替代语义、安全和集成测试；OpenAPI 只做结构性检查；本命令 SQL 检查仅为 v1 初始模式的内存试运行，v2 迁移另有 T01 集成测试。", "",
              "真实小红书连接、精准检索节省比例、授权用途、高德/报价可用性及干净 Windows 安装验收均保持 NOT_RUN/待验证。", "",
              "## 重跑", "", "```sh", "python -m pip install -r tools/requirements-docs.txt", "python tools/validate_pack.py", "```", ""]
    (out / "document-validation.md").write_text("\n".join(lines), encoding="utf-8")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
