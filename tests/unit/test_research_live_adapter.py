"""Live-adapter boundaries with synthetic pages and no real browser or login."""

from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from travel_agent.research.live import LiveResearchReader, _stopped
from travel_agent.research.models import Candidate, ResearchStopped
from xhs_sidecar.browser import BrowserSession, FakeBrowserResource, SessionClosed
from xhs_sidecar.live_page import LiveReadStopped


NOTE_ID = "synthetic-research-note"
SOURCE_ID = f"xhs:{NOTE_ID}"


def search_payload():
    return {
        "feeds": [{"id": NOTE_ID, "modelType": "note", "noteCard": {
            "displayTitle": "合成川西路线", "type": "normal",
        }}],
        "links": [{"note_id": NOTE_ID, "href": (
            f"https://www.xiaohongshu.com/explore/{NOTE_ID}"
            "?xsec_token=SECRET_XSEC_T05&xsec_source=synthetic"
        )}],
    }


def detail_payload():
    return {
        "http_status": 200,
        "note": {"noteId": NOTE_ID, "title": "合成标题", "type": "normal",
                 "desc": "合成正文：路线可分两天体验。\n图片信息未分析。", "imageList": [{}, {}]},
        "dom_body_found": True, "dom_body": "不完全一致的合成 DOM",
        "expandable": None, "truncated": None,
    }


class FakePolicy:
    def __init__(self):
        self.disabled = False

    def snapshot(self):
        return {"requested": "TEXT_FIRST", "optimization_disabled": self.disabled}


class FakeBrowser:
    def __init__(self):
        self.session = BrowserSession(FakeBrowserResource())
        self.get_calls = 0

    def get_session(self):
        self.get_calls += 1
        if self.session is None:
            raise SessionClosed()
        self.session.require_open()
        return self.session


class FakeRedactor:
    def __init__(self):
        self.registered = []

    def register(self, value):
        self.registered.append(value)


class FakeLogin:
    def __init__(self, browser):
        self.browser = browser
        self.state = SimpleNamespace(status="AUTHENTICATED", generation=1)
        self.after_connect = "AUTHENTICATED"
        self.connect_calls = self.shutdown_calls = self.disconnect_calls = 0
        self.audit = SimpleNamespace(redactor=FakeRedactor())

    def status(self):
        return self.state

    def connect(self):
        self.connect_calls += 1
        self.state.status = self.after_connect

    def shutdown(self):
        self.shutdown_calls += 1
        self.state.status = "SESSION_PRESENT_UNVERIFIED"
        self.browser.session._close()

    def disconnect(self):
        self.disconnect_calls += 1
        raise AssertionError("本阶段不得删除 profile")


class FakeObserver:
    def __init__(self):
        self.stop_code = None
        self.finishes = 0

    def finish_window(self):
        self.finishes += 1


class FakeBackend:
    def __init__(self):
        self.resource = None
        self.resource_policy = FakePolicy()
        self.login_window_open = False
        self.search_payload = search_payload()
        self.detail_payload = detail_payload()
        self.search_calls = self.detail_calls = self.disable_calls = 0
        self.search_error = self.detail_error = None
        self.on_search = self.on_detail = None

    def search(self, session, query):
        self.search_calls += 1
        if self.on_search:
            self.on_search()
        if self.search_error:
            raise self.search_error
        return self.search_payload

    def detail(self, session, **kwargs):
        self.detail_calls += 1
        assert kwargs["note_id"] == NOTE_ID
        assert "SECRET_XSEC_T05" in kwargs["href"]
        if self.on_detail:
            self.on_detail()
        if self.detail_error:
            raise self.detail_error
        return self.detail_payload

    def disable_text_first(self):
        self.disable_calls += 1
        self.resource_policy.disabled = True


@pytest.fixture
def reader():
    result = object.__new__(LiveResearchReader)
    result.profile = SimpleNamespace(exists=lambda: True)
    result.profile_present_at_start = True
    result.browser = FakeBrowser()
    result.login = FakeLogin(result.browser)
    result.backend = FakeBackend()
    result.observer = FakeObserver()
    result._candidates = {}
    result._session = result.browser.session
    result._generation = 1
    result.login_state = "AUTHENTICATED"
    result.closed = False
    result.connect_calls = 0
    result.detail_summaries = []
    result.search_summary = None
    result.browser_info = {}
    result._last_operation = 0.0
    # Pacing is independent of these state/identity tests; no wall-clock waits.
    def no_pacing():
        result._scope()
    result._pace = no_pacing
    return result


def selected(reader):
    return reader.search("合成研究关键词")[0]


def test_text_first_reads_real_policy_keys_and_disable_is_local(reader):
    assert reader.text_first is True
    reader.disable_text_first()
    assert reader.text_first is False
    assert reader.backend.disable_calls == 1
    assert reader.backend.search_calls == reader.backend.detail_calls == 0


