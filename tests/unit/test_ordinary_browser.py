"""Real-backend configuration and lifecycle tested with a wholly synthetic driver."""

import logging
from pathlib import Path
import stat
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

from xhs_sidecar.browser import BrowserError, BrowserManager, BrowserOptions, SessionClosed
from xhs_sidecar.ordinary_browser import (
    LOGIN_OBSERVATION_SCRIPT,
    LOGIN_URL,
    OrdinaryBrowserBackend,
    launch_configuration,
)
from xhs_sidecar.profile import ProfileError, ProfileStore


@pytest.fixture
def profile(tmp_path):
    return ProfileStore(project_root=tmp_path / "project", root=tmp_path / "owned-xhs")


@pytest.fixture
def driver(monkeypatch):
    calls = []
    observations = [{"state": "LOGIN_REQUIRED"}]
    faults = {"close": 0, "startup": False}

    def record(name, value=None):
        calls.append((name, value, get_ident()))

    class Page:
        url = LOGIN_URL

        def goto(self, url, **options):
            record("goto", (url, options))
            self.url = url

        def locator(self, selector):
            record("locator", selector)
            return self

        def evaluate(self, script, **options):
            record("evaluate", (script, options))
            value = observations.pop(0) if len(observations) > 1 else observations[0]
            if isinstance(value, Exception):
                raise value
            if callable(value):
                return value()
            return value

    class Context:
        pages = [Page()]

        def set_default_timeout(self, timeout):
            record("timeout", timeout)
            if faults["startup"]:
                raise RuntimeError("SECRET_SESSION_T03")

        def set_default_navigation_timeout(self, timeout):
            record("navigation_timeout", timeout)

        def close(self):
            record("close")
            if faults["close"]:
                faults["close"] -= 1
                raise RuntimeError("SECRET_COOKIE_T03")

    class Driver:
        @property
        def chromium(self):
            return self

        def launch_persistent_context(self, **options):
            record("launch", options)
            return Context()

        def stop(self):
            record("stop")

    class Factory:
        def start(self):
            record("start")
            return Driver()

    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("PWDEBUG", raising=False)
    monkeypatch.setattr("xhs_sidecar.ordinary_browser.sync_playwright", Factory)
    return SimpleNamespace(
        calls=calls, observations=observations, faults=faults, page=Context.pages[0]
    )


def test_T03_01_ordinary_launch_configuration(profile, driver):
    options = BrowserOptions(engine="chrome", headless=False)
    manager = BrowserManager(OrdinaryBrowserBackend(profile), options)
    assert driver.calls == []
    session = manager.start()
    session.open_login()
    session.open_login()
    session.observe_login()
    session.observe_login()
    manager.close()
    launches = [value for name, value, _ in driver.calls if name == "launch"]
    assert launches == [
        {
            "user_data_dir": str(profile.get_profile_path()),
            "headless": False,
            "channel": "chrome",
            "no_viewport": True,
            "chromium_sandbox": True,
            "timeout": 15_000,
            "args": [],
        }
    ]
    assert len([name for name, _, _ in driver.calls if name == "goto"]) == 1
    assert len({thread for _, _, thread in driver.calls}) == 1
    assert driver.calls[0][2] != get_ident()
    assert launch_configuration(BrowserOptions(headless=False), "synthetic")["channel"] is None
    with pytest.raises(BrowserError):
        launch_configuration(BrowserOptions(headless=True), "synthetic")


def test_T03_02_profile_default_uses_application_data(monkeypatch, tmp_path):
    application_data = tmp_path / "app-data" / "TravelAgent"
    observed = []

    def app_data(name, appauthor):
        observed.append((name, appauthor))
        return application_data

    monkeypatch.delenv("TRAVEL_XHS_PROFILE_ROOT", raising=False)
    monkeypatch.setattr("xhs_sidecar.profile.user_data_path", app_data)
    store = ProfileStore(project_root=tmp_path / "project")
    assert store.get_profile_path() == application_data / "xhs" / "browser-profile"
    assert observed == [("TravelAgent", False)]
    assert not store.exists()
    assert not application_data.exists()


def test_profile_override_and_deletion_are_owned(monkeypatch, tmp_path):
    root = tmp_path / "development-xhs"
    monkeypatch.setenv("TRAVEL_XHS_PROFILE_ROOT", str(root))
    store = ProfileStore(project_root=tmp_path / "project")
    path = store.prepare()
    (path / "synthetic-session").write_text("SYNTHETIC", encoding="utf-8")
    assert store.exists()
    assert store.prepare() == path
    store.clear_profile()
    assert not path.exists()
    assert not store.exists()
    assert root.is_dir()
    store.clear_profile()


