from collections import defaultdict
from dataclasses import asdict
import gc
import json
from types import SimpleNamespace
from urllib.parse import urlsplit
import weakref

import pytest

from xhs_sidecar.live_observability import LiveNetworkObserver


class FakeContext:
    def __init__(self):
        self.handlers = defaultdict(list)

    def on(self, event, handler):
        self.handlers[event].append(handler)

    def remove_listener(self, event, handler):
        self.handlers[event].remove(handler)

    def emit(self, event, value):
        for handler in tuple(self.handlers[event]):
            handler(value)


class FakeRequest:
    def __init__(self, resource="document", *, url="https://www.example.test/", main=True):
        self.url = url
        self.resource_type = resource
        self.method = "GET"
        self.frame = SimpleNamespace(parent_frame=None if main else object())

    def is_navigation_request(self):
        return self.resource_type == "document"

    @property
    def headers(self):
        raise AssertionError("SECRET_COOKIE_T04 must never be read")

    @property
    def post_data(self):
        raise AssertionError("SECRET_SESSION_T04 must never be read")

    @property
    def failure(self):
        raise AssertionError("failure text can contain a sensitive URL")


class FakeResponse:
    def __init__(self, request, status=200):
        self.request = request
        self.status = status

    @property
    def headers(self):
        raise AssertionError("SECRET_AUTHORIZATION_T04 must never be read")

    def body(self):
        raise AssertionError("SECRET_QR_CONTENT_T04 must never be read")


@pytest.fixture
def observed():
    context = FakeContext()
    observer = LiveNetworkObserver()
    observer.attach(context)
    return context, observer


def test_t04_11_unmeasured_is_not_zero_and_observed_bytes_stay_unknown(observed):
    missing = LiveNetworkObserver().snapshot()
    assert missing.measurement == "NOT_MEASURED"
    assert missing.scope == "none"
    assert missing.total_requests is None
    assert missing.browser_navigation is None
    assert all(value is None for value in missing.requests.values())
    assert missing.total_bytes is None
    _, observer = observed
    assert observer.snapshot().total_requests == 0
    assert observer.snapshot().total_bytes is None
    assert observer.snapshot("SEARCH").total_requests is None


def test_categories_main_frame_navigation_and_status_outcomes(observed):
    context, observer = observed
    observer.start_window("SEARCH")
    resources = ["document", "document", "xhr", "fetch", "image", "media", "script"]
    requests = [FakeRequest(resource, main=index != 1) for index, resource in enumerate(resources)]
    for request in requests:
        context.emit("request", request)
    for status, request in zip((200, 302, 404, 500, 200, 206), requests, strict=False):
        context.emit("response", FakeResponse(request, status))
        context.emit("requestfinished", request)
    context.emit("requestfailed", requests[-1])
    result = observer.finish_window()
    assert result.measurement == "OBSERVED"
    assert result.scope == "context_events_since_attach"
    assert result.browser_navigation == 1
    assert result.requests == {"document": 2, "xhr_fetch": 2, "image": 1, "media": 1, "other": 1}
    assert result.total_requests == 7
    assert result.response_status == {"200": 2, "302": 1, "404": 1, "500": 1, "206": 1}
    assert result.failed_requests == 1  # HTTP 4xx/5xx are responses, not transport failures.
    assert result.finished_requests == 6
    assert result.total_bytes is None
    assert result.hosts == {"www.example.test": 7}
    assert result.methods == {"GET": 7}
    assert result.callback_errors == 0
    assert len(observer._associations) == 0


def test_late_responses_belong_to_initiation_window_and_idle_is_counted(observed):
    context, observer = observed
    idle = FakeRequest("image")
    context.emit("request", idle)
    observer.start_window("SEARCH")
    search = FakeRequest("fetch")
    context.emit("request", search)
    frozen_snapshot = observer.finish_window()
    observer.start_window("DETAIL_1")
    detail = FakeRequest()
    context.emit("request", detail)
    context.emit("response", FakeResponse(search, 204))
    context.emit("requestfinished", search)
    context.emit("requestfailed", idle)
    observer.finish_window()
    assert frozen_snapshot.response_status == {}
    assert observer.snapshot("SEARCH").response_status == {"204": 1}
    assert observer.snapshot("SEARCH").finished_requests == 1
    assert observer.snapshot("DETAIL_1").response_status == {}
    assert observer.snapshot("OUTSIDE_WINDOW").failed_requests == 1
    assert observer.snapshot("OUTSIDE_WINDOW").total_requests == 1
    assert observer.snapshot().total_requests == 3


