"""Execute production read scripts in a synthetic Node VM; never open a browser."""

import json
from pathlib import Path
import subprocess
import sys
from threading import RLock
from types import SimpleNamespace

import playwright
import pytest

from xhs_sidecar.browser import BrowserSession, LoginObservation
from xhs_sidecar.live_page import (
    DETAIL_SCRIPT, SEARCH_SCRIPT, LiveBrowserBackend, LiveReadStopped,
)
from xhs_sidecar.live_parsing import LiveParseError, parse_detail, parse_search
from xhs_sidecar.models import LoginEvidence, SourceIdentity


NODE_FIXTURE = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const values = input.fixtures.map(f => {
  let effects = 0, sensitiveReads = 0;
  const blocked = () => { effects++; throw new Error('Forbidden side effect'); };
  const hidden = (object, key) => Object.defineProperty(object, key, {
    get() { sensitiveReads++; throw new Error('Forbidden field read'); }, enumerable:true
  });
  const initialState = f.initialState;
  if (f.poison && initialState?.note?.noteDetailMap) {
    const map = initialState.note.noteDetailMap;
    const row = map[f.noteId];
    hidden(row, 'comments');
    hidden(row.note, 'comments');
    hidden(row.note, 'video');
    hidden(row.note, 'xsecToken');
    for (const image of row.note.imageList || []) hidden(image, 'urlDefault');
    hidden(map, 'not-requested-note');
  }
  const document = {
    querySelectorAll(selector) {
      if (f.forbidDocumentRead) throw new Error('Unexpected DOM read');
      if (selector !== 'a[href]') throw new Error('Unexpected fixture selector');
      return (f.links || []).map(href => ({getAttribute:()=>href, click:blocked}));
    },
    querySelector(selector) {
      if (f.forbidDocumentRead) throw new Error('Unexpected DOM read');
      if (selector !== '#detail-desc, .note-content .desc, .note-scroller .desc')
        throw new Error('Unexpected fixture selector');
      return f.domBody === undefined ? null : {textContent:f.domBody, click:blocked};
    }
  };
  Object.defineProperty(document, 'cookie', {get:blocked});
  const location = {origin:f.origin || 'https://www.xiaohongshu.com',
    pathname:f.path || (input.kind === 'search' ? '/search_result' : '/explore/' + f.noteId),
    search:f.search ?? ('?keyword=' + encodeURIComponent(f.keyword || 'synthetic query'))};
  location.href = location.origin + location.pathname + location.search;
  const window = {__INITIAL_STATE__:initialState, fetch:blocked, scroll:blocked,
    scrollTo:blocked, scrollBy:blocked};
  const context = {document, location, window, URL, URLSearchParams,
    fetch:blocked, scroll:blocked, scrollTo:blocked, XMLHttpRequest:blocked,
    readArgument:input.kind === 'search' ? (f.keyword || 'synthetic query') : f.noteId};
  const value = vm.runInNewContext('(' + input.script + ')(readArgument)', context, {timeout:1000});
  return {value,effects,sensitiveReads};
});
process.stdout.write(JSON.stringify(values));
"""


def execute(script, fixtures, *, kind="search"):
    node = Path(playwright.__file__).parent / "driver" / (
        "node.exe" if sys.platform == "win32" else "node"
    )
    result = subprocess.run(
        [str(node), "-e", NODE_FIXTURE],
        input=json.dumps({"script": script, "fixtures": fixtures, "kind": kind}),
        text=True, encoding="utf-8", capture_output=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert all(value["effects"] == 0 and value["sensitiveReads"] == 0 for value in values)
    return [value["value"] for value in values]


def synthetic_feed():
    return {
        "id": "synthetic-note", "modelType": "note", "xsecToken": "SECRET_XSEC_T04",
        "noteCard": {
            "displayTitle": "合成川西路线", "type": "normal",
            "user": {"nickname": "合成作者", "cookie": "SECRET_COOKIE_T04"},
            "cover": {"urlDefault": "https://synthetic.invalid/cover"},
            "interactInfo": {"likedCount": "3"},
            "unused_private_field": "SECRET_UNUSED_T04",
        },
        "extra": "SECRET_EXTRA_T04",
    }


@pytest.mark.parametrize("wrapper", [None, "value", "_value"])
def test_actual_search_script_accepts_direct_and_vue_shapes(wrapper):
    feed = synthetic_feed()
    values = [feed]
    if wrapper is not None:
        feed["noteCard"] = {wrapper: feed["noteCard"]}
        values = {wrapper: values}
    payload = execute(SEARCH_SCRIPT, [{"initialState": {"search": {"feeds": values}}}])[0]
    parsed = parse_search(payload, "synthetic-session")
    assert len(parsed.candidates) == 1
    assert parsed.candidates[0].title == "合成川西路线"
    assert payload["state_available"] is True and payload["batch_capped"] is False
    serialized = json.dumps(payload)
    assert "SECRET_UNUSED_T04" not in serialized
    assert "SECRET_EXTRA_T04" not in serialized
    assert "SECRET_COOKIE_T04" not in serialized


def test_actual_search_links_preserve_same_note_query_without_fabricated_source():
    href = "/search_result/synthetic-note?xsec_source=pc_search&xsec_token=SECRET_XSEC_T04&extra=1"
    payload = execute(SEARCH_SCRIPT, [{
        "initialState": {"search": {"feeds": [synthetic_feed()]}},
        "links": [
            href,
            "https://foreign.invalid/explore/synthetic-note?xsec_token=SECRET_FOREIGN",
            "/user/profile/synthetic-note?xsec_token=SECRET_WRONG_PATH",
        ],
    }])[0]
    assert payload["links"] == [{
        "note_id": "synthetic-note", "href": "https://www.xiaohongshu.com" + href
    }]
    candidate = parse_search(payload, "synthetic-session").candidates[0]
    assert candidate.href.get_secret_value() == "https://www.xiaohongshu.com" + href
    assert candidate.locator.xsec_token.get_secret_value() == "SECRET_XSEC_T04"


@pytest.mark.parametrize("script,kind", [(SEARCH_SCRIPT, "search"), (DETAIL_SCRIPT, "detail")])
def test_scripts_refuse_foreign_origin_before_reading_state_or_dom(script, kind):
    result = execute(script, [{
        "origin": "https://foreign.invalid", "forbidDocumentRead": True,
        "initialState": {"search": {"feeds": [synthetic_feed()]}}
    }], kind=kind)
    assert result == [{"invalid_page": True}]


def test_search_refuses_wrong_official_route():
    assert execute(SEARCH_SCRIPT, [{"path": "/explore", "forbidDocumentRead": True}]) == [
        {"invalid_page": True}
    ]


@pytest.mark.parametrize("search", ["?keyword=wrong", "", "?other=1"])
def test_search_refuses_mismatched_query_before_reading_page(search):
    assert execute(SEARCH_SCRIPT, [{"search": search, "forbidDocumentRead": True}]) == [
        {"invalid_page": True}
    ]


@pytest.mark.parametrize("path", ["/explore/wrong-note", "/user/profile/synthetic-note", "/explore"])
def test_detail_atomically_refuses_route_for_another_note(path):
    assert execute(DETAIL_SCRIPT, [{
        "path": path, "noteId": "synthetic-note", "forbidDocumentRead": True
    }], kind="detail") == [{"invalid_page": True}]


def test_actual_script_distinguishes_missing_state_and_valid_empty_array():
    missing, empty = execute(SEARCH_SCRIPT, [
        {}, {"initialState": {"search": {"feeds": []}}}
    ])
    assert missing == {"state_available": False, "links": []}
    with pytest.raises(LiveParseError):
        parse_search(missing, "synthetic-session")
    assert empty["state_available"] is True and empty["feeds"] == []
    assert parse_search(empty, "synthetic-session").candidates == ()


def test_initial_search_capture_is_bounded_without_loading_more():
    payload = execute(SEARCH_SCRIPT, [{
        "initialState": {"search": {"feeds": [synthetic_feed()] * 81}},
        "links": [f"/explore/n{i}?xsec_token=SYNTHETIC" for i in range(161)],
    }])[0]
    assert payload["batch_capped"] is True
    assert len(payload["feeds"]) == 80 and len(payload["links"]) == 160
    assert payload["observed_raw_count"] == 81
    parsed = parse_search(payload, "synthetic-session")
    assert parsed.raw_count == 80 and parsed.observed_raw_count == 81
    assert parsed.safe_summary()["batch_capped"] is True


def test_actual_detail_reads_only_requested_note_and_leaves_images_unanalyzed():
    payload = execute(DETAIL_SCRIPT, [{
        "noteId": "synthetic-note", "domBody": "合成正文", "poison": True,
        "initialState": {"note": {"noteDetailMap": {"synthetic-note": {"note": {
            "noteId": "synthetic-note", "title": "合成标题", "desc": "合成正文",
            "type": "normal", "imageList": [{"width": 100, "height": 200}],
        }}}}},
    }], kind="detail")[0]
    assert payload["note"]["imageList"] == [{"width": 100, "height": 200}]
    assert payload["dom_body_found"] is True and payload["dom_body"] == "合成正文"
    assert payload["expandable"] is None and payload["truncated"] is None
    assert "comments" not in payload["note"] and "video" not in payload["note"]
    assert "xsecToken" not in payload["note"]
    parsed = parse_detail(payload, SourceIdentity(note_id="synthetic-note"))
    assert parsed.classification.completeness == "PARTIAL_TEXT"
    assert parsed.safe_summary()["image_analysis"] == "IMAGE_NOT_ANALYZED"
    assert parsed.http_status is None


@pytest.mark.parametrize("wrapper", ["value", "_value"])
def test_actual_detail_supports_vue_wrapped_map_entry_and_note(wrapper):
    payload = execute(DETAIL_SCRIPT, [{
        "noteId": "synthetic-note",
        "initialState": {"note": {"noteDetailMap": {wrapper: {
            "synthetic-note": {wrapper: {"note": {wrapper: {
                "noteId": "synthetic-note", "desc": "合成正文"
            }}}}
        }}}},
    }], kind="detail")[0]
    assert payload["state_available"] is True
    assert payload["dom_body_found"] is False and payload["dom_body"] is None
    assert payload["note"]["desc"] == "合成正文"


def test_detail_does_not_fall_back_to_another_notes_body():
    payload = execute(DETAIL_SCRIPT, [{
        "noteId": "synthetic-note", "initialState": {"note": {"noteDetailMap": {
            "different-note": {"note": {"noteId": "different-note", "desc": "错误正文"}}
        }}},
    }], kind="detail")[0]
    assert payload == {"state_available": False}


def clean_observation(**changes):
    fields = dict(
        current_url_classification="OFFICIAL_PAGE", page_ready=True,
        login_dialog_present=False, login_button_present=False,
        verification_present=False, access_restriction_present=False,
    )
    fields.update(changes)
    return LoginObservation("AUTHENTICATED", evidence=LoginEvidence(**fields))


class FakePage:
    def __init__(self, *, status=200, goto_error=None, payload=None, redirect=None):
        self.url = "https://www.xiaohongshu.com/explore"
        self.status = status
        self.goto_error = goto_error
        self.redirect = redirect
        self.payload = payload if payload is not None else {"state_available": True, "feeds": []}
        self.goto_calls = []
        self.evaluate_calls = []
        self.wait_calls = []

    def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error:
            raise self.goto_error
        self.url = self.redirect or url
        return SimpleNamespace(status=self.status) if self.status is not None else None

    def evaluate(self, script, *args):
        self.evaluate_calls.append((script, args))
        return dict(self.payload)

    def wait_for_timeout(self, milliseconds):
        self.wait_calls.append(milliseconds)


class FakeResource:
    def __init__(self, page, observations):
        self._page = page
        self._lock = RLock()
        self._closed = False
        self._revoked = False
        self.observations = list(observations)

    def _observe(self):
        if len(self.observations) > 1:
            return self.observations.pop(0)
        return self.observations[0]

    def _run(self, operation):
        return operation()


class FakeObserver:
    def __init__(self):
        self.windows = []
        self.finishes = 0
        self.stop_code = None

    def start_window(self, window):
        self.windows.append(window)

    def finish_window(self):
        self.finishes += 1


def fake_backend(page=None, observations=None):
    page = page if page is not None else FakePage()
    resource = FakeResource(page, observations or [clean_observation()])
    backend = object.__new__(LiveBrowserBackend)
    backend.resource = resource
    backend.observer = FakeObserver()
    backend.goto_attempts = 0
    return backend, BrowserSession(resource), page


def test_search_navigates_once_and_extracts_locally_without_additional_navigation():
    backend, session, page = fake_backend()
    payload = backend.search(session, "成都 川西 国庆 攻略")
    assert payload["http_status"] == 200
    assert backend.goto_attempts == 1 and len(page.goto_calls) == 1
    assert len(page.evaluate_calls) == 2
    assert all(script == SEARCH_SCRIPT for script, _ in page.evaluate_calls)
    assert backend.observer.windows == ["SEARCH"] and backend.observer.finishes == 1
    assert page.goto_calls[0][1] == {"wait_until": "domcontentloaded", "timeout": 9000}


def test_detail_navigates_observed_href_once_and_passes_only_expected_id_to_script():
    backend, session, page = fake_backend(page=FakePage(payload={"state_available": True}))
    href = "https://www.xiaohongshu.com/explore/synthetic-note?xsec_token=SECRET_XSEC_T04"
    backend.detail(session, href=href, note_id="synthetic-note", detail_number=1)
    assert backend.goto_attempts == 1 and page.goto_calls[0][0] == href
    assert len(page.goto_calls) == 1
    assert page.evaluate_calls == [(DETAIL_SCRIPT, ("synthetic-note",))] * 2
    assert backend.observer.windows == ["DETAIL_1"] and backend.observer.finishes == 1


@pytest.mark.parametrize("start_path,final_path", [
    ("/search_result/synthetic-note", "/explore/synthetic-note"),
    ("/explore/synthetic-note", "/search_result/synthetic-note"),
    ("/explore/synthetic-note", "/explore/synthetic-note/"),
])
def test_same_note_official_route_canonicalization_does_not_repeat_navigation(start_path, final_path):
    page = FakePage(payload={"state_available": True},
                    redirect="https://www.xiaohongshu.com" + final_path)
    backend, session, _ = fake_backend(page=page)
    backend.detail(session, href="https://www.xiaohongshu.com" + start_path,
                   note_id="synthetic-note", detail_number=1)
    assert len(page.goto_calls) == 1
    assert len(page.evaluate_calls) == 2
    assert backend.last_read_diagnostic is None


@pytest.mark.parametrize("path", [
    "/explore/different-id", "/search_result/different-id", "/user/profile/synthetic-note",
    "/explore/synthetic-note/extra", "/search_result", "/explore",
])
def test_other_note_or_route_remains_rejected_with_safe_diagnostic(path):
    page = FakePage(payload={"state_available": True},
                    redirect="https://www.xiaohongshu.com" + path)
    backend, session, _ = fake_backend(page=page)
    with pytest.raises(LiveReadStopped, match="UNEXPECTED_PAGE"):
        backend.detail(session, href="https://www.xiaohongshu.com/explore/synthetic-note",
                       note_id="synthetic-note", detail_number=1)
    assert len(page.goto_calls) == 1 and not page.evaluate_calls
    assert backend.last_read_diagnostic == "ROUTE_MISMATCH"


@pytest.mark.parametrize("observation,code", [
    (LoginObservation("VERIFICATION_REQUIRED", evidence=clean_observation(
        verification_present=True).evidence), "VERIFICATION_REQUIRED"),
    (LoginObservation("LOGIN_REQUIRED", evidence=clean_observation(
        login_dialog_present=True).evidence), "NEED_LOGIN"),
    (clean_observation(access_restriction_present=True), "ACCESS_RESTRICTED"),
    (clean_observation(current_url_classification="FOREIGN_ORIGIN"), "UNEXPECTED_PAGE"),
    (LoginObservation("UNKNOWN"), "UNEXPECTED_PAGE"),
])
def test_pre_navigation_guard_stops_before_any_new_navigation(observation, code):
    backend, session, page = fake_backend(observations=[observation])
    with pytest.raises(LiveReadStopped) as error:
        backend.search(session, "合成关键词")
    assert error.value.code == code
    assert not page.goto_calls and not page.evaluate_calls
    assert backend.goto_attempts == 0 and backend.observer.windows == []


@pytest.mark.parametrize("status,code", [
    (401, "ACCESS_RESTRICTED"), (403, "ACCESS_RESTRICTED"),
    (429, "RATE_LIMITED"), (500, "BROWSER_ERROR"),
])
def test_http_access_errors_stop_without_retry_or_extraction(status, code):
    backend, session, page = fake_backend(page=FakePage(status=status))
    with pytest.raises(LiveReadStopped) as error:
        backend.search(session, "合成关键词")
    assert error.value.code == code
    assert backend.goto_attempts == 1 and len(page.goto_calls) == 1
    assert not page.evaluate_calls and backend.observer.finishes == 1


def test_challenge_after_navigation_prevents_content_extraction():
    challenge = LoginObservation("VERIFICATION_REQUIRED", evidence=clean_observation(
        verification_present=True).evidence)
    backend, session, page = fake_backend(observations=[clean_observation(), challenge])
    with pytest.raises(LiveReadStopped, match="^VERIFICATION_REQUIRED$"):
        backend.search(session, "合成关键词")
    assert len(page.goto_calls) == 1 and not page.evaluate_calls
    assert backend.observer.finishes == 1


def test_navigation_error_never_exposes_original_credential_url(capsys):
    secret = "https://www.xiaohongshu.com/explore/synthetic?xsec_token=SECRET_XSEC_T04"
    backend, session, page = fake_backend(page=FakePage(goto_error=RuntimeError(secret)))
    with pytest.raises(LiveReadStopped) as error:
        backend.detail(session, href=secret, note_id="synthetic", detail_number=1)
    assert str(error.value) == "BROWSER_ERROR"
    assert error.value.__context__ is None
    captured = capsys.readouterr()
    assert "SECRET_XSEC_T04" not in repr(error.value) + captured.out + captured.err
    assert len(page.goto_calls) == 1 and backend.observer.finishes == 1


def test_redirect_to_wrong_route_fails_closed_without_reading_payload():
    backend, session, page = fake_backend(page=FakePage(
        redirect="https://www.xiaohongshu.com/unexpected"
    ))
    with pytest.raises(LiveReadStopped, match="^UNEXPECTED_PAGE$"):
        backend.search(session, "合成关键词")
    assert len(page.goto_calls) == 1 and not page.evaluate_calls


def test_missing_state_timeout_does_not_navigate_again(monkeypatch):
    ticks = iter(range(0, 100, 5))
    monkeypatch.setattr("xhs_sidecar.live_page.monotonic", lambda: next(ticks))
    backend, session, page = fake_backend(page=FakePage(payload={"state_available": False}))
    with pytest.raises(LiveReadStopped, match="^PARSE_ERROR$"):
        backend.search(session, "合成关键词")
    assert len(page.goto_calls) == 1 and len(page.evaluate_calls) == 2
    assert backend.observer.finishes == 1


def test_stale_resource_cannot_navigate():
    backend, session, page = fake_backend()
    backend.resource = FakeResource(FakePage(), [clean_observation()])
    with pytest.raises(LiveReadStopped, match="^STALE_SESSION$"):
        backend.search(session, "合成关键词")
    assert not page.goto_calls


@pytest.mark.parametrize("code", ["RATE_LIMITED", "ACCESS_RESTRICTED", "NEED_LOGIN"])
def test_observed_network_stop_code_wins_before_navigation(code):
    backend, session, page = fake_backend()
    backend.observer.stop_code = code
    with pytest.raises(LiveReadStopped) as error:
        backend.search(session, "合成关键词")
    assert error.value.code == code
    assert not page.goto_calls and not page.evaluate_calls
    assert backend.observer.windows == []


def test_resource_revoked_under_operation_lock_cannot_navigate():
    backend, session, page = fake_backend()
    backend.resource._revoked = True
    with pytest.raises(LiveReadStopped, match="^STALE_SESSION$"):
        backend.search(session, "合成关键词")
    assert not page.goto_calls