@pytest.mark.parametrize("suffix", ["project/cache", "Google/Chrome/User Data", "edge/Default"])
def test_profile_rejects_repository_and_daily_browser_roots(tmp_path, suffix):
    with pytest.raises(ProfileError):
        ProfileStore(project_root=tmp_path / "project", root=tmp_path / suffix)


def test_profile_refuses_foreign_data_and_tampered_ownership(tmp_path):
    root = tmp_path / "foreign"
    profile = root / "browser-profile"
    profile.mkdir(parents=True)
    precious = profile / "keep-this"
    precious.write_text("synthetic unrelated data", encoding="utf-8")
    store = ProfileStore(project_root=tmp_path / "project", root=root)
    for action in (store.prepare, store.exists, store.clear_profile):
        with pytest.raises(ProfileError):
            action()
    assert precious.exists()
    (root / ".travelagent-xhs-profile").write_text("foreign owner", encoding="utf-8")
    with pytest.raises(ProfileError):
        store.clear_profile()
    assert precious.exists()


def test_profile_rejects_other_git_checkout(tmp_path):
    other = tmp_path / "other-checkout"
    other.mkdir()
    (other / ".git").write_text("gitdir: synthetic", encoding="utf-8")
    with pytest.raises(ProfileError):
        ProfileStore(project_root=tmp_path / "project", root=other / "data")


def test_profile_rejects_unc_before_any_filesystem_inspection(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("UNC configuration must be rejected before filesystem inspection")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "resolve", unexpected)
        patch.setattr(Path, "lstat", unexpected)
        with pytest.raises(ProfileError):
            ProfileStore(
                project_root=tmp_path / "project", root=Path("//synthetic.invalid/share/xhs")
            )


def test_profile_rejects_junction_or_symlink_ancestor(monkeypatch, tmp_path):
    root = tmp_path / "redirected"
    original = Path.lstat

    def reparse(path, *args, **kwargs):
        if path == root:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT
            )
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ProfileError):
        ProfileStore(project_root=tmp_path / "project", root=root)


def test_T03_14_profile_deletion_has_bounded_retries(profile, monkeypatch):
    path = profile.prepare()
    calls = []

    def locked(target):
        calls.append(target)
        raise PermissionError("synthetic browser lock")

    monkeypatch.setattr("xhs_sidecar.profile.shutil.rmtree", locked)
    monkeypatch.setattr("xhs_sidecar.profile.time.sleep", lambda _: None)
    with pytest.raises(ProfileError):
        profile.clear_profile()
    assert calls == [path, path, path]
    assert path.exists()


def test_browser_observes_same_page_and_stable_id_is_private(profile, driver):
    driver.observations[:] = [
        {"state": "AUTHENTICATED", "stable_id": "SECRET_ACCOUNT_T03"},
        {"state": "AUTHENTICATED", "nickname": "not-an-identity"},
        {"state": "VERIFICATION_REQUIRED"},
        {"state": "LOGIN_REQUIRED"},
        {"unrecognized": True},
    ]
    manager = BrowserManager(OrdinaryBrowserBackend(profile), BrowserOptions(headless=False))
    session = manager.start()
    session.open_login()
    first = session.observe_login()
    assert first.identity.stable_id.get_secret_value() == "SECRET_ACCOUNT_T03"
    assert "SECRET_ACCOUNT_T03" not in repr(first)
    assert session.observe_login().identity.stable_id is None
    assert session.observe_login().state == "VERIFICATION_REQUIRED"
    assert session.observe_login().state == "LOGIN_REQUIRED"
    assert session.observe_login().state == "UNKNOWN"
    manager.close()
    assert [value[0] for name, value, _ in driver.calls if name == "goto"] == [LOGIN_URL]
    evaluations = [value for name, value, _ in driver.calls if name == "evaluate"]
    assert len(evaluations) == 5
    assert all(script == LOGIN_OBSERVATION_SCRIPT for script, _ in evaluations)
    for operation in (
        "fetch(",
        "reload(",
        "goto(",
        "XMLHttpRequest",
        "localStorage",
        "document.cookie",
    ):
        assert operation not in LOGIN_OBSERVATION_SCRIPT


