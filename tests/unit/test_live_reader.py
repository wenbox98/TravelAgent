"""T04 permits and revocation tests; fixtures are synthetic and network-denied."""

from types import SimpleNamespace

import pytest

from xhs_sidecar.browser import BrowserManager
from xhs_sidecar.live_page import LiveReadStopped
from xhs_sidecar.live_reader import LiveSmokeReader
from xhs_sidecar.models import LoginState, SearchFilters, SearchRequest
from xhs_sidecar.redaction import SafeAuditLog


def candidate(i):
    return {"id": f"synthetic-{i}", "modelType": "note", "noteCard": {
        "displayTitle": f"合成川西国庆路线攻略{i}", "type": "normal",
    }}


class PageReader:
    def __init__(self):
        self.search_calls = 0
        self.detail_calls = 0
        self.after = lambda: None
        self.failure = None

    def search(self, session, keyword):
        self.search_calls += 1
        self.after()
        if self.failure:
            raise self.failure
        return {"feeds": [candidate(i) for i in range(3)], "links": [
            {"note_id": f"synthetic-{i}", "href":
             f"https://www.xiaohongshu.com/explore/synthetic-{i}?xsec_token=SECRET_XSEC_T04&xsec_source=pc_search"}
            for i in range(3)
        ]}

    def detail(self, session, *, href, note_id, detail_number):
        self.detail_calls += 1
        self.after()
        if self.failure:
            raise self.failure
        return {"note": {"noteId": note_id, "desc": "合成正文", "imageList": [{}]},
                "http_status": 200}


@pytest.fixture
def rig():
    manager = BrowserManager()
    manager.start()
    life = SimpleNamespace(
        current=LoginState(mode="login", status="AUTHENTICATED", generation=1),
        audit=SafeAuditLog(),
    )
    life.status = lambda: life.current
    page = PageReader()
    return LiveSmokeReader(manager, life, page), manager, life, page


def test_t04_14_second_search_is_rejected_without_dispatch(rig):
    reader, _, _, page = rig
    reader.search(SearchRequest(keyword="合成川西"))
    with pytest.raises(LiveReadStopped, match="BUDGET_EXHAUSTED"):
        reader.search(SearchRequest(keyword="不能自动fallback"))
    assert reader.search_operations == page.search_calls == 1


def test_t041_detail_budget_is_one_even_with_two_selected_candidates(rig):
    _, manager, life, page = rig
    reader = LiveSmokeReader(manager, life, page, max_feed_details=1)
    reader.search(SearchRequest(keyword="合成川西"))
    reader.detail(0)
    with pytest.raises(LiveReadStopped, match="BUDGET_EXHAUSTED"):
        reader.detail(1)
    assert reader.safe_summary()["max_feed_details"] == 1
    assert reader.detail_operations == page.detail_calls == 1


def test_t04_15_third_detail_is_rejected_without_dispatch(rig):
    reader, _, _, page = rig
    reader.search(SearchRequest(keyword="合成川西"))
    reader.detail(0)
    reader.detail(1)
    with pytest.raises(LiveReadStopped, match="BUDGET_EXHAUSTED"):
        reader.detail(2)
    assert reader.detail_operations == page.detail_calls == 2


def test_t04_10_duplicate_detail_returns_same_memory_result(rig):
    reader, _, _, page = rig
    reader.search(SearchRequest(keyword="合成川西"))
    first = reader.detail(0)
    assert reader.detail(0) is first
    assert reader.detail_operations == page.detail_calls == 1
    assert reader.duplicate_details_avoided == 1


def test_failed_detail_also_consumes_budget_and_cannot_repeat(rig):
    reader, _, _, page = rig
    reader.search(SearchRequest(keyword="合成川西"))
    page.failure = RuntimeError("SECRET_XSEC_T04")
    with pytest.raises(LiveReadStopped, match="BROWSER_ERROR"):
        reader.detail(0)
    with pytest.raises(LiveReadStopped, match="DUPLICATE_SOURCE"):
        reader.detail(0)
    assert reader.detail_operations == page.detail_calls == 1


