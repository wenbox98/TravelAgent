import pytest
from concurrent.futures import ThreadPoolExecutor

from xhs_sidecar.browser import BrowserManager, SessionClosed
from xhs_sidecar.completeness import classify_completeness
from xhs_sidecar.models import RawDetail, SourceIdentity
from xhs_sidecar.observability import FakeNetworkObserver


def test_T02_01_plain_browser_defaults():
    manager = BrowserManager()
    assert manager.options.engine == "chromium"
    assert vars(manager.options) == {"engine": "chromium", "headless": True}
    assert manager.backend.kind == "fake"


def test_T02_02_session_is_reused():
    manager = BrowserManager()
    first = manager.start()
    assert manager.start() is first
    assert manager.get_session() is first
    assert manager.backend.starts == 1


def test_T02_03_closed_session_cannot_be_used():
    manager = BrowserManager()
    first = manager.start()
    manager.close()
    manager.close()
    with pytest.raises(SessionClosed):
        first.require_open()
    with pytest.raises(SessionClosed):
        manager.get_session()
    assert manager.start().session_id != first.session_id


def test_concurrent_start_has_one_owner_and_one_session():
    manager = BrowserManager()
    with ThreadPoolExecutor(max_workers=4) as workers:
        sessions = list(workers.map(lambda _: manager.start(), range(12)))
    assert all(session is sessions[0] for session in sessions)
    assert manager.backend.starts == 1
    manager.close()


def test_close_failure_still_revokes_old_session():
    class Resource:
        def close(self):
            raise RuntimeError("synthetic cleanup failure")

    class Backend:
        def start(self, options):
            return Resource()

    manager = BrowserManager(backend=Backend())
    session = manager.start()
    with pytest.raises(RuntimeError):
        manager.close()
    with pytest.raises(SessionClosed):
        session.require_open()


@pytest.mark.parametrize(
    "body,summary,verified,truncated,expected",
    [
        ("合成正文", None, False, False, "PARTIAL_TEXT"),
        ("合成正文", None, True, True, "PARTIAL_TEXT"),
        ("合成正文", None, True, False, "FULL_TEXT"),
        (None, "合成摘要", False, False, "SUMMARY_ONLY"),
        (None, None, False, False, "METADATA_ONLY"),
        ("  ", "合成摘要", True, False, "SUMMARY_ONLY"),
    ],
)
def test_T02_08_success_is_not_full_text(body, summary, verified, truncated, expected):
    raw = RawDetail(
        source=SourceIdentity(note_id="synthetic-1"),
        title="合成标题",
        body=body,
        summary=summary,
        text_scope_verified=verified,
        truncated=truncated,
        http_status=200,
    )
    assert classify_completeness(raw).completeness == expected


def test_T02_10_unmeasured_is_not_zero():
    metrics = FakeNetworkObserver().snapshot()
    assert metrics.measurement == "NOT_MEASURED"
    assert metrics.total_requests is None
    assert metrics.total_bytes is None
    assert metrics.browser_navigation is None
    assert all(value is None for value in metrics.requests.model_dump().values())


def test_synthetic_network_counts_navigation_separately_and_keeps_unknown_bytes():
    observer = FakeNetworkObserver(measured=True)
    observer.navigation()
    for category in ("document", "xhr_fetch", "image", "media", "other"):
        observer.request(category, byte_count=20 if category != "media" else None)
    metrics = observer.snapshot()
    assert metrics.measurement == "SIMULATED"
    assert metrics.browser_navigation == 1
    assert metrics.total_requests == 5
    assert metrics.total_bytes is None


def test_simulated_known_bytes_are_counted_without_network():
    observer = FakeNetworkObserver(measured=True)
    observer.request("document", byte_count=10)
    observer.request("xhr_fetch", byte_count=15)
    assert observer.snapshot().total_bytes == 25


def test_launcher_is_loopback_offline_and_does_not_accept_browser_options(monkeypatch):
    from xhs_sidecar.__main__ import main
    import uvicorn

    calls = []
    monkeypatch.setenv("TRAVEL_XHS_SIDECAR_SECRET", "SYNTHETIC_LOCAL_SECRET_" * 2)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    assert main() == 0
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["access_log"] is False
    monkeypatch.setenv("TRAVEL_XHS_SIDECAR_SECRET", "")
    assert main() == 2
    assert len(calls) == 1
