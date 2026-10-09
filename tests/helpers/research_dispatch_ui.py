"""Built page -> HTTP -> actual worker subprocesses, with synthetic I/O boundaries."""

import json
from pathlib import Path
import sqlite3
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
    origin = "http://127.0.0.1:18779"
    control = output / "control.json"
    database = output / "preview.sqlite3"
    (output / "fail-startup").touch()
    log = (output / "server.log").open("w", encoding="utf8")
    proc = subprocess.Popen([sys.executable, str(ROOT / "tests/helpers/preview_server.py"), "--database", str(database), "--scope", "owner", "--mode", "CACHED_PRIVATE_PREVIEW", "--control", str(control), "--port", "18779", "--product", "--automatic-subprocess"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    external, errors = [], []
    try:
        with httpx.Client(trust_env=False) as client:
            for _ in range(100):
                if proc.poll() is not None:
                    raise AssertionError("SERVER_FAILED")
                try:
                    if client.get(origin + "/health", timeout=.3).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise AssertionError("SERVER_NOT_READY")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=[])
            context = browser.new_context(service_workers="block", viewport={"width":1200,"height":900})

            def guard(route):
                if urlsplit(route.request.url).netloc != "127.0.0.1:18779":
                    external.append("external")
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", guard)
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(origin + "/bootstrap?ticket=" + json.loads(control.read_text())["ticket"])
            page.get_by_label("你想去哪里，怎么玩？", exact=True).fill("我想去合成青谷玩7天")
            page.get_by_role("button", name="查资料并生成旅行建议", exact=True).click()
            try:
                expect(page.get_by_text("停止阶段：SOURCE_STARTUP", exact=False)).to_be_visible(timeout=30000)
            except AssertionError:
                print("SYNTHETIC_PAGE_ERRORS", errors, flush=True)
                raise
            conditions = page.get_by_role("region", name="本次旅行条件")
            expect(conditions).to_contain_text("7天")
            expect(page.get_by_role("button", name="先比较现有方案", exact=True)).to_have_count(0)
            expect(page.get_by_role("button", name="为什么推荐这些", exact=True)).to_have_count(0)
            expect(page.get_by_text("因系统启动故障尚未派发", exact=False)).to_be_visible()
            page.screenshot(path=str(output / "startup-failure.png"), full_page=True)
            with sqlite3.connect(database) as con:
                assert con.execute("SELECT count(*) FROM continuation_operations WHERE kind='MODEL'").fetchone()[0] == 2
                assert con.execute("SELECT count(*) FROM continuation_operations WHERE kind!='MODEL'").fetchone()[0] == 0
                failed = con.execute("SELECT summary_json FROM planning_tasks").fetchone()[0]
            # Empty material does not expose a cache-comparison shortcut or authorize an answer.
            with sqlite3.connect(database) as con:
                assert con.execute("SELECT count(*) FROM preview_jobs WHERE research_id LIKE 'question-%'").fetchone()[0] == 0
            # Local condition edit / cancellation does not alter the saved values.
            conditions.get_by_role("button", name="修改本次条件", exact=True).click()
            conditions.get_by_label("可用天数（可留空）", exact=True).fill("9")
            expect(page.get_by_role("button", name="新建独立旅行", exact=True)).to_be_disabled()
            page.get_by_text("历史旅行与合成场景", exact=True).click()
            expect(page.get_by_label("恢复本次旅行", exact=False)).to_be_disabled()
            expect(page.get_by_role("button", name="继续补充研究", exact=True)).to_be_disabled()
            assert page.evaluate("JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k=>k.startsWith('ta-condition-draft:')))).values.days") == 9
            page.reload()
            expect(conditions.get_by_label("可用天数（可留空）", exact=True)).to_have_value("9")
            conditions.get_by_role("button", name="取消条件编辑", exact=True).click()
            expect(conditions).to_contain_text("7天")
            with sqlite3.connect(database) as con:
                assert con.execute("SELECT count(*) FROM continuation_operations").fetchone()[0] == 2
            (output / "fail-startup").unlink()
            # A new independent full task exercises the real subprocess chain.
            # Its own cap includes intake and supervision; no old allowance is reused.
            page.get_by_role("button",name="新建独立旅行",exact=True).click()
            page.get_by_label("你想去哪里，怎么玩？",exact=True).fill("我想去合成青谷玩7天，想自驾")
            page.get_by_role("button",name="查资料并生成旅行建议",exact=True).click()
            expect(page.get_by_role("heading", name="资料有限，先看局部建议", exact=True)).to_be_visible(timeout=60000)
            expect(conditions).to_contain_text("自己驾驶")
            expect(page.get_by_text("请先明确本次交通方式", exact=False)).to_have_count(0)
            points = page.get_by_role("region", name="正文拆分点", exact=True)
            expect(points).to_be_visible()
            with sqlite3.connect(database) as con:
                before_choices = con.execute("SELECT count(*) FROM continuation_operations").fetchone()[0]
            points.get_by_role("button", name="想了解这个", exact=True).first.click()
            expect(points.get_by_role("button", name="撤回兴趣", exact=True)).to_have_count(1)
            points.get_by_role("button", name="本轮不采用", exact=True).first.click()
            expect(points.get_by_role("button", name="恢复这条参考", exact=True)).to_have_count(1)
            points.get_by_role("button", name="恢复这条参考", exact=True).click()
            points.get_by_role("button", name="想了解这个", exact=True).first.click()
            page.reload()
            expect(points.get_by_role("button", name="撤回兴趣", exact=True)).to_have_count(1)
            with sqlite3.connect(database) as con:
                assert con.execute("SELECT count(*) FROM continuation_operations").fetchone()[0] == before_choices
            calls = [json.loads(line) for line in (output / "dispatch.jsonl").read_text(encoding="utf8").splitlines()]
            kinds = [v["kind"] for v in calls]
            assert all(kind in kinds for kind in ("agent-worker", "agent-model-worker", "READER_CONSTRUCTOR", "CONNECT", "SEARCH", "DETAIL", "extract-worker", "review-worker", "worker")), kinds
            assert kinds.count("CONNECT")==1 and kinds.count("SEARCH")==2
            assert "不自驾" not in next(v["query"] for v in calls if v["kind"] == "SEARCH")
            with sqlite3.connect(database) as con:
                assert con.execute("SELECT summary_json FROM planning_tasks ORDER BY created_at LIMIT 1").fetchone()[0] == failed
                assert con.execute("SELECT count(*) FROM planning_tasks").fetchone()[0] == 2
                used = con.execute("SELECT count(*) FROM continuation_operations").fetchone()[0]
            conditions.get_by_role("button", name="修改本次条件", exact=True).click()
            conditions.get_by_label("可用天数（可留空）", exact=True).fill("5")
            conditions.get_by_role("button", name="保存本次条件（仅本地）", exact=True).click()
            expect(conditions.get_by_role("button", name="修改本次条件", exact=True)).to_be_visible()
            expect(conditions).to_contain_text("5天")
            page.reload()
            expect(conditions).to_contain_text("5天")
            with sqlite3.connect(database) as con:
                assert con.execute("SELECT count(*) FROM continuation_operations").fetchone()[0] == used
            assert (output / "dispatch.jsonl").read_text(encoding="utf8").count('"kind": "CONNECT"') == 1
            page.set_viewport_size({"width":390,"height":844})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=str(output / "conditions-and-result.png"), full_page=True)
            assert not external and not errors, errors
            browser.close()
    finally:
        if proc.poll() is None:
            proc.stdin.write(b"stop\n")
            proc.stdin.flush()
            proc.wait(timeout=20)
        log.close()
    assert all(json.loads(path.read_text())["blocked"] == [] for path in output.glob("*-worker-*.metrics.json"))
    assert json.loads(control.with_suffix(".metrics.json").read_text())["outbound_attempts"] == []
    print(json.dumps(dict(result="PASS", external_calls=0, production_subprocess_chain=True, historical_failure_unchanged=True, condition_recovery=True)))


if __name__ == "__main__":
    main()
