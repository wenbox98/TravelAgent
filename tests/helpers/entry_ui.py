"""Built workbench root entry acceptance, synthetic database and loopback only."""

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))


def main():
    from travel_agent.preview.local_entry import entry_proof

    output = Path(sys.argv[1])
    output.mkdir(exist_ok=True)
    control = output / "control.json"
    origin = "http://127.0.0.1:18769"
    log = (output / "server.log").open("w", encoding="utf8")
    proc = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tests/helpers/preview_server.py"),
            "--database",
            str(output / "synthetic.sqlite3"),
            "--scope",
            "owner",
            "--mode",
            "CACHED_PRIVATE_PREVIEW",
            "--control",
            str(control),
            "--port",
            "18769",
            "--product",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=log,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    external = []
    try:
        with httpx.Client(trust_env=False) as client:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError("ENTRY_SERVER_FAILED")
                try:
                    if client.get(origin + "/health", timeout=0.3).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("ENTRY_SERVER_NOT_READY")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=[])
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900}, service_workers="block"
                )

                def guard(r):
                    parts = urlsplit(r.request.url)
                    if parts.netloc != "127.0.0.1:18769":
                        external.append(parts.netloc)
                        r.abort()
                    else:
                        r.continue_()

                context.route("**/*", guard)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(type(e).__name__))
                page.goto(origin)
                expect(
                    page.get_by_role("heading", name="重新打开本机入口", exact=True)
                ).to_be_visible()
                page.goto(origin + "/bootstrap?ticket=expired-synthetic")
                expect(
                    page.get_by_role("heading", name="重新打开本机入口", exact=True)
                ).to_be_visible()
                assert page.get_by_role("button", name="查看本地草案", exact=True).count() == 0
                idea = page.get_by_label("你想去哪里，怎么玩？", exact=True)
                idea.fill("我想去合成北域玩7天")
                expect(page.get_by_role("button", name="连接后才能提交", exact=True)).to_be_disabled()
                idea.press("Control+Enter")
                expect(page.locator("#intake-reason")).to_contain_text("未提交")
                expect(page.locator("#intake-hint")).not_to_contain_text("Ctrl")
                page.reload()
                expect(idea).to_have_value("我想去合成北域玩7天")
                # Owner CLI uses a private local key; the browser never receives proof.
                renewed = client.post(
                    origin + "/local-entry",
                    headers={
                        "X-Local-Entry-Proof": entry_proof(control.with_suffix(".key").read_bytes())
                    },
                )
                assert renewed.status_code == 200
                page.goto(renewed.json()["entry_url"])
                expect(page.get_by_role("button", name="查资料并生成旅行建议", exact=True)).to_be_enabled()
                expect(idea).to_have_value("我想去合成北域玩7天")
                # Chinese IME composition must not submit Ctrl+Enter.
                idea.evaluate(
                    "el=>el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',ctrlKey:true,isComposing:true,bubbles:true}))"
                )
                assert (
                    page.get_by_role("heading", name="合成北域", exact=True).count() == 0
                )
                idea.press("Control+Enter")
                expect(page.get_by_role("heading", name="合成北域", exact=True)).to_be_visible()
                expect(
                    page.get_by_text(
                        "已识别：合成北域 · 7 天。人数、预算和日期可以以后再补。",
                        exact=True,
                    )
                ).to_be_visible()
                expect(page.get_by_role("heading", name="先完成一次模型配置", exact=True)).to_be_visible()
                page.get_by_role("button", name="新建独立旅行", exact=True).click()
                idea.fill("去虚构湖城玩三天")
                page.route("**/api/v1/preview", lambda r: r.abort())
                page.reload()
                expect(page.get_by_role("heading", name="连接本机服务", exact=True)).to_be_visible()
                expect(idea).to_have_value("去虚构湖城玩三天")
                page.unroute("**/api/v1/preview")
                page.get_by_role("button", name="重新连接本机工作台", exact=True).click()
                expect(page.get_by_role("button", name="查资料并生成旅行建议", exact=True)).to_be_enabled()
                expect(idea).to_have_value("去虚构湖城玩三天")
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(output / "narrow.png"))
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                page.get_by_role("button", name="查资料并生成旅行建议", exact=True).focus()
                expect(page.get_by_role("button", name="查资料并生成旅行建议", exact=True)).to_be_focused()
                page.route(
                    "**/api/v1/preview/automatic-planning",
                    lambda r: (
                        r.fulfill(
                            status=422,
                            json={
                                "error": {
                                    "code": "CACHE_UNAVAILABLE",
                                    "message": "合成本机保存失败，输入保留",
                                }
                            },
                        )
                        if r.request.method == "POST"
                        else r.continue_()
                    ),
                )
                page.get_by_role("button", name="查资料并生成旅行建议", exact=True).click()
                expect(page.locator(".trip-intake").get_by_role("alert")).to_contain_text("合成本机保存失败")
                expect(idea).to_have_value("去虚构湖城玩三天")
                assert not external and not errors
                browser.close()
        proc.stdin.write(b"stop\n")
        proc.stdin.flush()
        proc.wait(timeout=15)
        assert proc.returncode == 0
        metrics = json.loads(control.with_suffix(".metrics.json").read_text())
        assert metrics == {"outbound_attempts": [], "live_imports": []}
        print(
            json.dumps(
                dict(
                    result="PASS",
                    root_auth_recovery=True,
                    idea_preserved=True,
                    keyboard_and_ime=True,
                    empty_cache_next_step=True,
                    offline_recovery=True,
                    narrow=True,
                    failed_submission_preserved=True,
                    external=external,
                )
            )
        )
    finally:
        if proc.poll() is None:
            proc.stdin.write(b"stop\n")
            proc.stdin.flush()
            proc.wait(timeout=15)
        log.close()


if __name__ == "__main__":
    main()
