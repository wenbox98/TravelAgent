"""Child process, loopback HTTP only, synthetic content only."""

from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/api"))
from pydantic import SecretStr  # noqa: E402
from travel_agent.persistence.database import Database  # noqa: E402
from travel_agent.providers.llm import OpenAICompatibleProvider  # noqa: E402
from travel_agent.research.extractor import EvidenceExtractor  # noqa: E402
from travel_agent.research.retry import retry_saved  # noqa: E402
from travel_agent.research.store import EvidenceStore  # noqa: E402


def deny_external(event, args):
    if event in {"socket.connect", "socket.bind", "socket.sendto"} and args[1][0] != "127.0.0.1":
        raise AssertionError("EXTERNAL_NETWORK_DENIED")
    if event == "socket.getaddrinfo" and args[0] != "127.0.0.1":
        raise AssertionError("EXTERNAL_DNS_DENIED")


sys.addaudithook(deny_external)
observed = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/chat/completions"
        assert data["response_format"] == {"type": "json_object"}
        assert data["store"] is False
        assert '"source_block_ids"' in data["messages"][0]["content"]
        assert '"applicable_conditions"' in data["messages"][0]["content"]
        payload = json.loads(data["messages"][1]["content"])
        assert payload["task"] == "extract_evidence"
        blocks = payload["input"]["blocks"]
        observed.append(True)
        output = {"claims": [{"topic": topic, "kind": "AUTHOR_OPINION", "claim": b["text"],
            "quote": b["text"], "source_block_ids": [b["block_index"]], "confidence": "MEDIUM",
            "applicable_conditions": [], "extraction_basis": "合成 HTTP 夹具"}
            for topic, b in zip(("ROUTE", "EXPERIENCE", "DURATION", "TRANSPORT"), blocks)]}
        body = json.dumps({"model": "synthetic-model", "choices": [{"finish_reason": "stop",
                          "message": {"content": json.dumps(output, ensure_ascii=False)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = HTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with Database(Path(sys.argv[1])) as db:
        store = EvidenceStore(db)
        contents = store.contents.load("xhs:synthetic-a", "owner")
        before = json.dumps(contents, sort_keys=True, ensure_ascii=False)
        provider = OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_port}", "synthetic-model",
                                            SecretStr("synthetic-key"), response_format="json_object")
        result = retry_saved(store, EvidenceExtractor(provider), attempt_id=sys.argv[2], fix_commit="a" * 40)
        after = json.dumps(store.contents.load("xhs:synthetic-a", "owner"), sort_keys=True, ensure_ascii=False)
        result.update(content_unchanged=before == after, digest=sha256(after.encode()).hexdigest(),
                      versions=len(contents), blocks=len(contents[0]["body_blocks"]),
                      body_present=bool(contents[0]["raw_text"]), http_requests=len(observed),
                      no_browser_modules=not any(m.startswith("xhs_sidecar") for m in sys.modules))
        print(json.dumps(result))
finally:
    server.shutdown()
    server.server_close()
    thread.join()
