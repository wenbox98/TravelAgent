"""Explicit operator-driven T04 entrypoint; only safe summaries leave this process."""

import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Thread

from .browser import BrowserManager, BrowserOptions, BrowserSession, SessionClosed
from .live_observability import LiveNetworkObserver
from .live_page import LiveBrowserBackend, LiveReadStopped
from .live_reader import LiveSmokeReader
from .login import LoginLifecycle
from .models import SearchRequest
from .profile import ProfileStore


QUERY = "成都 川西 国庆 攻略"


class CountingBrowserManager(BrowserManager):
    def __init__(self, backend: LiveBrowserBackend) -> None:
        super().__init__(backend, BrowserOptions(engine="chromium", headless=False))
        self.sessions_created = 0

    def start(self) -> BrowserSession:
        with self._lock:
            before = self._session
            session = super().start()
            if session is not before:
                self.sessions_created += 1
            return session


class AuditCounter(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines = 0
        self.unrecognized = 0
        self.sentinel_matches = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.lines += 1
        # SafeAuditLog creates a mapping before creating the LogRecord.
        value = record.args
        allowed = {"event", "operation", "outcome", "count", "status_code"}
        if not isinstance(value, dict) or set(value) - allowed or record.exc_info:
            self.unrecognized += 1
        if "SECRET_" in record.getMessage():
            self.sentinel_matches += 1
        # No raw logs or exception details are printed or retained.


class SmokeController:
    def __init__(self, project: Path, output: Path, *, detail_smoke: bool = False) -> None:
        if output.exists():
            previous = json.loads(output.read_text(encoding="utf-8"))
            usage = previous.get("reading", {})
            if usage.get("search_operations", 0) or usage.get("detail_operations", 0):
                raise RuntimeError("已有实站读取记录；不得通过重启重置实验预算")
        self.output = output
        self.detail_smoke = detail_smoke
        self.observer = LiveNetworkObserver()
        self.profile = ProfileStore(project)
        self.profile_present_at_start = self.profile.exists()
        self.backend = LiveBrowserBackend(self.profile, self.observer)
        self.browser = CountingBrowserManager(self.backend)
        self.login = LoginLifecycle(self.browser, self.profile)
        self.audit = AuditCounter()
        logger = self.login.audit.logger
        logger.handlers = [self.audit]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        self.reader = LiveSmokeReader(
            self.browser, self.login, self.backend, checkpoint=self.save,
            max_feed_details=1 if detail_smoke else 2,
        )
        self.login_window = False
        self.connect_started = False
        self.login_required_seen = False
        self.authenticated_seen = False
        self.verification_seen = False
        self.last_error: str | None = None
        self.closed = False

    def summary(self) -> dict[str, object]:
        state = self.login.status()
        return {
            "experiment": "T04.1" if self.detail_smoke else "T04",
            "locator_reacquisition": "MEMORY_ONLY_LOCATOR_NOT_RETAINED" if self.detail_smoke else None,
            "query": QUERY,
            "login": {
                "status": state.status, "error_code": state.error_code,
                "account_identity": state.account_identity,
                "evidence": state.evidence.model_dump() if state.evidence else None,
                "profile_present_at_start": self.profile_present_at_start,
                "login_required_seen": self.login_required_seen,
                "authenticated_seen": self.authenticated_seen,
                "verification_seen": self.verification_seen,
                "browser_sessions": self.browser.sessions_created,
                "browser_starts": self.backend.browser_starts,
            },
            "reading": self.reader.safe_summary(),
            "network": {
                label: asdict(self.observer.snapshot(None if label == "TOTAL" else label))
                for label in ("TOTAL", "LOGIN", "SEARCH", "DETAIL_1", "DETAIL_2", "OUTSIDE_WINDOW")
            },
            "audit": {
                "lines": self.audit.lines, "unrecognized": self.audit.unrecognized,
                "sentinel_matches": self.audit.sentinel_matches,
            },
            "last_error": self.last_error,
            "read_diagnostic": self.backend.last_read_diagnostic,
            "detail_diagnostic": self.backend.detail_diagnostic,
            "closed": self.closed,
        }

    def save(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.summary(), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.output)

    def tick(self) -> bool:
        state = self.login.status()
        changed = False
        if state.status in {"WAITING_USER", "LOGIN_REQUIRED"} and not self.login_required_seen:
            self.login_required_seen, changed = True, True
        if state.status == "VERIFICATION_REQUIRED" and not self.verification_seen:
            self.verification_seen, changed = True, True
        if state.status == "AUTHENTICATED" and not self.authenticated_seen:
            self.authenticated_seen, changed = True, True
        if self.login_window and state.status in {"AUTHENTICATED", "VERIFICATION_REQUIRED", "ERROR"}:
            if self.backend.login_window_open:
                self.observer.finish_window()
                self.backend.login_window_open = False
            self.login_window = False
            changed = True
        # The sync driver needs an API message pump to deliver normal network events.
        # This neither navigates nor reads content; no requests are added for measurement.
        if self.authenticated_seen and not self.closed:
            try:
                self.backend.pump(self.browser.get_session())
            except SessionClosed:
                pass
            except Exception:
                self.last_error = "BROWSER_ERROR"
        if self.observer.stop_code is not None:
            self.reader.stopped = self.observer.stop_code
            self.last_error = self.observer.stop_code
        return changed

    def command(self, command: str) -> bool:
        if command == "connect":
            if not self.connect_started:
                self.login_window = self.connect_started = True
                self.login.connect()
        elif command == "search":
            self.reader.search(SearchRequest(keyword=QUERY))
        elif command in {"detail 0", "detail 1"}:
            ordinal = int(command[-1])
            choices = self.reader.selection()
            if ordinal >= len(choices):
                raise LiveReadStopped("NO_LOCATOR")
            self.reader.detail(choices[ordinal])
        elif command in {"status", "snapshot"}:
            pass
        elif command == "quit":
            self.close()
            return False
        else:
            self.last_error = "UNKNOWN_LOCAL_COMMAND"
        self.tick()
        return True

    def close(self) -> None:
        if not self.closed:
            self.login.shutdown()  # Normal close, retaining the user's dedicated profile.
            if self.login.status().status == "ERROR":
                self.last_error = "CLEANUP_FAILED"
                raise RuntimeError("浏览器关闭未完成")
            self.closed = True
            self.save()


def main(project: Path) -> int:
    parser = argparse.ArgumentParser(description="T04一次搜索、最多两篇详情的人工Smoke")
    parser.add_argument("--live", action="store_true", help="明确启用真实普通浏览器")
    parser.add_argument("--detail-smoke", action="store_true", help="T04.1独立账本；最多一篇详情")
    args = parser.parse_args()
    if not args.live:
        print("未启用真实访问。需要显式 --live；启动后仍须输入 connect。")
        return 0
    controller: SmokeController | None = None
    try:
        directory = "t04.1-smoke" if args.detail_smoke else "t04-smoke"
        controller = SmokeController(project, project / f".local/{directory}/summary.json",
                                     detail_smoke=args.detail_smoke)
        commands: Queue[str] = Queue()

        def receive() -> None:
            for line in sys.stdin:
                commands.put(line.strip())
            commands.put("quit")

        Thread(target=receive, daemon=True, name="smoke-local-input").start()
        print(json.dumps({"ready": True, "commands": [
            "connect", "status", "search", "detail 0", "detail 1", "snapshot", "quit",
        ]}), flush=True)
        running = True
        while running:
            try:
                command = commands.get(timeout=0.5)
            except Empty:
                if controller.tick():
                    controller.save()
                    print(json.dumps(controller.summary(), ensure_ascii=False), flush=True)
                continue
            try:
                running = controller.command(command)
            except LiveReadStopped as error:
                controller.last_error = error.code
            except Exception:
                if command == "quit":
                    controller.last_error = "CLEANUP_FAILED"
                    controller.save()
                    print(json.dumps(controller.summary(), ensure_ascii=False), flush=True)
                    return 1
                controller.last_error = "LOCAL_SMOKE_ERROR"
            controller.save()
            print(json.dumps(controller.summary(), ensure_ascii=False), flush=True)
        return 0
    except Exception:
        print(json.dumps({"error": "SMOKE_SETUP_FAILED_OR_EXISTING_RUN"}), flush=True)
        return 1
    finally:
        if controller is not None and not controller.closed:
            try:
                controller.close()
            except Exception:
                print(json.dumps({"error": "CLEANUP_FAILED"}), flush=True)