def test_purpose_is_derived_and_unclassified_xhr_remains_unknown(observed):
    context, observer = observed
    samples = [
        ("fetch", "https://www.example.test/api/comment/page?x=secret", "comment"),
        ("xhr", "https://www.example.test/api/comments", "comment"),
        ("fetch", "https://log.example.test/unknown", "analytics"),
        ("fetch", "https://www.example.test/collect", "analytics"),
        ("xhr", "https://www.example.test/unknown", "unknown"),
        ("image", "https://images.example.test/unknown", "image"),
        ("media", "https://www.example.test/unknown", "media"),
        ("document", "https://www.example.test/unknown", "document"),
        ("script", "https://www.example.test/unknown", "other"),
    ]
    for resource, url, purpose in samples:
        request = FakeRequest(resource, url=url)
        before = observer.snapshot().purposes[purpose]
        context.emit("request", request)
        assert observer.snapshot().purposes[purpose] == before + 1
    assert observer.snapshot().purpose_classification == "DERIVED"
    assert sum(observer.snapshot().purposes.values()) == len(samples)


def test_t04_12_sentinels_are_absent_from_snapshots_and_logs(observed, capsys, caplog):
    context, observer = observed
    secrets = [
        "SECRET_COOKIE_T04", "SECRET_XSEC_T04", "SECRET_SESSION_T04",
        "SECRET_AUTHORIZATION_T04", "SECRET_QR_CONTENT_T04", "SECRET_ACCOUNT_ID_T04",
    ]
    secret_text = "/".join(secrets)
    request = FakeRequest(
        "fetch", url=f"https://{secrets[0]}:password@www.example.test/{secret_text}?xsec_token={secret_text}"
    )
    cache_before = urlsplit.cache_info()
    context.emit("request", request)
    context.emit("response", FakeResponse(request))
    context.emit("requestfailed", request)
    output = json.dumps(asdict(observer.snapshot())) + repr(observer) + caplog.text
    captured = capsys.readouterr()
    output += captured.out + captured.err
    for sentinel in secrets:
        assert sentinel not in output
    assert "xsec_token" not in output
    assert "password" not in output
    assert "www.example.test" in output
    assert urlsplit.cache_info() == cache_before


def test_t04_13_operations_are_not_counted_as_http_requests(observed):
    context, observer = observed
    observer.start_window("SEARCH")
    assert observer.snapshot().total_requests == 0
    requests = [FakeRequest("image") for _ in range(9)]
    for request in requests:
        context.emit("request", request)
    assert observer.finish_window().total_requests == 9
    assert "search_operations" not in asdict(observer.snapshot())
    assert "detail_operations" not in asdict(observer.snapshot())


def test_duplicate_responses_and_events_before_attach_are_not_double_counted(observed):
    context, observer = observed
    untracked = FakeRequest()
    context.emit("response", FakeResponse(untracked))
    context.emit("requestfinished", untracked)
    assert observer.snapshot().total_requests == 0
    tracked = FakeRequest()
    context.emit("request", tracked)
    context.emit("request", tracked)
    context.emit("response", FakeResponse(tracked))
    context.emit("response", FakeResponse(tracked))
    context.emit("requestfailed", tracked)
    context.emit("requestfailed", tracked)
    assert observer.snapshot().total_requests == 1
    assert observer.snapshot().response_status == {"200": 1}
    assert observer.snapshot().failed_requests == 1


def test_bounded_associations_disclose_lost_attribution():
    context = FakeContext()
    observer = LiveNetworkObserver(max_associations=2)
    observer.attach(context)
    observer.start_window("SEARCH")
    requests = [FakeRequest("fetch") for _ in range(3)]
    for request in requests:
        context.emit("request", request)
    for request in requests:
        context.emit("response", FakeResponse(request))
    assert observer.snapshot().total_requests == 3
    assert observer.snapshot().association_losses == 1
    assert observer.snapshot("SEARCH").association_losses == 1
    assert observer.snapshot().response_status == {"200": 2}
    assert len(observer._associations) == 2


def test_observer_does_not_keep_request_objects_alive(observed):
    context, observer = observed
    request = FakeRequest()
    reference = weakref.ref(request)
    context.emit("request", request)
    del request
    gc.collect()
    assert reference() is None
    assert len(observer._associations) == 0


def test_errors_do_not_escape_callbacks_or_expose_messages(observed, capsys, caplog):
    context, observer = observed

    class BadRequest(FakeRequest):
        def is_navigation_request(self):
            raise RuntimeError("SECRET_SESSION_T04")

    request = BadRequest(url="https://[invalid")
    context.emit("request", request)
    assert observer.snapshot().total_requests == 1
    assert observer.snapshot().navigation_unknown == 1
    assert observer.snapshot().callback_errors == 1
    assert observer.snapshot().hosts == {"UNKNOWN": 1}
    assert "SECRET_SESSION_T04" not in repr(observer.snapshot()) + caplog.text
    assert capsys.readouterr().out == ""


def test_late_response_callback_error_keeps_original_window(observed):
    context, observer = observed
    observer.start_window("SEARCH")
    request = FakeRequest()
    context.emit("request", request)
    observer.finish_window()
    observer.start_window("DETAIL_1")

    class BadResponse:
        def __init__(self, request):
            self.request = request

        @property
        def status(self):
            raise RuntimeError("SECRET_XSEC_T04")

    context.emit("response", BadResponse(request))
    assert observer.snapshot("SEARCH").callback_errors == 1
    assert observer.snapshot("DETAIL_1").callback_errors == 0