@pytest.mark.parametrize(
    "variable",
    [
        "DEBUG",
        "PWDEBUG",
        "DEBUG_FILE",
        "PWDEBUGIMPL",
        "npm_config_pwdebug",
        "NODE_OPTIONS",
        "PLAYWRIGHT_NODEJS_PATH",
        "SELENIUM_REMOTE_URL",
    ],
)
def test_driver_debug_environment_fails_before_start(profile, driver, monkeypatch, variable):
    monkeypatch.setenv(variable, "pw:api")
    backend = OrdinaryBrowserBackend(profile)
    with pytest.raises(BrowserError):
        backend.start(BrowserOptions(headless=False))
    assert driver.calls == []
    assert not profile.exists()


def test_driver_errors_are_sanitized_and_close_failure_can_retry(profile, driver, caplog):
    caplog.set_level(logging.DEBUG)
    manager = BrowserManager(OrdinaryBrowserBackend(profile), BrowserOptions(headless=False))
    session = manager.start()
    session.open_login()
    driver.observations[:] = [RuntimeError("SECRET_COOKIE_T03 SECRET_XSEC_T03 SECRET_SESSION_T03")]
    with pytest.raises(BrowserError) as raised:
        session.observe_login()
    assert raised.value.__suppress_context__
    assert "SECRET_" not in str(raised.value)
    driver.faults["close"] = 1
    with pytest.raises(BrowserError):
        manager.close()
    with pytest.raises(SessionClosed):
        session.require_open()
    with pytest.raises(SessionClosed):
        manager.start()
    assert profile.exists()
    manager.close()
    assert len([name for name, _, _ in driver.calls if name == "close"]) == 2
    assert len([name for name, _, _ in driver.calls if name == "stop"]) == 1
    assert "SECRET_" not in caplog.text


def test_partial_startup_failure_keeps_cleanup_owner(profile, driver):
    driver.faults.update(startup=True, close=1)
    backend = OrdinaryBrowserBackend(profile)
    manager = BrowserManager(backend, BrowserOptions(headless=False))
    with pytest.raises(BrowserError):
        manager.start()
    with pytest.raises(BrowserError):
        manager.start()
    assert len([name for name, _, _ in driver.calls if name == "launch"]) == 1
    manager.close()
    assert len([name for name, _, _ in driver.calls if name == "close"]) == 2
    assert len([name for name, _, _ in driver.calls if name == "stop"]) == 1


def test_native_operation_timeout_keeps_resource_until_confirmed_close(
    profile, driver, monkeypatch
):
    manager = BrowserManager(OrdinaryBrowserBackend(profile), BrowserOptions(headless=False))
    session = manager.start()
    session.open_login()
    gate = Event()

    def pending_observation():
        gate.wait(3)
        return {"state": "AUTHENTICATED", "stable_id": "SECRET_ACCOUNT_T03"}

    driver.observations[:] = [pending_observation]
    monkeypatch.setattr("xhs_sidecar.ordinary_browser._OPERATION_TIMEOUT", 0.02)
    try:
        with pytest.raises(BrowserError):
            session.observe_login()
        with pytest.raises(BrowserError):
            manager.close()
        with pytest.raises(SessionClosed):
            manager.start()
        assert profile.exists()
    finally:
        gate.set()
        monkeypatch.setattr("xhs_sidecar.ordinary_browser._OPERATION_TIMEOUT", 2)
        manager.close()
    assert len([name for name, _, _ in driver.calls if name == "close"]) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://foreign.invalid/explore",
        "https://www.xiaohongshu.com.evil.invalid/explore",
        "http://www.xiaohongshu.com/explore",
        "https://www.xiaohongshu.com:8443/explore",
        "about:blank",
        "https://[invalid-host",
    ],
)
def test_foreign_origin_never_evaluates_login_dom(profile, driver, url):
    manager = BrowserManager(OrdinaryBrowserBackend(profile), BrowserOptions(headless=False))
    session = manager.start()
    session.open_login()
    driver.page.url = url
    driver.observations[:] = [{"state": "AUTHENTICATED", "stable_id": "SECRET_ACCOUNT_T03"}]
    try:
        assert session.observe_login().state == "UNKNOWN"
        assert not any(name in {"locator", "evaluate"} for name, _, _ in driver.calls)
        assert len([name for name, _, _ in driver.calls if name == "goto"]) == 1
    finally:
        manager.close()
