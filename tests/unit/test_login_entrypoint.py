"""Entrypoints stay local and dormant until an explicit connect command."""

import json
from pathlib import Path
import runpy

import pytest

from xhs_sidecar.__main__ import main
from xhs_sidecar.profile import ProfileStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("engine", ["chrome", "chromium"])
def test_login_server_startup_only_recognizes_local_profile(tmp_path, monkeypatch, engine):
    root = tmp_path / "owned-xhs"
    ProfileStore(ROOT, root).prepare()
    monkeypatch.setenv("TRAVEL_XHS_SIDECAR_MODE", "login")
    monkeypatch.setenv("TRAVEL_XHS_PROFILE_ROOT", str(root))
    monkeypatch.setenv("TRAVEL_XHS_SIDECAR_SECRET", "SYNTHETIC_LOCAL_SECRET_" * 2)
    monkeypatch.setenv("TRAVEL_XHS_BROWSER", engine)
    captured = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.append((app, kwargs)))

    def forbidden_start(*args, **kwargs):
        pytest.fail("仅启动本地服务不应启动浏览器")

    monkeypatch.setattr(
        "xhs_sidecar.ordinary_browser.OrdinaryBrowserBackend.start", forbidden_start
    )
    assert main() == 0
    app, options = captured[0]
    assert options["host"] == "127.0.0.1"
    assert options["access_log"] is False
    assert app.state.login.status().status == "SESSION_PRESENT_UNVERIFIED"
    assert app.state.login.status().remote_checked is False
    assert app.state.login.browser.options.engine == engine
    assert app.state.login.browser.options.headless is False
    app.state.login.shutdown()


def test_launcher_rejects_unsafe_profile_without_traceback(monkeypatch, capsys):
    monkeypatch.setenv("TRAVEL_XHS_SIDECAR_MODE", "login")
    monkeypatch.setenv("TRAVEL_XHS_PROFILE_ROOT", str(ROOT / "browser-profile"))
    monkeypatch.setenv("TRAVEL_XHS_SIDECAR_SECRET", "SECRET_SESSION_T03" * 3)
    assert main() == 2
    output = capsys.readouterr()
    assert "SECRET_SESSION_T03" not in output.err
    assert str(ROOT) not in output.err
    assert "Traceback" not in output.err


@pytest.mark.parametrize(
    "command,method", [("status", "GET"), ("connect", "POST"), ("disconnect", "POST")]
)
def test_login_cli_only_uses_fixed_local_endpoint(monkeypatch, capsys, command, method):
    namespace = runpy.run_path(str(ROOT / "scripts/xhs_login.py"), run_name="test_login_control")
    command_main = namespace["main"]
    monkeypatch.setenv("TRAVEL_XHS_SIDECAR_SECRET", "SECRET_SESSION_T03" * 3)
    monkeypatch.setattr("sys.argv", ["xhs_login.py", command])
    calls = []

    class LocalResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps({"mode": "login", "status": "DISCONNECTED"}).encode()

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            assert timeout == 50
            return LocalResponse()

    def opener(*handlers):
        assert handlers[0].proxies == {}
        assert isinstance(handlers[1], namespace["NoRedirect"])
        return Opener()

    monkeypatch.setitem(command_main.__globals__, "build_opener", opener)
    assert command_main() == 0
    assert calls[0].full_url == f"http://127.0.0.1:18061/v1/login/{command}"
    assert calls[0].method == method
    assert "SECRET_SESSION_T03" not in capsys.readouterr().out
