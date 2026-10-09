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

            def failed_response(response):
                if response.status >= 400 and "/api/v1/preview/conversation/" in response.url:
                    print(
                        "SYNTHETIC_CONVERSATION_HTTP", response.status, response.json(), flush=True
                    )

            page.on("response", failed_response)
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
            expect(
                page.get_by_role("heading", name="资料有限，先看局部建议", exact=True)
            ).to_be_visible(timeout=30000)
            expect(
                page.get_by_text("本次新生成的AI建议 · 当前可行性未核实", exact=True)
            ).to_be_visible()
            if page.locator("details.research-message").get_attribute("open") is None:
                page.get_by_text("研究进展与资料依据", exact=False).click()
            expect(page.get_by_text("成功取得新正文 2 篇", exact=False)).to_be_visible()
            expect(page.get_by_role("button", name="采用这版建议", exact=True)).to_be_enabled()
            page.screenshot(path=str(output / "result.png"), full_page=True)
            page.get_by_text("查看本次资料依据", exact=True).click()
            expect(page.get_by_role("link", name="合成青谷游玩路线1", exact=True)).to_be_visible()
            page.get_by_role("button", name="偏向这个方案", exact=True).click()
            expect(page.get_by_text("已记住暂定方向：", exact=False)).to_be_visible()
            page.get_by_role("button", name="为什么推荐这些", exact=True).click()
            expect(page.get_by_text("依据现有资料回答 · 本地", exact=True)).to_be_visible()
            page.get_by_role("button", name="撤回选择", exact=True).click()
            page.get_by_role("button", name="偏向这个方案", exact=True).click()
            # Preview/cancel does not regenerate.
            page.get_by_role("button", name="预览这版", exact=True).click()
            expect(page.get_by_role("heading", name="建议攻略", exact=True)).to_be_visible()
            page.get_by_role("button", name="取消修改，恢复原版", exact=True).click()
            page.get_by_role("button", name="采用这版建议", exact=True).click()
            expect(
                page.get_by_text("已采用这版；尚未核实的交通和预约继续保留。", exact=True)
            ).to_be_visible()
            page.get_by_label("继续聊聊这次旅行", exact=True).fill("只有5天，不想自驾，想轻松一点")
            page.get_by_role("button", name="发送", exact=True).click()
            expect(page.get_by_role("button", name="按当前取舍更新建议", exact=True)).to_be_enabled(
                timeout=30000
            )
            expect(
                page.get_by_role("heading", name="资料有限，先看局部建议", exact=True)
            ).to_be_visible(timeout=30000)
            expect(
                page.get_by_text(
                    "已识别：合成青谷 · 5 天。人数、预算和日期可以以后再补。", exact=True
                )
            ).to_be_visible()
            expect(page.get_by_role("button", name="确认并更新建议", exact=True)).to_have_count(0)
            page.get_by_label("继续聊聊这次旅行", exact=True).fill(
                "如果只有3天，不自驾会不会太赶？"
            )
            page.get_by_role("button", name="发送", exact=True).click()
            expect(
                page.get_by_text("AI缓存问答 · 建议与解释，非事实核实", exact=True)
            ).to_be_visible(timeout=30000)
            expect(
                page.get_by_text(
                    "已识别：合成青谷 · 5 天。人数、预算和日期可以以后再补。", exact=True
                )
            ).to_be_visible()
            expect(page.get_by_role("button", name="确认并更新建议", exact=True)).to_have_count(0)
            # A hypothesis answers from cache without changing the confirmed five days.
            expect(page.get_by_text("这次是问题或假设，不修改当前条件，也不查新资料。", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="按当前取舍更新建议", exact=True)).to_be_enabled(
                timeout=30000
            )
            if page.locator("details.research-message").get_attribute("open") is None:
                page.get_by_text("研究进展与资料依据", exact=False).click()
            # The latest task is a cache-only hypothesis; earlier real fixture reads
            # remain historical and must not be counted as its new searches.
            import sqlite3
            with sqlite3.connect(output / "synthetic.sqlite3") as con:
                grant=con.execute("SELECT grant_id FROM planning_tasks ORDER BY created_at DESC LIMIT 1").fetchone()[0]
                assert con.execute("SELECT count(*) FROM continuation_operations WHERE continuation_id=? AND kind IN ('SEARCH','DETAIL','CONNECT')",(grant,)).fetchone()[0]==0
            key_leg = page.get_by_role("region", name="关键路段核实", exact=True)
            key_leg.get_by_role("combobox").first.select_option("WALKING")
            expect(key_leg.get_by_role("combobox", name="先查看哪一段", exact=True)).to_be_visible()
            key_leg.get_by_role("checkbox").check()
            key_leg.get_by_role("button", name="核实这段地点（最多2次）", exact=True).click()
            expect(key_leg.get_by_text("地点余额0次；路径余额1次。", exact=False)).to_be_visible()
            for _ in range(2):
                key_leg.get_by_role("button", name="选择这个地点", exact=True).first.click()
            key_leg.get_by_role("button", name="核实这段移动参考（1次）", exact=True).click()
            expect(key_leg.get_by_text("估算约10分钟", exact=False)).to_be_visible()
            page.reload()
            expect(
                page.get_by_role("region", name="本次旅行条件", exact=True)
            ).to_be_visible()
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
                "choice_question_revert_next_round": "PASS",
                "followup_partial_cache_supplement": "PASS",
                "refresh_restore": "PASS",
                "cached_ai_single_submit": "PASS_FAKE_ONLY",
                "key_leg_place_confirmation_route": "PASS_FAKE_ONLY",
                "external_calls": 0,
                "synthetic_only": True,
            }
        )
    )


if __name__ == "__main__":
    main()