@pytest.mark.parametrize("change", ["generation", "session", "logout"])
def test_search_late_result_cannot_update_candidates_or_summary(reader, change):
    def invalidate():
        if change == "generation":
            reader.login.state.generation += 1
        elif change == "session":
            reader.browser.session = BrowserSession(FakeBrowserResource())
        else:
            reader.login.state.status = "DISCONNECTED"
    reader.backend.on_search = invalidate
    with pytest.raises(ResearchStopped) as error:
        reader.search("合成研究关键词")
    assert error.value.reason == "NEED_LOGIN"
    assert reader._candidates == {}
    assert reader.search_summary is None
    assert reader.backend.search_calls == 1
    assert reader.login.connect_calls == 0


@pytest.mark.parametrize("change", ["generation", "session", "logout"])
def test_detail_late_result_cannot_update_summary_or_return_material(reader, change):
    candidate = selected(reader)
    def invalidate():
        if change == "generation":
            reader.login.state.generation += 1
        elif change == "session":
            reader.browser.session = BrowserSession(FakeBrowserResource())
        else:
            reader.login.state.status = "DISCONNECTED"
    reader.backend.on_detail = invalidate
    with pytest.raises(ResearchStopped) as error:
        reader.detail(candidate, 1)
    assert error.value.reason == "NEED_LOGIN"
    assert reader.detail_summaries == []
    assert reader.backend.detail_calls == 1
    assert reader.login.connect_calls == 0


def test_unknown_or_cross_session_locator_is_rejected_before_backend(reader):
    with pytest.raises(ResearchStopped) as error:
        reader.detail(Candidate("xhs:unobserved", None, "normal", True), 1)
    assert error.value.code == "NO_LOCATOR" and not error.value.fallback_eligible
    candidate = selected(reader)
    observed = reader._candidates[SOURCE_ID]
    reader._candidates[SOURCE_ID] = replace(
        observed, locator=replace(observed.locator, session_id="foreign-session"),
    )
    with pytest.raises(ResearchStopped) as error:
        reader.detail(candidate, 1)
    assert error.value.code == "NO_LOCATOR" and not error.value.fallback_eligible
    assert reader.backend.detail_calls == 0


@pytest.mark.parametrize("status", ["LOGIN_REQUIRED", "WAITING_USER"])
def test_connect_stops_on_normal_login_need_without_auto_retry(reader, status):
    reader.login.state.status = "SESSION_PRESENT_UNVERIFIED"
    reader.login.after_connect = status
    with pytest.raises(ResearchStopped) as error:
        reader.connect()
    assert error.value.reason == "NEED_LOGIN"
    assert reader.login.connect_calls == 1
    assert reader.backend.search_calls == reader.backend.detail_calls == 0


def test_connect_stops_on_verification_without_auto_retry(reader):
    reader.login.state.status = "SESSION_PRESENT_UNVERIFIED"
    reader.login.after_connect = "VERIFICATION_REQUIRED"
    with pytest.raises(ResearchStopped) as error:
        reader.connect()
    assert error.value.reason == "VERIFICATION_REQUIRED"
    assert reader.login.connect_calls == 1


def test_authenticated_connect_reuses_scope_without_reconnecting(reader):
    reader.connect()
    assert reader.connect_calls == 1
    assert reader.login.connect_calls == 0
    assert reader._session is reader.browser.session


def test_profile_reuse_connect_finishes_existing_login_window(reader):
    reader.login.state.status = "SESSION_PRESENT_UNVERIFIED"
    reader.backend.login_window_open = True
    reader.connect()
    assert reader.login.connect_calls == 1
    assert reader.observer.finishes == 1
    assert reader.backend.login_window_open is False
    assert reader._session is reader.browser.session
    assert reader._generation == reader.login.state.generation


def test_scope_preserves_verification_reason_and_never_reconnects(reader):
    reader.login.state.status = "VERIFICATION_REQUIRED"
    with pytest.raises(ResearchStopped) as error:
        reader.search("合成研究关键词")
    assert error.value.reason == "VERIFICATION_REQUIRED"
    assert reader.login.connect_calls == reader.backend.search_calls == 0


@pytest.mark.parametrize("code", ["RATE_LIMITED", "ACCESS_RESTRICTED"])
@pytest.mark.parametrize("status", ["AUTHENTICATED", "SESSION_PRESENT_UNVERIFIED"])
def test_observed_network_restriction_stops_before_connect_or_read(reader, code, status):
    reader.observer.stop_code = code
    reader.login.state.status = status
    with pytest.raises(ResearchStopped) as error:
        reader.connect()
    assert error.value.code == code and not error.value.fallback_eligible
    with pytest.raises(ResearchStopped) as error:
        reader.search("合成研究关键词")
    assert error.value.code == code and not error.value.fallback_eligible
    assert reader.login.connect_calls == reader.backend.search_calls == 0


