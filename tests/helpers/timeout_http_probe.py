"""Scaled deadline integration harness. Loopback only, fabricated text and credential."""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))
from travel_agent.domain.source_policy import private_policy  # noqa: E402
from travel_agent.domain.models import SourcePolicy  # noqa: E402
from travel_agent.persistence.database import Database  # noqa: E402
from travel_agent.providers.diagnostics import Diagnostic  # noqa: E402
from travel_agent.providers.llm import LLMError, OpenAICompatibleProvider  # noqa: E402
from travel_agent.research.extractor import EvidenceExtractor  # noqa: E402
from travel_agent.research.models import DetailMaterial, ResearchRequest  # noqa: E402
from travel_agent.research.recovery import ExtractionRecovery  # noqa: E402
from travel_agent.research.retry import authorize_extra, supervise_extra, run_extra_worker  # noqa: E402
from travel_agent.research.store import EvidenceStore  # noqa: E402
from travel_agent.research.candidate_review import review_candidates  # noqa: E402
from travel_agent.research.grounding import REVIEW_DIMENSIONS  # noqa: E402


def guard(event, args):
    if event in {"socket.connect", "socket.bind", "socket.sendto"} and args[1][0] != "127.0.0.1":
        raise PermissionError("LOOPBACK_ONLY")
    if event == "socket.getaddrinfo" and args[0] != "127.0.0.1":
        raise PermissionError("LOOPBACK_ONLY")


sys.addaudithook(guard)
mode, path = sys.argv[1], Path(sys.argv[2])
if mode == "worker":
    if os.environ["PROBE_MODE"] == "abort":
        os._exit(7)
    with Database(path) as db:
        provider = OpenAICompatibleProvider.from_env()
        run_extra_worker(EvidenceStore(db), provider, os.environ["TRAVEL_RESERVED_ATTEMPT"])
    if os.environ["PROBE_MODE"] == "after_commit":
        time.sleep(4)
    raise SystemExit(0)

if mode == "controller":
    try:
        result = supervise_extra(path, base_attempt_id=os.environ["PROBE_BASE"], fix_commit="a" * 40,
            provider=OpenAICompatibleProvider.from_env(), deadline=float(os.environ["PROBE_DEADLINE"]),
            worker_command=[sys.executable, __file__, "worker", str(path)])
    except ValueError:
        result = {"status": "BLOCKED", "reason": "CONSUMED"}
    print(json.dumps(result))
    raise SystemExit(0)

def clock():
    return datetime(2026, 9, 26, tzinfo=timezone.utc)


body = "合成青谷路线：连接虚构山谷与湖泊。\n作者沿湖步行。\n我自驾用了五天。"
requests = []
stop = threading.Event()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append(True)
        assert request["response_format"] == {"type": "json_object"}
        payload = json.loads(request["messages"][1]["content"])["input"]
        rows = [{"topic": topic, "kind": "AUTHOR_OPINION", "claim": b["text"], "quote": b["text"],
                 "source_block_ids": [b["block_index"]], "confidence": "MEDIUM", "applicable_conditions": [],
                 "extraction_basis": "离线合成测试"}
                for topic, b in zip(("ROUTE", "EXPERIENCE"), payload["blocks"])]
        rows.append(rows[0] | {"claim": "不存在的引文", "quote": "不存在的引文"})
        content = {"model": "synthetic-model", "choices": [{"finish_reason": "stop",
                   "message": {"content": json.dumps({"claims": rows}, ensure_ascii=False)}}]}
        data = json.dumps(content, ensure_ascii=False).encode()
        self.send_response(200)
        if mode != "keepalive":
            self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            if mode == "keepalive":
                while not stop.wait(0.03):
                    self.wfile.write(b"\n")
                    self.wfile.flush()
            elif mode == "stall":
                self.wfile.write(b'{"choices":')
                self.wfile.flush()
                stop.wait(2)
            else:
                stop.wait(0.35)
                self.wfile.write(data)
                self.wfile.flush()
        except (ConnectionError, OSError):
            pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_port
thread = threading.Thread(target=server.serve_forever, daemon=True)
if mode != "opening":
    thread.start()
else:
    server.server_close()
timeout = 0.1 if mode in {"delay_old", "stall"} else 0.25 if mode == "keepalive" else 1.0
deadline = 1.5 if mode in {"keepalive", "after_commit"} else 5.0
os.environ.update(LLM_API_KEY="SECRET_T064_CREDENTIAL", LLM_MODEL="synthetic-model",
    LLM_BASE_URL=f"http://127.0.0.1:{port}", LLM_RESPONSE_FORMAT="json_object",
    LLM_TIMEOUT_SECONDS=str(timeout), PROBE_MODE=mode, PROBE_DEADLINE=str(deadline))
provider = OpenAICompatibleProvider.from_env()


class Failed:
    is_external = True
    is_mock = False
    def structured(self, *args):
        raise LLMError(diagnostic=Diagnostic(stage="TRANSPORT", category="TIMEOUT", http_attempts=1))