def test_attach_is_idempotent_and_detach_preserves_frozen_totals(observed):
    context, observer = observed
    observer.attach(context)
    assert all(len(handlers) == 1 for handlers in context.handlers.values())
    context.emit("request", FakeRequest())
    observer.detach()
    observer.detach()
    context.emit("request", FakeRequest())
    assert observer.snapshot().total_requests == 1
    assert observer.snapshot().attachment_active is False
    assert observer.snapshot().window_finished is True
    with pytest.raises(ValueError, match="不可切换会话"):
        observer.attach(FakeContext())


def test_partial_attach_failure_removes_handlers_and_stays_unmeasured():
    class FailingContext(FakeContext):
        def on(self, event, handler):
            if event == "requestfailed":
                raise RuntimeError("SECRET_SESSION_T04")
            super().on(event, handler)

    context = FailingContext()
    observer = LiveNetworkObserver()
    with pytest.raises(ValueError, match="网络观测未启用"):
        observer.attach(context)
    assert all(not handlers for handlers in context.handlers.values())
    assert observer.snapshot().measurement == "NOT_MEASURED"


def test_window_guards_disallow_overlap_reuse_or_sensitive_labels(observed):
    _, observer = observed
    with pytest.raises(ValueError):
        observer.start_window("SECRET_ACCOUNT_ID_T04")
    with pytest.raises(ValueError):
        observer.finish_window()
    observer.start_window("SEARCH")
    with pytest.raises(ValueError):
        observer.start_window("DETAIL_1")
    observer.finish_window()
    with pytest.raises(ValueError):
        observer.start_window("SEARCH")
    with pytest.raises(ValueError):
        observer.snapshot("SECRET_ACCOUNT_ID_T04")


@pytest.mark.parametrize("resource", ["document", "xhr", "fetch"])
@pytest.mark.parametrize("host", ["xiaohongshu.com", "www.xiaohongshu.com", "edith.xiaohongshu.com"])
@pytest.mark.parametrize("status,expected", [(429, "RATE_LIMITED"), (401, "ACCESS_RESTRICTED"), (403, "ACCESS_RESTRICTED")])
def test_official_page_and_api_restrictions_latch_stop_code(
    observed, resource, host, status, expected
):
    context, observer = observed
    assert observer.stop_code is None
    request = FakeRequest(resource, url=f"https://{host}/api?xsec_token=SECRET_XSEC_T04")
    context.emit("request", request)
    context.emit("response", FakeResponse(request, status))
    assert observer.stop_code == expected
    assert observer.snapshot().response_status == {str(status): 1}
    assert observer.snapshot().failed_requests == 0


@pytest.mark.parametrize("resource,host,status", [
    ("image", "www.xiaohongshu.com", 403),
    ("media", "www.xiaohongshu.com", 429),
    ("script", "www.xiaohongshu.com", 401),
    ("fetch", "www.xiaohongshu.com.evil.test", 403),
    ("document", "evilxiaohongshu.com", 429),
    ("xhr", "www.example.test", 401),
    ("document", "www.xiaohongshu.com", 200),
    ("fetch", "www.xiaohongshu.com", 404),
    ("xhr", "www.xiaohongshu.com", 500),
])
def test_non_official_resource_or_other_status_does_not_latch(observed, resource, host, status):
    context, observer = observed
    request = FakeRequest(resource, url=f"https://{host}/")
    context.emit("request", request)
    context.emit("response", FakeResponse(request, status))
    assert observer.stop_code is None
    assert observer.snapshot().response_status == {str(status): 1}


def test_stop_signal_survives_window_end_attribution_loss_and_detach():
    context = FakeContext()
    observer = LiveNetworkObserver(max_associations=1)
    observer.attach(context)
    observer.start_window("SEARCH")
    dropped = FakeRequest("fetch", url="https://edith.xiaohongshu.com/api")
    kept = FakeRequest("image")
    context.emit("request", dropped)
    context.emit("request", kept)
    observer.finish_window()
    assert observer.snapshot().association_losses == 1
    context.emit("response", FakeResponse(dropped, 429))
    assert observer.stop_code == "RATE_LIMITED"
    # An unassociated response can latch a stop, but is never falsely counted as
    # an outcome belonging to the active operation's initiated requests.
    assert observer.snapshot().response_status == {}
    another = FakeRequest("document", url="https://xiaohongshu.com/")
    context.emit("request", another)
    context.emit("response", FakeResponse(another, 403))
    assert observer.stop_code == "RATE_LIMITED"
    assert observer.snapshot().response_status == {"403": 1}
    observer.detach()
    assert observer.stop_code == "RATE_LIMITED"
    with pytest.raises(AttributeError):
        observer.stop_code = None


def test_response_without_request_event_can_still_latch_stop(observed):
    context, observer = observed
    request = FakeRequest("xhr", url="https://edith.xiaohongshu.com/api")
    context.emit("response", FakeResponse(request, 403))
    assert observer.stop_code == "ACCESS_RESTRICTED"
    assert observer.snapshot().total_requests == 0
    assert observer.snapshot().response_status == {}