@pytest.mark.parametrize("code", [
    "VERIFICATION_REQUIRED", "NEED_LOGIN", "STALE_SESSION", "RATE_LIMITED",
    "ACCESS_RESTRICTED", "ACCESS_DENIED", "NOT_FOUND", "ACCESS_LOCATOR_INVALID",
    "IDENTITY_MISMATCH", "NO_LOCATOR", "REDIRECTED_OTHER_VALID_XHS_PAGE",
])
def test_restricted_or_identity_detail_failure_never_qualifies_for_fallback(reader, code):
    candidate = selected(reader)
    reader.backend.detail_error = LiveReadStopped(code)
    with pytest.raises(ResearchStopped) as error:
        reader.detail(candidate, 1)
    assert error.value.code == code
    assert error.value.fallback_eligible is False
    assert reader.backend.detail_calls == 1
    assert reader.detail_summaries == []


@pytest.mark.parametrize("code", ["BROWSER_ERROR", "PARSE_ERROR", "UNKNOWN"])
def test_technical_detail_failure_is_eligible_but_adapter_does_not_retry(reader, code):
    candidate = selected(reader)
    reader.backend.detail_error = LiveReadStopped(code)
    with pytest.raises(ResearchStopped) as error:
        reader.detail(candidate, 1)
    assert error.value.fallback_eligible is True
    assert reader.backend.detail_calls == 1
    assert reader.login.connect_calls == 0
    assert reader.detail_summaries == []


def test_search_parse_failure_disables_text_first_without_fallback(reader):
    reader.backend.search_payload = {"feeds": "invalid"}
    with pytest.raises(ResearchStopped) as error:
        reader.search("合成研究关键词")
    assert error.value.code == "PARSE_ERROR" and not error.value.fallback_eligible
    assert reader.backend.disable_calls == 1
    assert reader.backend.search_calls == 1


def test_parser_identity_mismatch_is_not_treated_as_generic_retryable_parse_error(reader):
    candidate = selected(reader)
    reader.backend.detail_payload["note"]["noteId"] = "foreign-note"
    with pytest.raises(ResearchStopped) as error:
        reader.detail(candidate, 1)
    assert error.value.code == "IDENTITY_MISMATCH"
    assert error.value.fallback_eligible is False
    assert reader.backend.detail_calls == 1
    assert reader.detail_summaries == []


@pytest.mark.parametrize("timestamp", [1790035200, 1790035200000])
def test_metadata_timestamp_accepts_seconds_and_milliseconds_without_travel_date(reader, timestamp):
    candidate = selected(reader)
    reader.backend.detail_payload["note"]["time"] = timestamp
    material = reader.detail(candidate, 1)
    expected = datetime.fromtimestamp(1790035200, timezone.utc).isoformat()
    assert material.published_at == expected
    assert datetime.fromisoformat(material.fetched_at).tzinfo is not None
    assert "travel_time" not in asdict(material)
    assert material.completeness == "PARTIAL_TEXT"
    assert material.image_count == 2


@pytest.mark.parametrize("timestamp", [None, True, 0, -1, "2026-09-22", 1790035200.0, 10**100])
def test_absent_or_unusable_publication_time_remains_unknown(reader, timestamp):
    candidate = selected(reader)
    reader.backend.detail_payload["note"]["time"] = timestamp
    assert reader.detail(candidate, 1).published_at is None


def test_safe_adapter_summaries_exclude_body_title_credentials_and_raw_note_id(reader, capsys, caplog):
    reader.backend.search_payload["feeds"][0]["noteCard"]["displayTitle"] = "SECRET_TITLE_T05"
    candidate = selected(reader)
    reader.backend.detail_payload["note"]["desc"] = "SECRET_BODY_T05"
    reader.backend.detail_payload["note"]["title"] = "SECRET_TITLE_T05"
    material = reader.detail(candidate, 1)
    assert material.body == "SECRET_BODY_T05"  # Private material remains available to extraction.
    output = json.dumps(reader.search_summary) + json.dumps(reader.detail_summaries)
    captured = capsys.readouterr()
    output += captured.out + captured.err + caplog.text
    for private in ("SECRET_BODY_T05", "SECRET_TITLE_T05", "SECRET_XSEC_T05", NOTE_ID, "xsec_token"):
        assert private not in output
    assert len(reader.login.audit.redactor.registered) == 2


def test_close_retains_profile_and_revokes_local_materials_without_disconnect(reader):
    selected(reader)
    reader.close()
    reader.close()
    assert reader.closed is True
    assert reader.login.shutdown_calls == 1
    assert reader.login.disconnect_calls == 0
    assert reader._candidates == {} and reader._session is None
    assert reader.login.state.status == "SESSION_PRESENT_UNVERIFIED"


def test_unknown_failure_is_not_misreported_as_login_expiry():
    error = _stopped("UNRECOGNIZED_ERROR")
    assert error.reason == "SOURCE_UNAVAILABLE"
    assert error.fallback_eligible is False