try:
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        policy = SourcePolicy(private_policy("owner", now=clock()).to_dict() | {"basis": "SYNTHETIC", "basis_note": "自编离线材料"})
        run = store.begin("probe", 0, ResearchRequest(destination="合成青谷").to_dict(), "owner")
        store.register_policy(run, 0, policy)
        store.reserve_operation(run, 0, "DETAIL", "synthetic:t064", 1)
        content = store.save_source(run, 0, DetailMaterial("synthetic:t064", "自编", body, "PARTIAL_TEXT",
                                   clock().isoformat(), source_type="SYNTHETIC"), policy, "合成青谷")
        kwargs = dict(run_id=run, revision=0, content_id=content, account_scope="owner", policy=policy,
                      batch_id="original-batch", max_attempts=4)
        runner = ExtractionRecovery(store, EvidenceExtractor(Failed(), clock=clock))
        runner.execute(**kwargs)
        old = runner.execute(**kwargs, retry_fix_commit="b" * 40)
        old_rows = [tuple(r) for r in db.connection.execute("SELECT * FROM extraction_attempts ORDER BY attempt_number")]
        before = store.contents.load("synthetic:t064", "owner")
        grant = authorize_extra(store, base_attempt_id=old["attempt_id"], fix_commit="a" * 40,
                                provider=provider, deadline=deadline)
        assert grant["status"] == "GRANTED"
    os.environ["PROBE_BASE"] = old["attempt_id"]
    if mode == "concurrent":
        command = [sys.executable, __file__, "controller", str(path)]
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        results = [json.loads(p.communicate(timeout=15)[0]) for p in children]
        assert all(p.returncode == 0 for p in children)
        result = next(r for r in results if r["status"] != "BLOCKED")
        result["concurrent_blocked"] = sum(r["status"] == "BLOCKED" for r in results)
    else:
        result = supervise_extra(path, base_attempt_id=old["attempt_id"], fix_commit="a" * 40,
            provider=provider, deadline=deadline, worker_command=[sys.executable, __file__, "worker", str(path)])
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        if mode in {"delay_new", "concurrent"}:
            reviewed = review_candidates(store, attempt_id=result["attempt_id"], account_scope="owner", decisions={
                i: {"action": "ACCEPT", "reason_code": "WORK_CONTEXT_VERIFIED",
                    "dimension_checks": {k: True for k in REVIEW_DIMENSIONS}} for i in [0, 1]})
            result["reviewed_status"] = reviewed["status"]
            result["persisted_evidence"] = reviewed["counts"]["persisted_evidence"]
        try:
            reserve = supervise_extra(path, base_attempt_id=old["attempt_id"], fix_commit="a" * 40,
                provider=provider, deadline=deadline, worker_command=[sys.executable, __file__, "worker", str(path)])
            raise AssertionError(reserve["status"])
        except ValueError:
            result["replay_blocked"] = True
        assert authorize_extra(store, base_attempt_id=old["attempt_id"], fix_commit="a" * 40,
                               provider=provider, deadline=deadline)["status"] == "CONSUMED"
        try:
            runner = ExtractionRecovery(store, EvidenceExtractor(Failed(), clock=clock))
            runner.execute(**kwargs, retry_fix_commit="c" * 40)
            raise AssertionError("OLD_RETRY_MUST_REMAIN_EXHAUSTED")
        except ValueError:
            result["old_budget_still_exhausted"] = True
        after_rows = [tuple(r) for r in db.connection.execute("SELECT * FROM extraction_attempts WHERE authorization_id IS NULL ORDER BY attempt_number")]
        auth = db.connection.execute("SELECT * FROM extraction_authorizations").fetchone()
        result.update(source_unchanged=before == store.contents.load("synthetic:t064", "owner"),
            old_rows_unchanged=old_rows == after_rows, old_max=db.connection.execute("SELECT max_attempts FROM extraction_batches").fetchone()[0],
            grant_consumed=bool(auth["consumed_at"]), dispatch_marked=bool(auth["dispatch_started_at"]),
            http_requests=len(requests), timeout_effective=result["diagnostic"]["timeout_seconds"],
            credential_in_database="SECRET_T064_CREDENTIAL" in "\n".join(db.connection.iterdump()),
            browser_absent=not any(m.startswith(("xhs_sidecar", "playwright")) for m in sys.modules))
        before_status = db.connection.execute("SELECT status,diagnostic_json FROM extraction_attempts WHERE authorization_id IS NOT NULL").fetchone()[:]
        time.sleep(0.1)
        result["no_late_overwrite"] = before_status == db.connection.execute("SELECT status,diagnostic_json FROM extraction_attempts WHERE authorization_id IS NOT NULL").fetchone()[:]
    assert "SECRET_T064_CREDENTIAL" not in json.dumps(result)
    print(json.dumps(result))
finally:
    stop.set()
    if thread.is_alive():
        server.shutdown()
        server.server_close()
        thread.join()
