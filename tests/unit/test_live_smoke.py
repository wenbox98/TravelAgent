"""Controller regressions with synthetic resources; never start Playwright or access XHS."""

import json
import logging
from threading import RLock
from types import SimpleNamespace

import pytest

from xhs_sidecar import live_smoke
from xhs_sidecar.live_observability import LiveNetworkObserver
from xhs_sidecar.models import LoginState
from xhs_sidecar.ordinary_browser import OrdinaryBrowserBackend
from xhs_sidecar.redaction import SafeAuditLog


@pytest.fixture
def controller_rig(monkeypatch, tmp_path):
    events = []
    resources = []

    class Observer(LiveNetworkObserver):
        def attach(self, context):
            events.append("attach")
            return super().attach(context)

        def start_window(self, label):
            events.append(("start_window", label))
            return super().start_window(label)

        def finish_window(self):
            events.append("finish_window")
            return super().finish_window()

        def detach(self):
            events.append("detach")
            return super().detach()

    class Context:
        def __init__(self):
            self.handlers = {}

        def on(self, event, handler):
            self.handlers.setdefault(event, []).append(handler)

        def remove_listener(self, event, handler):
            self.handlers[event].remove(handler)

        def close(self):
            for handler in tuple(self.handlers.get("close", ())):
                handler(self)

    class Resource:
        def __init__(self, observer):
            self.observer = observer
            self._context = Context()
            self._page = SimpleNamespace(wait_for_timeout=lambda _: events.append("pump"))
            self._lock = RLock()
            self._closed = False
            self._revoked = False
            self.navigations = 0

        def _run(self, operation):
            return operation()

        def open_login(self):
            # Exercise the actual backend/controller coordination: the window must
            # already be attached and active when the lifecycle begins navigation.
            measurement = self.observer.snapshot("LOGIN")
            assert measurement.attachment_active
            assert measurement.measurement == "OBSERVED"
            assert not measurement.window_finished
            self.navigations += 1
            events.append("login_navigation")

        def close(self):
            events.append("resource_close")
            self._revoked = self._closed = True
            self._context.close()

    class Profile:
        def __init__(self, project):
            self.project = project

        def exists(self):
            return False

    class Lifecycle:
        def __init__(self, browser, profile):
            self.browser = browser
            self.audit = SafeAuditLog()
            self.current = LoginState(mode="login", status="DISCONNECTED")
            self.connect_calls = 0
            self.shutdown_calls = 0
            self.fail_shutdown = False

        def status(self):
            return self.current

        def connect(self):
            self.connect_calls += 1
            self.browser.start().open_login()
            self.current = LoginState(mode="login", status="AUTHENTICATED", generation=1)
            return self.current

        def shutdown(self):
            self.shutdown_calls += 1
            if self.fail_shutdown:
                self.current = LoginState(
                    mode="login", status="ERROR", error_code="CLEANUP_FAILED"
                )
            else:
                self.browser.close()
                self.current = LoginState(mode="login", status="DISCONNECTED")
            return self.current

    def start_ordinary(backend, options):
        events.append("ordinary_start")
        assert options.engine == "chromium" and options.headless is False
        resource = Resource(backend.observer)
        resources.append(resource)
        return resource

    monkeypatch.setattr(live_smoke, "LiveNetworkObserver", Observer)
    monkeypatch.setattr(live_smoke, "ProfileStore", Profile)
    monkeypatch.setattr(live_smoke, "LoginLifecycle", Lifecycle)
    monkeypatch.setattr(OrdinaryBrowserBackend, "start", start_ordinary)
    logger = logging.getLogger("xhs_sidecar")
    original = logger.handlers[:], logger.propagate, logger.level
    controller = live_smoke.SmokeController(tmp_path, tmp_path / "summary.json")
    try:
        yield SimpleNamespace(controller=controller, events=events, resources=resources)
    finally:
        controller.login.fail_shutdown = False
        if not controller.closed:
            controller.close()
        logger.handlers, logger.propagate, logger.level = original


