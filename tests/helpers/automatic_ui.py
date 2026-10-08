"""Actual built Vue single-submit acceptance; synthetic provider and reader only."""

import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]


def main():
    output = Path(sys.argv[1])
    output.mkdir(exist_ok=True)
    control = output / "control.json"
    origin = "http://127.0.0.1:18774"
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
            "18774",
            "--product",
            "--automatic-synthetic",
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
                    raise AssertionError("SERVER_FAILED")
                try:
                    if client.get(origin + "/health", timeout=0.3).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("SERVER_NOT_READY")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=[])
            context = browser.new_context(
                viewport={"width": 1200, "height": 900}, service_workers="block"
            )

            def guard(r):
                if urlsplit(r.request.url).netloc != "127.0.0.1:18774":
                    external.append(r.request.url)
                    r.abort()
                else:
                    r.continue_()

            context.route("**/*", guard)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(type(e).__name__))
            page.goto(
                origin
                + "/bootstrap?ticket="
                + json.loads(control.read_text(encoding="utf8"))["ticket"]
            )
            idea = page.get_by_label("你想去哪里，怎么玩？", exact=True)
            idea.fill("我想去合成青谷玩7天")
            page.screenshot(path=str(output / "first-screen.png"))
            # One user click: no permit form, no source/activity/model relay.
            page.get_by_role("button", name="查资料并生成旅行建议", exact=True).click()
            expect(page.get_by_role("heading", name="先看看这几种玩法", exact=True)).to_be_visible(
                timeout=30000
            )
            expect(
                page.get_by_text("本次新生成的AI建议 · 当前可行性未核实", exact=True)
            ).to_be_visible()
            expect(page.get_by_text("成功取得新正文 1 篇", exact=False)).to_be_visible()
            expect(page.get_by_role("button", name="采用这版建议", exact=True)).to_be_enabled()
            page.screenshot(path=str(output / "result.png"), full_page=True)
            page.get_by_text("查看本次资料依据", exact=True).click()
            expect(page.get_by_role("link", name="合成青谷游玩路线1", exact=True)).to_be_visible()
            # Preview/cancel does not regenerate.
            page.get_by_role("button", name="预览这版", exact=True).click()
            expect(page.get_by_role("heading", name="建议攻略", exact=True)).to_be_visible()
            page.get_by_role("button", name="取消修改，恢复原版", exact=True).click()
            page.get_by_role("button", name="采用这版建议", exact=True).click()
            expect(
                page.get_by_text("已采用这版；尚未核实的交通和预约继续保留。", exact=True)
            ).to_be_visible()
            page.get_by_label("补充或修改想法", exact=True).fill("只有5天，不想自驾，想轻松一点")
            page.get_by_role("button", name="按补充调整建议", exact=True).click()
            expect(page.get_by_role("heading", name="先看看这几种玩法", exact=True)).to_be_visible(
                timeout=30000
            )
            expect(
                page.get_by_text(
                    "已识别：合成青谷 · 5 天。人数、预算和日期可以以后再补。", exact=True
                )
            ).to_be_visible()
            expect(page.get_by_text("本次没有派发小红书搜索", exact=False)).to_be_visible()
            page.reload()
            expect(page.get_by_role("heading", name="先看看这几种玩法", exact=True)).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=str(output / "followup.png"), full_page=True)
            assert not errors and not external
            context.close()
            browser.close()
    finally:
        if proc.poll() is None:
            proc.stdin.write(b"\n")
            proc.stdin.flush()
            proc.wait(timeout=20)
        log.close()
    metrics = json.loads(control.with_suffix(".metrics.json").read_text(encoding="utf8"))
    assert metrics == {"outbound_attempts": [], "live_imports": []}, metrics
    print(
        json.dumps(
            {
                "single_click_to_proposal": "PASS",
                "preview_cancel_adopt": "PASS",
                "followup_cached": "PASS",
                "refresh_restore": "PASS",
                "external_calls": 0,
                "synthetic_only": True,
            }
        )
    )


if __name__ == "__main__":
    main()
