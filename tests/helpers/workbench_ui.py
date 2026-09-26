"""Actual Vue clicks, two real worker HTTP calls to an authored localhost stub, restart."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/api"), str(ROOT / "tests/integration")]


def exercise(folder):
    from pydantic import SecretStr
    from travel_agent.providers.llm import OpenAICompatibleProvider
    from travel_agent.persistence.database import Database
    from test_workbench_pipeline import setup, Provider
    import httpx
    from playwright.sync_api import sync_playwright, expect

    folder.mkdir(parents=True, exist_ok=True)
    fake = Provider()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            item = json.loads(body["messages"][1]["content"])
            task = item["task"]
            requests.append(task)
            if task == "review_evidence_context_v1":
                assert "Independently review" in body["messages"][0]["content"]
            output = fake.structured(task, item["input"], {})
            response = json.dumps(
                {
                    "model": "synthetic",
                    "choices": [
                        {"finish_reason": "stop", "message": {"content": json.dumps(output)}}
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    model = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    model_url = f"http://127.0.0.1:{model.server_address[1]}"
    database = folder / "synthetic.sqlite3"
    control = folder / "control.json"
    with Database(database) as db:
        initial, _ = setup(
            db,
            OpenAICompatibleProvider(
                model_url, "synthetic", SecretStr("fixture"), 120, response_format="json_object"
            ),
        )
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "TRAVEL_LLM_", "OPENAI_"))
    }
    env.update(
        LLM_BASE_URL=model_url,
        LLM_API_KEY="fixture",
        LLM_MODEL="synthetic",
        LLM_TIMEOUT_SECONDS="120",
        LLM_RESPONSE_FORMAT="json_object",
    )
    origin = "http://127.0.0.1:18766"
    processes = []

    def start():
        stream = (folder / "errors.log").open("a", encoding="utf-8")
        proc = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "tests/helpers/workbench_server.py"),
                "--database",
                str(database),
                "--control",
                str(control),
                "--port",
                "18766",
            ],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=stream,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        processes.append(proc)
        with httpx.Client(trust_env=False) as client:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError("TEST_SERVER_FAILED")
                try:
                    if client.get(origin + "/health", timeout=0.3).status_code == 200:
                        return proc
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
        raise RuntimeError("TEST_SERVER_TIMEOUT")

    def stop(proc):
        proc.stdin.write(b"stop\n")
        proc.stdin.flush()
        proc.wait(timeout=15)
        assert json.loads(control.with_suffix(".metrics.json").read_text()) == {
            "outbound": [],
            "workers_alive": 0,
        }

    external = []
    errors = []
    proc = start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=[])
            context = browser.new_context()

            def route(r):
                if urlsplit(r.request.url).netloc != "127.0.0.1:18766":
                    external.append("external")
                    r.abort()
                else:
                    r.continue_()

            context.route("**/*", route)
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(type(e).__name__))
            page.goto(origin + "/bootstrap?ticket=" + json.loads(control.read_text())["ticket"])
            expect(page.get_by_test_id("start-research")).to_be_enabled()

            def state():
                return page.request.get(origin + "/api/v1/preview").json()["session"]

            assert state()["confirmed_option_id"] == initial["confirmed_option_id"] and not requests
            page.get_by_test_id("start-research").click()
            expect(page.get_by_test_id("adopt-materials")).to_be_visible(timeout=30000)
            assert requests == ["select_evidence_references_v1", "review_evidence_context_v1"]
            assert state()["confirmed_option_id"] == initial["confirmed_option_id"]
            page.get_by_test_id("adopt-materials").click()
            expect(page.locator(".option")).to_have_count(3)
            final = state()
            assert final["evidence_count"] == initial["evidence_count"] + 2
            assert final["preferences"]["days"] == 5 and final["preferences"]["driving"] == "NO"
            page.reload()
            expect(page.get_by_role("status")).to_have_text("已从本机恢复选择和资料。")
            assert state() == final
            stop(proc)
            proc = start()
            page.reload()
            expect(page.get_by_role("status")).to_have_text("已从本机恢复选择和资料。")
            assert state() == final and len(requests) == 2
            page.screenshot(path=str(folder / "desktop.png"))
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(folder / "mobile.png"))
            assert not external and not errors
            assert any(
                e["review_status"] == "MODEL_CONTEXT_REVIEWED"
                for o in final["options"]
                for e in o["evidence"]
            )
            browser.close()
            stop(proc)
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
        model.shutdown()
        model.server_close()
    return {
        "status": "PASS",
        "real_loopback_model_requests": len(requests),
        "external_requests": external,
        "page_errors": errors,
        "new_evidence": 2,
        "cross_process_recovery": True,
        "source_kind": "SYNTHETIC_FIXTURE",
        "xhs_real_calls": 0,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    result = exercise(p.parse_args().output)
    print(json.dumps(result))
