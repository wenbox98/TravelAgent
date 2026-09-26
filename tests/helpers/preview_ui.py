"""Exercise the actual built Vue/API; only loopback UI requests are permitted."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]


def exercise(database, scope, mode, research, output, count, port):
    output.mkdir(parents=True, exist_ok=True)
    control = output / "server-control.json"
    origin = f"http://127.0.0.1:{port}"
    processes = []
    def start():
        stream = (output / "server-errors.log").open("a", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(ROOT / "tests/helpers/preview_server.py"),
            "--database", str(database), "--scope", scope, "--mode", mode,
            "--control", str(control), "--port", str(port)], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=stream, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        processes.append(proc)
        with httpx.Client(trust_env=False) as client:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError("PREVIEW_SERVER_FAILED; inspect private server-errors.log")
                try:
                    if client.get(origin + "/health", timeout=.3).status_code == 200:
                        stream.close()
                        return proc
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
        raise RuntimeError("PREVIEW_SERVER_NOT_READY")
    def stop(proc):
        proc.stdin.write(b"stop\n")
        proc.stdin.flush()
        proc.wait(timeout=15)
        assert proc.returncode == 0
        metrics = json.loads(control.with_suffix(".metrics.json").read_text(encoding="utf-8"))
        assert metrics == {"outbound_attempts": [], "live_imports": []}
        return metrics
    external, requests, errors = [], [], []
    result = {}
    proc = start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=[])
            context = browser.new_context(viewport={"width": 1360, "height": 1000}, service_workers="block")
            def route(r):
                parts = urlsplit(r.request.url)
                if parts.scheme != "http" or parts.netloc != f"127.0.0.1:{port}":
                    external.append(parts.netloc)
                    r.abort()
                else:
                    r.continue_()
            context.route("**/*", route)
            page = context.new_page()
            page.on("request", lambda r: requests.append(urlsplit(r.url).path))
            page.on("pageerror", lambda e: errors.append(type(e).__name__))
            page.goto(origin + "/bootstrap?ticket=" + json.loads(control.read_text(encoding="utf-8"))["ticket"])
            expect(page.locator("#research")).to_be_enabled()
            page.locator("#research").select_option(research)
            page.locator("#request").fill("国庆想出行")
            page.get_by_role("button", name="查看本地草案", exact=True).click()
            expect(page.locator(".option")).to_have_count(count)
            def state():
                return page.request.get(origin + "/api/v1/preview").json()["session"]
            initial = state()
            assert initial["mode"] == mode and initial["options"]
            assert page.locator("#source-injected").count() == 0
            assert all(o["verified_duration_days"] is None for o in initial["options"])
            page.get_by_role("button", name="5 天", exact=True).click()
            page.locator("#driving").select_option("NO")
            page.get_by_role("button", name="保存条件", exact=True).click()
            expect(page.get_by_role("status")).to_have_text("已保存本次选择。")
            selected = state()
            assert selected["preferences"]["days"] == 5 and selected["preferences"]["driving"] == "NO"
            assert selected["options"] == initial["options"] and not selected["questions"]
            a, b = [o["option_id"] for o in initial["options"][:2]]
            def preview(option):
                page.locator(f'[data-option-id="{option}"] button').click()
                expect(page.get_by_test_id("proposal")).to_be_visible()
            def confirm():
                page.get_by_role("button", name="确认兴趣方向", exact=True).click()
                expect(page.get_by_test_id("proposal")).to_have_count(0)
            preview(a)
            confirm()
            assert state()["confirmed_option_id"] == a
            preview(b)
            assert state()["confirmed_option_id"] == a and state()["preview"]["option_id"] == b
            page.get_by_role("button", name="取消改选", exact=True).click()
            expect(page.get_by_test_id("proposal")).to_have_count(0)
            assert state()["confirmed_option_id"] == a
            preview(b)
            confirm()
            final = state()
            assert final["confirmed_option_id"] == b
            page.reload()
            expect(page.get_by_role("status")).to_have_text("已从本机恢复选择和资料。")
            assert state() == final
            first_metrics = stop(proc)
            proc = start()
            page.reload()
            expect(page.get_by_role("status")).to_have_text("已从本机恢复选择和资料。")
            assert state() == final
            page.screenshot(path=str(output / "desktop.png"), full_page=False)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(output / "mobile.png"), full_page=False)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert not errors and not external
            # Vue text interpolation must not turn arbitrary request markup into DOM.
            page.locator("#research").select_option("")
            page.locator("#request").fill('<b id="injected">没有缓存的合成新地区</b>')
            page.get_by_role("button", name="查看本地草案", exact=True).click()
            expect(page.get_by_test_id("cache-miss")).to_be_visible()
            assert page.locator("#injected").count() == 0
            assert state()["input_text"].startswith("<b") and state()["options"] == []
            # Restore the accepted session as most recently used through the normal API.
            index = page.request.get(origin + "/api/v1/preview").json()
            restored = page.request.post(origin + "/api/v1/preview/sessions/" + final["session_id"],
                headers={"Origin": origin, "X-CSRF-Token": index["csrf_token"], "Idempotency-Key": "ui-restore-" + str(time.time_ns())},
                data={"action": "cancel", "expected_revision": final["revision"]})
            assert restored.ok
            result = {"status": "PASS", "mode": mode, "options": count, "evidence_count": final["evidence_count"],
                "source_count": final["source_count"], "schedule_counts": [o["source_schedule"]["day_count"] for o in final["options"]],
                "five_days_no_driving": True, "preview_cancel_confirm": True, "refresh": True, "restart": True,
                "mobile_no_overflow": True, "xss_text_escaped": True, "external_page_requests": external,
                "local_page_requests": len(requests), "page_errors": errors, "first_process": first_metrics,
                "second_process": stop(proc), "business_calls": final["business_calls"],
                "options_digest": sha256(json.dumps(final["options"], sort_keys=True).encode()).hexdigest(),
                "local_ui_browser_sessions": 1, "xhs_browser_sessions": 0}
            browser.close()
    finally:
        for item in processes:
            if item.poll() is None:
                item.terminate()
                item.wait(timeout=10)
    (output / "acceptance.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--mode", choices=["SYNTHETIC_DEMO", "CACHED_PRIVATE_PREVIEW"], required=True)
    parser.add_argument("--research", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    print(json.dumps(exercise(args.database, args.scope, args.mode, args.research, args.output, args.count, args.port)))
