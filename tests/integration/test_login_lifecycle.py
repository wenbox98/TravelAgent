"""T03 login lifecycle acceptance using owned temporary profiles and local fakes only."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from threading import Barrier, Condition, Event, Lock
from time import monotonic

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from xhs_sidecar.app import SidecarConfig, create_app
from xhs_sidecar.browser import AccountIdentity, BrowserManager, LoginObservation
from xhs_sidecar.login import LoginLifecycle
from xhs_sidecar.models import LoginEvidence
from xhs_sidecar.profile import ProfileStore
from xhs_sidecar.service import SidecarService

ROOT = Path(__file__).resolve().parents[2]
SECRET = "SYNTHETIC_LOCAL_T03_SECRET_" * 2


class LocalLoginResource:
    def __init__(self, observation=None):
        self.observation = observation or LoginObservation("LOGIN_REQUIRED")
        self.navigations = 0
        self.external_operations = 0
        self.observations = 0
        self.closed = False
        self.close_hook = None
        self.changed = Condition()

    def open_login(self):
        self.navigations += 1
        self.external_operations += 1

    def observe_login(self):
        with self.changed:
            self.observations += 1
            self.changed.notify_all()
            return self.observation

    def set_observation(self, observation):
        with self.changed:
            self.observation = observation

    def wait_observations(self, count):
        with self.changed:
            assert self.changed.wait_for(lambda: self.observations >= count, timeout=3)

    def close(self):
        if self.close_hook is not None:
            self.close_hook()
        self.closed = True


class LocalLoginBackend:
    kind = "fake"

    def __init__(self, observation=None):
        self.observation = observation
        self.resources = []
        self.lock = Lock()

    @property
    def starts(self):
        return len(self.resources)

    def start(self, options):
        with self.lock:
            resource = LocalLoginResource(self.observation)
            self.resources.append(resource)
            return resource


def wait_status(lifecycle, expected):
    deadline = monotonic() + 3
    pulse = Event()
    while monotonic() < deadline:
        snapshot = lifecycle.status()
        if snapshot.status == expected:
            return snapshot
        pulse.wait(0.002)
    pytest.fail(f"登录状态未到达 {expected}，当前为 {lifecycle.status().status}")


@pytest.fixture
def rig(tmp_path):
    profile = ProfileStore(project_root=ROOT, root=tmp_path / "owned-xhs")
    backend = LocalLoginBackend()
    browser = BrowserManager(backend)
    lifecycle = LoginLifecycle(browser, profile, poll_interval=0.005, timeout=10)
    yield lifecycle, backend, profile
    lifecycle.shutdown()


def make_client(lifecycle):
    service = SidecarService(browser=lifecycle.browser)
    app = create_app(SidecarConfig(secret=SecretStr(SECRET)), service=service, login=lifecycle)
    return TestClient(
        app,
        base_url="http://127.0.0.1:18061",
        headers={"Authorization": "Bearer " + SECRET},
    )


def test_T03_03_existing_profile_is_unverified_without_browser_or_network(tmp_path):
    profile = ProfileStore(project_root=ROOT, root=tmp_path / "owned-xhs")
    profile.prepare()
    backend = LocalLoginBackend()
    lifecycle = LoginLifecycle(BrowserManager(backend), profile)
    try:
        state = lifecycle.status()
        assert state.status == "SESSION_PRESENT_UNVERIFIED"
        assert state.remote_checked is False
        assert state.account_identity == "UNKNOWN"
        assert state.login_status_external_requests == 0
        assert backend.starts == 0
    finally:
        lifecycle.shutdown()


def test_T03_04_one_hundred_status_gets_have_no_browser_or_external_operations(rig):
    lifecycle, backend, _ = rig
    with make_client(lifecycle) as client:
        for _ in range(100):
            response = client.get("/v1/login/status")
            assert response.status_code == 200
            assert response.json()["status"] == "DISCONNECTED"
            assert response.json()["login_status_external_requests"] == 0
        assert backend.starts == 0
        assert sum(resource.navigations for resource in backend.resources) == 0
        assert sum(resource.external_operations for resource in backend.resources) == 0
        assert sum(resource.observations for resource in backend.resources) == 0


def test_T03_05_connect_and_observation_use_one_browser_session(rig):
    lifecycle, backend, _ = rig
    with make_client(lifecycle) as client:
        response = client.post("/v1/login/connect")
        assert response.status_code == 200
        wait_status(lifecycle, "WAITING_USER")
        resource = backend.resources[0]
        session = lifecycle.browser.get_session()
        resource.set_observation(LoginObservation("AUTHENTICATED"))
        wait_status(lifecycle, "AUTHENTICATED")
        assert lifecycle.browser.get_session() is session
        assert backend.starts == resource.navigations == 1
        assert resource.closed is False


def test_T03_06_repeated_connect_returns_existing_waiting_flow(rig):
    lifecycle, backend, _ = rig
    lifecycle.connect()
    first = wait_status(lifecycle, "WAITING_USER")
    for _ in range(20):
        repeated = lifecycle.connect()
        assert repeated.flow_id == first.flow_id
        assert repeated.generation == first.generation
    assert backend.starts == backend.resources[0].navigations == 1


def test_T03_07_concurrent_connect_has_one_flow_and_one_browser(rig):
    lifecycle, backend, _ = rig
    ready = Barrier(8)

    def connect():
        ready.wait(timeout=3)
        return lifecycle.connect()

    with ThreadPoolExecutor(max_workers=8) as workers:
        states = list(workers.map(lambda _: connect(), range(8)))
    wait_status(lifecycle, "WAITING_USER")
    assert len({state.flow_id for state in states}) == 1
    assert len({state.generation for state in states}) == 1
    assert states[0].flow_id is not None
    assert backend.starts == backend.resources[0].navigations == 1


def test_T03_08_authenticated_identity_is_private_and_unknown_is_explicit(rig):
    lifecycle, backend, _ = rig
    account = "SYNTHETIC_PRIVATE_ACCOUNT_T03"
    backend.observation = LoginObservation(
        "AUTHENTICATED", AccountIdentity(stable_id=SecretStr(account))
    )
    lifecycle.connect()
    state = wait_status(lifecycle, "AUTHENTICATED")
    assert state.account_identity == "KNOWN"
    assert state.remote_checked is True
    assert account not in state.model_dump_json()
    lifecycle.cancel()
    backend.observation = LoginObservation("AUTHENTICATED")
    lifecycle.connect()
    assert wait_status(lifecycle, "AUTHENTICATED").account_identity == "UNKNOWN"


def test_T03_09_expired_profile_requires_login_in_same_browser(rig):
    lifecycle, backend, profile = rig
    profile.prepare()
    lifecycle.connect()
    state = wait_status(lifecycle, "LOGIN_REQUIRED")
    resource = backend.resources[0]
    resource.set_observation(LoginObservation("AUTHENTICATED"))
    authenticated = wait_status(lifecycle, "AUTHENTICATED")
    assert authenticated.flow_id == state.flow_id
    assert backend.starts == resource.navigations == 1


def test_expiration_after_authentication_is_checked_only_on_explicit_connect(rig):
    lifecycle, backend, _ = rig
    backend.observation = LoginObservation("AUTHENTICATED")
    with make_client(lifecycle) as client:
        client.post("/v1/login/connect")
        authenticated = wait_status(lifecycle, "AUTHENTICATED")
        resource = backend.resources[0]
        session = lifecycle.browser.get_session()
        resource.set_observation(LoginObservation("LOGIN_REQUIRED"))
        observations = resource.observations
        for _ in range(100):
            response = client.get("/v1/login/status")
            assert response.json()["status"] == "AUTHENTICATED"
            assert response.json()["login_status_external_requests"] == 0
        assert resource.observations == observations
        client.post("/v1/login/connect")
        expired = wait_status(lifecycle, "LOGIN_REQUIRED")
        assert expired.generation > authenticated.generation
        assert lifecycle.browser.get_session() is session
        assert backend.starts == resource.navigations == resource.external_operations == 1


def test_T03_10_verification_pauses_until_explicit_resume_on_same_page(rig):
    lifecycle, backend, _ = rig
    backend.observation = LoginObservation("VERIFICATION_REQUIRED")
    lifecycle.connect()
    challenge = wait_status(lifecycle, "VERIFICATION_REQUIRED")
    resource = backend.resources[0]
    count = resource.observations
    for _ in range(20):
        assert lifecycle.connect().flow_id == challenge.flow_id
    with resource.changed:
        assert not resource.changed.wait_for(lambda: resource.observations > count, timeout=0.05)
    resource.set_observation(LoginObservation("AUTHENTICATED"))
    lifecycle.resume()
    resumed = wait_status(lifecycle, "AUTHENTICATED")
    assert resumed.flow_id == challenge.flow_id
    assert backend.starts == resource.navigations == 1


def test_T03_11_disconnect_invalidates_generation_before_browser_close(rig):
    lifecycle, backend, _ = rig
    lifecycle.connect()
    before = wait_status(lifecycle, "WAITING_USER")
    generations_at_close = []
    backend.resources[0].close_hook = lambda: generations_at_close.append(
        lifecycle.status().generation
    )
    after = lifecycle.disconnect()
    assert after.status == "DISCONNECTED"
    assert after.generation > before.generation
    assert generations_at_close == [after.generation]


def test_T03_12_late_authenticated_result_cannot_overwrite_new_generation(rig):
    lifecycle, backend, _ = rig
    lifecycle.connect()
    old = wait_status(lifecycle, "WAITING_USER")
    lifecycle.disconnect()
    lifecycle.connect()
    current = wait_status(lifecycle, "WAITING_USER")
    accepted = lifecycle._apply_observation(old.generation, LoginObservation("AUTHENTICATED"))
    assert accepted is False
    assert lifecycle.status() == current
    assert current.generation > old.generation
    assert current.flow_id != old.flow_id
    assert backend.starts == 2


def test_T03_13_disconnect_closes_browser_before_removing_profile(rig, monkeypatch):
    lifecycle, backend, profile = rig
    lifecycle.connect()
    wait_status(lifecycle, "WAITING_USER")
    marker = profile.get_profile_path() / "synthetic-session.txt"
    marker.write_text("SYNTHETIC_LOCAL_SESSION", encoding="utf-8")
    original_clear = profile.clear_profile

    def clear_after_close():
        assert backend.resources[0].closed
        original_clear()

    monkeypatch.setattr(profile, "clear_profile", clear_after_close)
    assert lifecycle.disconnect().status == "DISCONNECTED"
    assert not profile.get_profile_path().exists()
    assert not marker.exists()


def test_T03_14_failed_profile_cleanup_reports_error_and_retains_data(rig, monkeypatch):
    lifecycle, backend, profile = rig
    lifecycle.connect()
    wait_status(lifecycle, "WAITING_USER")

    def locked_profile():
        raise PermissionError("SYNTHETIC_FILE_LOCK")

    monkeypatch.setattr(profile, "clear_profile", locked_profile)
    state = lifecycle.disconnect()
    assert state.status == "ERROR"
    assert state.error_code is not None
    assert backend.resources[0].closed
    assert profile.exists()


def test_T03_15_restart_preserves_profile_without_automatic_check(rig):
    first, backend, profile = rig
    backend.observation = LoginObservation("AUTHENTICATED")
    first.connect()
    wait_status(first, "AUTHENTICATED")
    first.shutdown()
    assert profile.exists()
    assert backend.resources[0].closed
    restarted_backend = LocalLoginBackend(LoginObservation("AUTHENTICATED"))
    restarted = LoginLifecycle(BrowserManager(restarted_backend), profile, poll_interval=0.005)
    try:
        assert restarted.status().status == "SESSION_PRESENT_UNVERIFIED"
        assert restarted.status().remote_checked is False
        assert restarted_backend.starts == 0
        restarted.connect()
        wait_status(restarted, "AUTHENTICATED")
        assert restarted_backend.starts == restarted_backend.resources[0].navigations == 1
    finally:
        restarted.shutdown()


def test_T03_17_repeated_dom_checks_never_create_or_navigate_again(rig):
    lifecycle, backend, _ = rig
    lifecycle.connect()
    wait_status(lifecycle, "WAITING_USER")
    resource = backend.resources[0]
    resource.wait_observations(12)
    assert backend.starts == resource.navigations == resource.external_operations == 1


def test_T03_18_unmeasured_login_network_totals_remain_unknown(rig):
    lifecycle, _, _ = rig
    with make_client(lifecycle) as client:
        client.post("/v1/login/connect")
        wait_status(lifecycle, "WAITING_USER")
        result = client.get("/v1/metrics")
        assert result.status_code == 200
        metrics = result.json()
        assert metrics["login_status_external_requests"] == 0
        assert metrics["measurement"] == "NOT_MEASURED"
        assert metrics["browser_navigation"] is None
        assert metrics["total_requests"] is None
        assert metrics["total_bytes"] is None
        assert metrics["requests"] == dict.fromkeys(
            ["document", "xhr_fetch", "image", "media", "other"]
        )


def test_login_mode_blocks_browser_bypass_and_research_routes(rig):
    lifecycle, backend, _ = rig
    with make_client(lifecycle) as client:
        for path, payload in (
            ("/v1/browser/session", None),
            ("/v1/feeds/search", {"keyword": "合成测试"}),
            ("/v1/feeds/detail", {"note_handle": "0" * 32}),
        ):
            assert client.post(path, json=payload).status_code == 409
        assert backend.starts == 0


def test_cancel_revokes_generation_and_preserves_profile(rig):
    lifecycle, backend, profile = rig
    lifecycle.connect()
    before = wait_status(lifecycle, "WAITING_USER")
    cancelled = lifecycle.cancel()
    assert cancelled.status == "CANCELLED"
    assert cancelled.generation > before.generation
    assert backend.resources[0].closed
    assert profile.exists()
    assert (
        lifecycle._apply_observation(before.generation, LoginObservation("AUTHENTICATED")) is False
    )
    assert lifecycle.status().status == "CANCELLED"


def test_browser_close_failure_never_deletes_profile_or_claims_disconnected(rig, monkeypatch):
    lifecycle, backend, profile = rig
    lifecycle.connect()
    wait_status(lifecycle, "WAITING_USER")
    clear_calls = []

    def fail_close():
        raise RuntimeError("SYNTHETIC_CLOSE_FAILURE")

    backend.resources[0].close_hook = fail_close
    monkeypatch.setattr(profile, "clear_profile", lambda: clear_calls.append(True))
    state = lifecycle.disconnect()
    assert state.status == "ERROR"
    assert state.error_code is not None
    assert clear_calls == []
    assert profile.exists()
    assert lifecycle.connect() == state
    assert backend.starts == 1


def test_resume_during_verification_worker_exit_is_not_lost(rig, monkeypatch):
    lifecycle, backend, _ = rig
    backend.observation = LoginObservation("VERIFICATION_REQUIRED")
    publish = lifecycle._apply_observation
    published, finish_previous = Event(), Event()

    def delay_worker_exit(generation, observation):
        accepted = publish(generation, observation)
        if observation.state == "VERIFICATION_REQUIRED":
            published.set()
            assert finish_previous.wait(3)
        return accepted

    monkeypatch.setattr(lifecycle, "_apply_observation", delay_worker_exit)
    lifecycle.connect()
    assert published.wait(3)
    resource = backend.resources[0]
    resource.set_observation(LoginObservation("AUTHENTICATED"))
    with ThreadPoolExecutor(max_workers=1) as worker:
        resumed = worker.submit(lifecycle.resume)
        try:
            try:
                immediate = resumed.result(timeout=0.05)
                assert immediate.status != "VERIFICATION_REQUIRED"
            except TimeoutError:
                pass  # Waiting for the old worker is also a valid handoff.
        finally:
            finish_previous.set()
        resumed.result(timeout=3)
    wait_status(lifecycle, "AUTHENTICATED")
    assert backend.starts == resource.navigations == 1


def test_unknown_observation_expires_with_safe_evidence_and_stops_polling(tmp_path):
    profile = ProfileStore(ROOT, root=tmp_path / "owned-xhs")
    evidence = LoginEvidence(current_url_classification="OFFICIAL_PAGE", page_ready=True)
    backend = LocalLoginBackend(LoginObservation("UNKNOWN", evidence=evidence))
    lifecycle = LoginLifecycle(
        BrowserManager(backend), profile, poll_interval=0.002, timeout=2,
        observation_timeout=0.025,
    )
    try:
        lifecycle.connect()
        failed = wait_status(lifecycle, "ERROR")
        assert failed.error_code == "LOGIN_STATE_UNCERTAIN"
        assert failed.stop_reason == "OBSERVATION_TIMEOUT"
        assert failed.evidence == evidence
        assert 1 <= failed.observation_attempts <= 480
        resource = backend.resources[0]
        count = resource.observations
        for _ in range(100):
            assert lifecycle.status() == failed
        assert lifecycle.connect() == failed
        with resource.changed:
            assert not resource.changed.wait_for(lambda: resource.observations > count, timeout=0.04)
        assert backend.starts == resource.navigations == 1
    finally:
        lifecycle.shutdown()


def test_poll_limit_bounds_even_flapping_page_signals(tmp_path, monkeypatch):
    profile = ProfileStore(ROOT, root=tmp_path / "owned-xhs")
    backend = LocalLoginBackend(LoginObservation("UNKNOWN"))
    lifecycle = LoginLifecycle(
        BrowserManager(backend), profile, poll_interval=0.002, timeout=2,
        observation_timeout=1, max_observations=4,
    )
    original = LocalLoginResource.observe_login

    def alternating(resource):
        original(resource)
        return LoginObservation("LOGIN_REQUIRED" if resource.observations % 2 == 0 else "UNKNOWN")

    monkeypatch.setattr(LocalLoginResource, "observe_login", alternating)
    try:
        lifecycle.connect()
        failed = wait_status(lifecycle, "ERROR")
        assert failed.error_code == "LOGIN_STATE_UNCERTAIN"
        assert failed.stop_reason == "OBSERVATION_LIMIT"
        assert failed.observation_attempts == backend.resources[0].observations == 4
        assert backend.starts == backend.resources[0].navigations == 1
    finally:
        lifecycle.shutdown()


def test_login_wait_has_separate_total_deadline(tmp_path):
    profile = ProfileStore(ROOT, root=tmp_path / "owned-xhs")
    backend = LocalLoginBackend(LoginObservation("LOGIN_REQUIRED"))
    lifecycle = LoginLifecycle(
        BrowserManager(backend), profile, poll_interval=0.002, timeout=0.02,
        observation_timeout=1,
    )
    try:
        lifecycle.connect()
        failed = wait_status(lifecycle, "ERROR")
        assert failed.error_code == failed.stop_reason == "LOGIN_TIMEOUT"
    finally:
        lifecycle.shutdown()


def test_late_positive_observation_cannot_authenticate_after_deadline(tmp_path, monkeypatch):
    profile = ProfileStore(ROOT, root=tmp_path / "owned-xhs")
    backend = LocalLoginBackend(LoginObservation("AUTHENTICATED"))
    lifecycle = LoginLifecycle(
        BrowserManager(backend), profile, poll_interval=0.002, timeout=0.01,
    )
    original = LocalLoginResource.observe_login

    def late(resource):
        Event().wait(0.04)
        return original(resource)

    monkeypatch.setattr(LocalLoginResource, "observe_login", late)
    try:
        lifecycle.connect()
        failed = wait_status(lifecycle, "ERROR")
        assert failed.error_code == "LOGIN_TIMEOUT"
        assert failed.account_identity == "UNKNOWN"
        assert failed.observation_attempts == 1
    finally:
        lifecycle.shutdown()


@pytest.mark.parametrize("options", [
    {"timeout": float("inf")}, {"observation_timeout": float("nan")},
    {"poll_interval": 0}, {"stop_timeout": -1}, {"max_observations": 0},
    {"max_observations": True}, {"max_observations": 10_001},
])
def test_observation_limits_must_be_finite_and_bounded(tmp_path, options):
    profile = ProfileStore(ROOT, root=tmp_path / "owned-xhs")
    with pytest.raises(ValueError):
        LoginLifecycle(BrowserManager(LocalLoginBackend()), profile, **options)
