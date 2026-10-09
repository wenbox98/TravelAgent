"""Built normal page, delayed/lost loopback replies; authored adapters only."""

import json
from pathlib import Path
import subprocess
import sqlite3
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
    origin = "http://127.0.0.1:18778"
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
            "18778",
            "--product",
            "--automatic-synthetic",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=log,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    external, posts, errors = [], [], []
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
            context = browser.new_context(service_workers="block")

            def guard(route):
                if urlsplit(route.request.url).netloc != "127.0.0.1:18778":
                    external.append("external")
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", guard)
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(type(e).__name__))
            page.on(
                "request",
                lambda r: (
                    posts.append(r.url)
                    if r.method == "POST"
                    and any(p in r.url for p in ("/automatic-planning", "/conversation/"))
                    else None
                ),
            )
            held = []
            page.route("**/api/v1/preview", lambda r: held.append(r))
            page.goto(origin)
            idea = page.get_by_label("你想去哪里，怎么玩？", exact=True)
            idea.fill("我想去合成青谷玩7天")
            idea.press("Control+Enter")
            expect(page.locator("#intake-reason")).to_contain_text("正在连接")
            assert not posts
            held.pop().continue_()
            page.unroute("**/api/v1/preview")
            expect(page.get_by_role("heading", name="重新打开本机入口", exact=True)).to_be_visible()
            idea.press("Meta+Enter")
            expect(page.locator("#intake-reason")).to_contain_text("未提交")
            assert not posts
            page.goto(origin + "/bootstrap?ticket=" + json.loads(control.read_text())["ticket"])
            expect(idea).to_have_value("我想去合成青谷玩7天")
            idea.fill("")
            idea.press("Control+Enter")
            expect(page.locator("#intake-reason")).to_contain_text("请先写下")
            idea.fill("我想去合成青谷玩7天")
            # A never-delivered POST survives refresh without a silent retry.
            # Manual continuation retains the original key AND literal input.
            undelivered = []
            page.route(
                "**/api/v1/preview/automatic-planning",
                lambda r: (
                    undelivered.append(
                        (r.request.headers["idempotency-key"], r.request.post_data_json)
                    ),
                    r.abort(),
                ),
            )
            page.get_by_role("button", name="查资料并生成旅行建议", exact=True).click()
            expect(page.locator(".trip-intake").get_by_role("alert")).to_contain_text(
                "提交结果尚未确认"
            )
            idea.fill("我想去合成青谷玩8天")
            page.unroute("**/api/v1/preview/automatic-planning")
            page.reload()
            expect(idea).to_have_value("我想去合成青谷玩8天")
            expect(page.get_by_role("button", name="继续确认原提交", exact=True)).to_be_visible()
            assert len(posts) == 1
            with sqlite3.connect(output / "synthetic.sqlite3") as con:
                assert con.execute("SELECT count(*) FROM planning_tasks").fetchone()[0] == 0
            # One explicit continuation and repeated shortcuts while it waits.
            held = []
            page.route("**/api/v1/preview/automatic-planning", lambda r: held.append(r))
            page.get_by_role("button", name="继续确认原提交", exact=True).click()
            expect(page.get_by_role("button", name="正在提交…", exact=True)).to_be_disabled()
            expect(page.locator(".trip-intake")).to_contain_text("尚未确认接收")
            idea.press("Control+Enter")
            idea.press("Meta+Enter")
            assert len(held) == 1 and len(posts) == 2
            assert (
                held[-1].request.headers["idempotency-key"],
                held[-1].request.post_data_json,
            ) == undelivered[0]
            held.pop().continue_()
            page.unroute("**/api/v1/preview/automatic-planning")
            expect(page.locator(".trip-intake")).to_contain_text("已确认原提交接收成功")
            expect(idea).to_have_value("我想去合成青谷玩8天")
            idea.fill("")
            page.get_by_role("button", name="回到当前旅行", exact=True).click()
            expect(
                page.get_by_role("heading", name="资料有限，先看局部建议", exact=True)
            ).to_be_visible(timeout=30000)
            with sqlite3.connect(output / "synthetic.sqlite3") as con:
                assert con.execute("SELECT count(*) FROM planning_tasks").fetchone()[0] == 1
            composer = page.locator("form.composer")
            message = page.get_by_label("继续聊聊这次旅行", exact=True)
            message.fill("为什么推荐这些？")
            # IME, held-key repeats and plain Enter must not submit either form.
            for fields in [
                dict(ctrlKey=True, isComposing=True),
                dict(metaKey=True, repeat=True),
                {},
            ]:
                message.evaluate(
                    "(el,fields)=>el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,...fields}))",
                    fields,
                )
            assert len(posts) == 2, [urlsplit(p).path for p in posts]
            held = []
            page.route("**/api/v1/preview/conversation/*", lambda r: held.append(r))
            message.press("Meta+Enter")
            expect(composer.get_by_role("button", name="正在提交…", exact=True)).to_be_disabled()
            expect(composer).to_contain_text("尚未确认接收")
            message.press("Control+Enter")
            assert len(held) == 1 and len(posts) == 3
            held.pop().continue_()
            page.unroute("**/api/v1/preview/conversation/*")
            expect(composer.get_by_text("本次缓存回答已完成", exact=False)).to_be_visible(
                timeout=30000
            )
            expect(message).to_have_value("")
            message.fill("这个方向为什么适合？")
            page.reload()
            expect(message).to_have_value("这个方向为什么适合？")
            # Definite server rejection preserves the message near its error.
            page.route(
                "**/api/v1/preview/conversation/*",
                lambda r: r.fulfill(
                    status=422,
                    json={"error": {"code": "INVALID_INPUT", "message": "合成拒绝，未提交"}},
                ),
            )
            message.press("Control+Enter")
            expect(composer.get_by_role("alert")).to_contain_text("合成拒绝")
            expect(message).to_have_value("这个方向为什么适合？")
            page.unroute("**/api/v1/preview/conversation/*")

            # The server accepts, but the browser loses the response. A second
            # send MUST NOT replay the POST; only read-only recovery is allowed.
            def lose_reply(route):
                response = route.fetch()
                assert response.status == 200
                route.abort()

            page.route("**/api/v1/preview/conversation/*", lose_reply)
            message.press("Control+Enter")
            expect(composer.get_by_role("alert")).to_contain_text("提交结果尚未确认")
            expect(message).to_have_value("这个方向为什么适合？")
            attempts = len(posts)
            message.press("Meta+Enter")
            expect(page.locator("#message-feedback")).to_contain_text("未发送")
            assert len(posts) == attempts
            page.unroute("**/api/v1/preview/conversation/*")
            composer.get_by_role("button", name="读取已保存状态", exact=True).click()
            expect(page.locator("#message-feedback")).to_contain_text("已确认提交成功")
            expect(message).to_have_value("")
            assert len(posts) == attempts
            expect(composer.get_by_text("本次缓存回答已完成", exact=False)).to_be_visible(
                timeout=30000
            )
            # Accepted but response lost, then a full page reload: GET only,
            # keep a different message edited after the original submission.
            page.route("**/api/v1/preview/conversation/*", lose_reply)
            message.fill("这条路线的依据是什么？")
            message.press("Control+Enter")
            expect(composer.get_by_role("alert")).to_contain_text("提交结果尚未确认")
            message.fill("我后来编辑的另一条问题")
            attempts = len(posts)
            page.unroute("**/api/v1/preview/conversation/*")
            page.reload()
            expect(message).to_have_value("我后来编辑的另一条问题")
            expect(page.locator("#message-feedback")).to_contain_text("已确认提交成功")
            assert len(posts) == attempts
            expect(composer.get_by_text("本次缓存回答已完成", exact=False)).to_be_visible(
                timeout=30000
            )
            # A never-delivered message can explicitly continue with the same
            # original key/text; reading state and refreshing never resend it.
            undelivered = []
            page.route(
                "**/api/v1/preview/conversation/*",
                lambda r: (
                    undelivered.append(
                        (r.request.headers["idempotency-key"], r.request.post_data_json)
                    ),
                    r.abort(),
                ),
            )
            message.fill("能比较一下已有方向吗？")
            message.press("Control+Enter")
            expect(composer.get_by_role("alert")).to_contain_text("提交结果尚未确认")
            page.unroute("**/api/v1/preview/conversation/*")
            message.fill("保留后续编辑的问题")
            attempts = len(posts)
            page.reload()
            expect(message).to_have_value("保留后续编辑的问题")
            expect(
                composer.get_by_role("button", name="继续确认原提交", exact=True)
            ).to_be_visible()
            assert len(posts) == attempts
            # A continuation rejected by auth does not prove that the original
            # was unaccepted; retain its identity until a successful recovery.
            page.route(
                "**/api/v1/preview/conversation/*",
                lambda r: r.fulfill(
                    status=401, json={"error": {"code": "AUTH_REQUIRED", "message": "合成认证过期"}}
                ),
            )
            composer.get_by_role("button", name="继续确认原提交", exact=True).click()
            expect(composer.get_by_role("alert")).to_contain_text("提交结果尚未确认")
            assert (
                page.evaluate("JSON.parse(localStorage.getItem('ta-conversation-intent')).key")
                == undelivered[0][0]
            )
            page.unroute("**/api/v1/preview/conversation/*")
            page.reload()
            expect(
                composer.get_by_role("button", name="继续确认原提交", exact=True)
            ).to_be_visible()
            resumed = []
            page.route(
                "**/api/v1/preview/conversation/*",
                lambda r: (
                    resumed.append(
                        (r.request.headers["idempotency-key"], r.request.post_data_json)
                    ),
                    r.continue_(),
                ),
            )
            composer.get_by_role("button", name="继续确认原提交", exact=True).click()
            expect(page.locator("#message-feedback")).to_contain_text("已确认原提交接收成功")
            expect(message).to_have_value("保留后续编辑的问题")
            assert resumed == undelivered and len(posts) == attempts + 2
            page.unroute("**/api/v1/preview/conversation/*")
            expect(composer.get_by_text("本次缓存回答已完成", exact=False)).to_be_visible(
                timeout=30000
            )
            attempts = len(posts)
            # A synthetic legacy DETAILED trip uses the still-supported API
            # mode. Its actual editable DOM must explain the unsaved-draft gate.
            page.get_by_role("button", name="新建独立旅行", exact=True).click()
            idea.fill("我想去合成松谷玩3天")
            page.locator(".trip-intake").get_by_text("高级：执行范围与本地模式", exact=True).click()
            page.route(
                "**/api/v1/preview/planning",
                lambda r: (
                    r.continue_(
                        post_data=json.dumps(
                            {**r.request.post_data_json, "planning_mode": "DETAILED"}
                        )
                    )
                    if r.request.method == "POST"
                    else r.continue_()
                ),
            )
            page.get_by_role("button", name="只建立本地旅行", exact=True).click()
            expect(page.get_by_role("heading", name="合成松谷", exact=True)).to_be_visible()
            page.unroute("**/api/v1/preview/planning")
            page.get_by_text("高级：本地选材、手动操作与详细条件", exact=True).click()
            page.get_by_role("button", name="修改条件", exact=True).click()
            day = page.get_by_label("可用天数（可留空）", exact=True)
            day.fill("4")
            message.evaluate(
                "el=>el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',ctrlKey:true,bubbles:true}))"
            )
            expect(page.locator("#message-feedback")).to_contain_text("先保存")
            assert len(posts) == attempts
            day.fill("3")
            with sqlite3.connect(output / "synthetic.sqlite3") as con:
                assert con.execute("SELECT count(*) FROM planning_tasks").fetchone()[0] == 1
                assert (
                    con.execute(
                        "SELECT count(*) FROM preview_jobs WHERE research_id LIKE 'question-%'"
                    ).fetchone()[0]
                    == 4
                )
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=str(output / "feedback.png"), full_page=True)
            assert not external and not errors, errors
            browser.close()
    finally:
        if proc.poll() is None:
            proc.stdin.write(b"stop\n")
            proc.stdin.flush()
            proc.wait(timeout=20)
        log.close()
    assert json.loads(control.with_suffix(".metrics.json").read_text()) == {
        "outbound_attempts": [],
        "live_imports": [],
    }
    print(
        json.dumps(
            dict(result="PASS", external_calls=0, post_attempts=len(posts), unknown_replayed=False)
        )
    )


if __name__ == "__main__":
    main()