def test_first_connect_attaches_and_opens_window_before_login_navigation(controller_rig):
    controller = controller_rig.controller
    assert controller.command("status")
    assert controller_rig.events == []
    assert controller.observer.snapshot().measurement == "NOT_MEASURED"

    assert controller.command("connect")
    assert controller_rig.events[:4] == [
        "ordinary_start", "attach", ("start_window", "LOGIN"), "login_navigation"
    ]
    assert controller.authenticated_seen
    assert controller.browser.sessions_created == controller.backend.browser_starts == 1
    assert controller_rig.resources[0].navigations == 1
    assert controller.observer.snapshot("LOGIN").window_finished

    assert controller.command("connect")
    assert controller.login.connect_calls == 1
    assert len(controller_rig.resources) == 1
    assert controller_rig.resources[0].navigations == 1


def test_quit_without_browser_completes_and_saves_local_summary(controller_rig):
    controller = controller_rig.controller
    assert controller.command("quit") is False
    assert controller.closed
    assert controller.login.shutdown_calls == 1
    assert not controller_rig.resources
    assert controller_rig.events == []
    saved = json.loads(controller.output.read_text(encoding="utf-8"))
    assert saved["closed"] is True
    assert saved["login"]["browser_sessions"] == 0
    assert saved["network"]["TOTAL"]["measurement"] == "NOT_MEASURED"


def test_quit_after_authentication_does_not_end_login_window_twice(controller_rig):
    controller = controller_rig.controller
    controller.command("connect")
    assert controller_rig.events.count("finish_window") == 1
    assert not controller.login_window and not controller.backend.login_window_open

    assert controller.command("quit") is False
    assert controller.closed
    assert controller_rig.events.count("finish_window") == 1
    assert controller_rig.events.count("detach") == 1
    assert controller_rig.resources[0]._closed
    assert not controller.observer.snapshot().attachment_active
    controller.close()
    assert controller.login.shutdown_calls == 1


def test_failed_shutdown_keeps_controller_open_and_reports_cleanup_failure(controller_rig):
    controller = controller_rig.controller
    controller.command("connect")
    controller.login.fail_shutdown = True
    with pytest.raises(RuntimeError, match="浏览器关闭未完成"):
        controller.command("quit")
    assert not controller.closed
    assert controller.last_error == "CLEANUP_FAILED"
    assert controller.login.status().status == "ERROR"
    assert not controller_rig.resources[0]._closed

    controller.login.fail_shutdown = False
    assert controller.command("quit") is False
    assert controller.closed
    assert controller.login.shutdown_calls == 2
    assert not controller.observer.snapshot().attachment_active


def test_without_live_flag_never_constructs_controller(monkeypatch, tmp_path, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("未显式启用 live 时不得创建控制器、profile 或浏览器")

    monkeypatch.setattr(live_smoke, "SmokeController", forbidden)
    monkeypatch.setattr(live_smoke.sys, "argv", ["xhs_read_smoke.py"])
    assert live_smoke.main(tmp_path) == 0
    assert "需要显式 --live" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("usage", [
    {"search_operations": 1, "detail_operations": 0},
    {"search_operations": 0, "detail_operations": 1},
    {"search_operations": 1, "detail_operations": 2},
])
def test_previous_read_usage_blocks_restart_before_profile_or_browser(monkeypatch, tmp_path, usage):
    output = tmp_path / "summary.json"
    before = json.dumps({"reading": usage})
    output.write_text(before, encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("既有实验预算应在创建 profile 或浏览器之前检查")

    monkeypatch.setattr(live_smoke, "ProfileStore", forbidden)
    monkeypatch.setattr(live_smoke, "LiveBrowserBackend", forbidden)
    with pytest.raises(RuntimeError, match="不得通过重启重置实验预算"):
        live_smoke.SmokeController(tmp_path, output)
    assert output.read_text(encoding="utf-8") == before