def test_failed_search_consumes_permit_and_stops(rig):
    reader, _, _, page = rig
    page.failure = RuntimeError("https://example.invalid?token=SECRET_XSEC_T04")
    with pytest.raises(LiveReadStopped) as caught:
        reader.search(SearchRequest(keyword="合成"))
    assert "SECRET" not in str(caught.value)
    assert reader.search_operations == 1
    with pytest.raises(LiveReadStopped):
        reader.search(SearchRequest(keyword="retry"))
    assert page.search_calls == 1


def test_t04_06_unimplemented_filters_never_report_applied(rig):
    reader, _, _, page = rig
    with pytest.raises(LiveReadStopped, match="FILTERS_UNSUPPORTED"):
        reader.search(SearchRequest(keyword="合成", filters=SearchFilters(note_type="图文")))
    assert page.search_calls == reader.search_operations == 0
    assert reader.safe_summary()["filter_status"] == "NOT_REQUESTED"


@pytest.mark.parametrize("state", ["DISCONNECTED", "WAITING_USER", "VERIFICATION_REQUIRED", "ERROR"])
def test_unauthenticated_never_starts_or_reads(rig, state):
    reader, manager, life, page = rig
    life.current = life.current.model_copy(update={"status": state})
    manager.close()
    with pytest.raises(LiveReadStopped, match="NEED_LOGIN"):
        reader.search(SearchRequest(keyword="合成"))
    assert manager._session is None
    assert reader.search_operations == page.search_calls == 0


def test_late_search_cannot_commit_after_generation_changes(rig):
    reader, _, life, page = rig
    page.after = lambda: setattr(life, "current", life.current.model_copy(update={"generation": 2}))
    with pytest.raises(LiveReadStopped, match="STALE_SESSION"):
        reader.search(SearchRequest(keyword="合成"))
    assert reader.search_result is None
    assert reader.search_operations == 1


def test_checkpoint_revocation_is_checked_before_external_dispatch(rig):
    reader, _, life, page = rig
    reader._checkpoint = lambda: setattr(life, "current", life.current.model_copy(update={"generation": 2}))
    with pytest.raises(LiveReadStopped, match="STALE_SESSION"):
        reader.search(SearchRequest(keyword="合成"))
    assert page.search_calls == 0
    assert reader.search_operations == 1  # Conservative reservation never silently resets.


def test_late_detail_cannot_commit_after_disconnect(rig):
    reader, manager, life, page = rig
    reader.search(SearchRequest(keyword="合成"))
    def revoke():
        life.current = life.current.model_copy(update={"generation": 2, "status": "DISCONNECTED"})
        manager.close()
    page.after = revoke
    with pytest.raises(LiveReadStopped):
        reader.detail(0)
    assert not reader.details
    assert reader.detail_operations == 1


def test_same_generation_new_browser_cannot_reuse_handles(rig):
    reader, manager, _, page = rig
    reader.search(SearchRequest(keyword="合成"))
    manager.close()
    manager.start()
    with pytest.raises(LiveReadStopped, match="STALE_SESSION"):
        reader.detail(0)
    assert page.detail_calls == 0


def test_network_requests_and_operations_are_not_aliased_and_summary_is_safe(rig):
    reader, _, _, _ = rig
    reader.search(SearchRequest(keyword="合成"))
    detail = reader.detail(0)
    summary = reader.safe_summary()
    assert summary["is_synthetic"] is False and summary["mode"] == "live_smoke"
    assert summary["search_operations"] == 1 and summary["detail_operations"] == 1
    assert "total_requests" not in summary
    assert "SECRET" not in repr(summary) and "合成正文" not in repr(summary)
    assert detail.classification.completeness == "PARTIAL_TEXT"
    assert detail.safe_summary()["evidence_generated"] is False
    assert detail.safe_summary()["image_analysis"] == "IMAGE_NOT_ANALYZED"


@pytest.mark.parametrize("code", ["VERIFICATION_REQUIRED", "RATE_LIMITED", "ACCESS_RESTRICTED"])
def test_restriction_stops_all_subsequent_reads(rig, code):
    reader, _, _, page = rig
    reader.search(SearchRequest(keyword="合成"))
    page.failure = LiveReadStopped(code)
    with pytest.raises(LiveReadStopped, match=code):
        reader.detail(0)
    with pytest.raises(LiveReadStopped, match=code):
        reader.detail(1)
    assert page.detail_calls == 1
