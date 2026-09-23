"""Synthetic T04 page shapes; no browser or network access."""

import json
from typing import Any
from urllib.parse import urlsplit

import pytest

from xhs_sidecar.live_parsing import LiveParseError, parse_detail, parse_search
from xhs_sidecar.models import SourceIdentity

NOTE_ID = "synthetic-note-a"
TOKEN = "SECRET_XSEC_T04"
SESSION = "SECRET_SESSION_T04"
TITLE = "合成川西路线标题"
AUTHOR = "合成作者显示名称"
BODY = "合成路线正文，不能进入报告。"


def feed(note_id: str = NOTE_ID, **card_fields: object) -> dict[str, Any]:
    return {
        "id": note_id,
        "modelType": "note",
        "xsecToken": "STALE_SYNTHETIC_TOKEN",
        "noteCard": {
            "displayTitle": TITLE,
            "type": "normal",
            "user": {"nickname": AUTHOR, "userId": "SECRET_ACCOUNT_T04"},
            "cover": {"urlDefault": "https://synthetic.invalid/cover"},
            "interactInfo": {"likedCount": "12", "commentCount": "0"},
            **card_fields,
        },
    }


def link(note_id: str = NOTE_ID, href: str | None = None) -> dict[str, str]:
    return {
        "note_id": note_id,
        "href": href or f"/search_result/{note_id}?xsec_token={TOKEN}&xsec_source=pc_search",
    }


def detail(**payload_fields: object) -> dict[str, object]:
    return {
        "note": {
            "noteId": NOTE_ID,
            "title": TITLE,
            "desc": BODY,
            "type": "normal",
            "imageList": [{"urlDefault": "https://synthetic.invalid/image"}],
            "xsecToken": TOKEN,
            "comments": {"text": "SECRET_COMMENT_T04"},
            "video": {"masterUrl": "SECRET_VIDEO_T04"},
        },
        "http_status": 200,
        "dom_body": BODY,
        "dom_body_found": True,
        "expandable": None,
        "truncated": None,
        **payload_fields,
    }


def test_t04_01_02_stable_source_and_private_observed_locator() -> None:
    candidate = parse_search({"feeds": [feed()], "links": [link()]}, SESSION).candidates[0]
    assert candidate.source.source_id == f"xhs:{NOTE_ID}"
    assert candidate.source.model_dump() == {
        "provider": "xhs", "note_id": NOTE_ID, "source_id": f"xhs:{NOTE_ID}"
    }
    assert candidate.locator is not None and candidate.href is not None
    assert candidate.locator.xsec_token.get_secret_value() == TOKEN
    assert candidate.locator.session_id == SESSION
    assert candidate.locator.ttl_status == "UNKNOWN"
    assert candidate.href.get_secret_value() == (
        f"https://www.xiaohongshu.com/search_result/{NOTE_ID}"
        f"?xsec_token={TOKEN}&xsec_source=pc_search"
    )
    assert "pc_feed" not in candidate.href.get_secret_value()
    assert candidate.safe_summary()["detail_access_available"] is True


def test_t04_03_duplicate_note_identity_not_token_is_dedup_key() -> None:
    duplicate = feed()
    duplicate["xsecToken"] = "ROTATED_SYNTHETIC_TOKEN"
    result = parse_search({"feeds": [feed(), duplicate, feed("synthetic-note-b")]}, SESSION)
    assert len(result.candidates) == 2
    assert result.raw_count == 3 and result.duplicate_count == 1 and result.dropped_count == 0


def test_t04_04_05_missing_publish_time_and_summary_stay_unknown() -> None:
    candidate = parse_search({"feeds": [feed()]}, SESSION).candidates[0]
    assert candidate.title == TITLE
    assert candidate.published_at is None and candidate.summary is None
    for field in ("publish_time", "summary", "destination", "location", "travel_time"):
        assert candidate.field_status[field] == "NOT_AVAILABLE"


@pytest.mark.parametrize("publication_key", ["time", "publishTime", "publishedAt"])
def test_explicit_card_aliases_are_observed_with_exact_fixed_field_sources(publication_key):
    value = feed(displayTitle=None, title=TITLE, snippet="合成摘要", **{
        publication_key: "2026-09-23"
    })
    candidate = parse_search({"feeds": [value]}, SESSION).candidates[0]
    assert candidate.title == TITLE
    assert candidate.published_at == "2026-09-23" and candidate.summary == "合成摘要"
    assert candidate.field_status["publish_time"] == "OBSERVED"
    assert candidate.field_sources["title"] == "noteCard.title"
    assert candidate.field_sources["summary"] == "noteCard.snippet"
    assert candidate.field_sources["publish_time"] == "noteCard." + publication_key
    assert candidate.field_status["travel_time"] == "NOT_AVAILABLE"
    summary = json.dumps(candidate.safe_summary(), ensure_ascii=False)
    assert TITLE not in summary and "合成摘要" not in summary and "2026-09-23" not in summary


def test_alias_priority_and_missing_values_are_not_guessed():
    candidate = parse_search({"feeds": [feed(
        title="低优先级标题", time=None, publishTime=False, publishedAt=123456789,
        summary=" ", snippet="观测摘要",
    )]}, SESSION).candidates[0]
    assert candidate.title == TITLE and candidate.field_sources["title"] == "noteCard.displayTitle"
    assert candidate.field_sources["publish_time"] == "noteCard.publishedAt"
    assert candidate.field_sources["summary"] == "noteCard.snippet"
    assert "destination" not in candidate.field_sources


def test_search_reports_original_array_count_separately_from_capped_extraction():
    result = parse_search({
        "feeds": [feed()], "observed_raw_count": 81, "batch_capped": True
    }, SESSION)
    assert result.raw_count == 1 and result.observed_raw_count == 81 and result.batch_capped is True
    assert result.safe_summary()["observed_raw_count"] == 81
    assert result.safe_summary()["raw_count"] == 1
    unmeasured = parse_search({"feeds": []}, SESSION).safe_summary()
    assert unmeasured["observed_raw_count"] is None and unmeasured["batch_capped"] is None


@pytest.mark.parametrize("metadata", [
    {"observed_raw_count": -1}, {"observed_raw_count": True},
    {"batch_capped": "false"}, {"observed_raw_count": 2, "batch_capped": False},
    {"observed_raw_count": 1, "batch_capped": True},
])
def test_inconsistent_extraction_cap_metadata_fails_closed(metadata):
    with pytest.raises(LiveParseError, match="^页面数据无法安全解析$"):
        parse_search({"feeds": [feed()], **metadata}, SESSION)


def test_publish_time_is_not_travel_time_and_ip_location_not_destination() -> None:
    candidate = parse_search({"feeds": [feed(time=1234567890000, ipLocation="合成城市")]}, SESSION)
    assert candidate.candidates[0].field_status["publish_time"] == "OBSERVED"
    assert candidate.candidates[0].field_status["travel_time"] == "NOT_AVAILABLE"
    assert candidate.candidates[0].field_status["destination"] == "NOT_AVAILABLE"
    result = parse_detail(detail(note={
        "noteId": NOTE_ID, "desc": BODY, "time": 1234567890000, "ipLocation": "合成城市"
    }), SourceIdentity(note_id=NOTE_ID))
    assert result.field_status["publish_time"] == "OBSERVED"
    assert result.field_status["ip_location"] == "OBSERVED"
    assert result.field_status["destination"] == "NOT_AVAILABLE"
    assert result.field_status["travel_time"] == "NOT_AVAILABLE"


@pytest.mark.parametrize("wrapper", ["value", "_value"])
def test_vue_wrapped_feed_list_and_card(wrapper: str) -> None:
    value = feed()
    value["noteCard"] = {wrapper: value["noteCard"]}
    result = parse_search({"feeds": {wrapper: [{wrapper: value}]}}, SESSION)
    assert result.candidates[0].title == TITLE


def test_non_notes_invalid_ids_and_empty_cards_are_dropped() -> None:
    live = feed()
    live["modelType"] = "live_v2"
    empty = feed()
    empty["noteCard"] = {}
    result = parse_search({"feeds": [
        live, {"modelType": "hot_query"}, empty, feed("../bad-id"), None, feed(type="video")
    ]}, SESSION)
    assert result.dropped_count == 5
    assert len(result.candidates) == 1 and result.candidates[0].note_type == "video"


@pytest.mark.parametrize("payload", [None, {}, {"feeds": None}, {"feeds": {}}, {"feeds": "secret"}])
def test_missing_search_state_is_safe_error_not_empty_result(payload: object) -> None:
    with pytest.raises(LiveParseError, match="^页面数据无法安全解析$"):
        parse_search(payload, SESSION)
    assert parse_search({"feeds": []}, SESSION).safe_summary()["candidate_count"] == 0


@pytest.mark.parametrize("href", [
    f"https://evil.invalid/explore/{NOTE_ID}?xsec_token={TOKEN}",
    f"https://www.xiaohongshu.com.evil.invalid/explore/{NOTE_ID}?xsec_token={TOKEN}",
    f"http://www.xiaohongshu.com/explore/{NOTE_ID}?xsec_token={TOKEN}",
    f"https://www.xiaohongshu.com:444/explore/{NOTE_ID}?xsec_token={TOKEN}",
    f"https://user@www.xiaohongshu.com/explore/{NOTE_ID}?xsec_token={TOKEN}",
    f"/explore/different-note?xsec_token={TOKEN}",
    f"/user/profile/{NOTE_ID}?xsec_token={TOKEN}",
    f"/explore/{NOTE_ID}?xsec_token=",
    f"/explore/{NOTE_ID}?xsec_token={TOKEN}&xsec_token=second",
    f"/explore/{NOTE_ID}?xsec_token={TOKEN}&xsec_source=one&xsec_source=two",
    f"/explore/{NOTE_ID}?xsec_token={TOKEN}\n",
    f"\\evil.invalid/explore/{NOTE_ID}?xsec_token={TOKEN}",
    f"//www.xiaohongshu.com/explore/{NOTE_ID}?xsec_token={TOKEN}",
    f"explore/{NOTE_ID}?xsec_token={TOKEN}",
    f"../explore/{NOTE_ID}?xsec_token={TOKEN}",
])
def test_invalid_or_ambiguous_href_cannot_create_detail_capability(href: str) -> None:
    candidate = parse_search({"feeds": [feed()], "links": [link(href=href)]}, SESSION).candidates[0]
    assert candidate.locator is None and candidate.href is None
    assert candidate.safe_summary()["detail_access_available"] is False


def test_feed_token_alone_is_not_an_invented_detail_url() -> None:
    candidate = parse_search({"feeds": [feed()]}, SESSION).candidates[0]
    assert candidate.xsec_token_available is True
    assert candidate.locator is None and candidate.href is None


def test_private_locator_does_not_populate_global_urlsplit_cache():
    before = urlsplit.cache_info()
    candidate = parse_search({"feeds": [feed()], "links": [link()]}, SESSION).candidates[0]
    assert candidate.locator is not None
    assert urlsplit.cache_info() == before


def test_valid_later_dom_link_is_used_and_missing_source_is_not_guessed() -> None:
    href = f"https://xiaohongshu.com/explore/{NOTE_ID}?xsec_token={TOKEN}"
    result = parse_search({"feeds": [feed()], "links": [
        link(href=f"/explore/{NOTE_ID}"), link(href=href)
    ]}, SESSION)
    candidate = result.candidates[0]
    assert candidate.href is not None and candidate.href.get_secret_value() == href


def test_t04_07_success_and_matching_dom_do_not_alone_prove_full_text() -> None:
    result = parse_detail(detail(), SourceIdentity(note_id=NOTE_ID))
    assert result.http_status == 200 and result.dom_body_matches is True
    assert result.raw.text_scope_verified is False
    assert result.classification.completeness == "PARTIAL_TEXT"


@pytest.mark.parametrize("flags", [
    {"truncated": True, "expandable": False},
    {"truncated": False, "expandable": True},
    {"truncated": False, "expandable": False, "dom_body": "正文片段"},
    {"truncated": False, "expandable": False, "dom_body_found": False},
    {"truncated": False, "expandable": False, "http_status": None},
    {"truncated": False, "expandable": False, "http_status": 403},
])
def test_t04_08_missing_scope_or_truncation_keeps_partial(flags: dict[str, object]) -> None:
    result = parse_detail(detail(**flags), SourceIdentity(note_id=NOTE_ID))
    assert result.classification.completeness == "PARTIAL_TEXT"


def test_full_text_requires_explicit_scope_and_actual_success_evidence() -> None:
    result = parse_detail(detail(expandable=False, truncated=False), SourceIdentity(note_id=NOTE_ID))
    assert result.classification.completeness == "FULL_TEXT"
    assert result.classification.reason == "verified_text_scope"


def test_unmeasured_http_status_does_not_inherit_raw_detail_default_200() -> None:
    payload = detail()
    del payload["http_status"]
    result = parse_detail(payload, SourceIdentity(note_id=NOTE_ID))
    assert result.http_status is None and result.raw.http_status == 0
    assert result.safe_summary()["http_status"] is None


def test_t04_09_images_not_analyzed_and_no_comment_video_or_evidence() -> None:
    result = parse_detail(detail(), SourceIdentity(note_id=NOTE_ID))
    safe = result.safe_summary()
    assert safe["image_analysis"] == "IMAGE_NOT_ANALYZED"
    assert safe["image_count"] == 1 and safe["evidence_generated"] is False
    assert not hasattr(result, "comments") and not hasattr(result, "video")
    assert not hasattr(result, "evidence")
    assert "SECRET_COMMENT_T04" not in repr(result)
    assert "SECRET_VIDEO_T04" not in json.dumps(safe)


@pytest.mark.parametrize("note,expected", [
    ({"noteId": NOTE_ID, "title": TITLE}, "METADATA_ONLY"),
    ({"noteId": NOTE_ID, "title": TITLE, "summary": "合成摘要"}, "SUMMARY_ONLY"),
    ({"noteId": NOTE_ID, "title": TITLE, "desc": "  "}, "METADATA_ONLY"),
])
def test_title_and_summary_never_upgrade_to_body(note: dict[str, str], expected: str) -> None:
    result = parse_detail(detail(note=note), SourceIdentity(note_id=NOTE_ID))
    assert result.classification.completeness == expected
    assert result.source_locator is None


def test_source_locator_is_body_version_bound_and_token_free() -> None:
    original = parse_detail(detail(), SourceIdentity(note_id=NOTE_ID))
    changed = parse_detail(detail(note={"noteId": NOTE_ID, "desc": BODY + "新版"}),
                           SourceIdentity(note_id=NOTE_ID))
    assert original.source_locator is not None
    assert original.source_locator.startswith("note-body:v1:")
    assert original.source_locator.endswith(f":chars:0-{len(BODY)}")
    assert original.source_locator != changed.source_locator
    assert TOKEN not in original.source_locator and NOTE_ID not in original.source_locator


def test_detail_wrong_source_has_only_fixed_safe_error() -> None:
    with pytest.raises(LiveParseError) as error:
        parse_detail(detail(note={"noteId": TOKEN}), SourceIdentity(note_id=NOTE_ID))
    assert str(error.value) == "页面数据无法安全解析"
    assert TOKEN not in repr(error.value)


def test_safe_reports_and_reprs_never_expose_private_content_or_locators() -> None:
    search = parse_search({"feeds": [feed()], "links": [link()]}, SESSION)
    parsed_detail = parse_detail(detail(), SourceIdentity(note_id=NOTE_ID))
    output = json.dumps([search.safe_summary(), parsed_detail.safe_summary()], ensure_ascii=False)
    output += repr(search) + repr(search.candidates[0]) + repr(search.candidates[0].locator)
    output += repr(parsed_detail) + repr(parsed_detail.raw)
    for secret in (TOKEN, SESSION, NOTE_ID, TITLE, AUTHOR, BODY, "SECRET_ACCOUNT_T04"):
        assert secret not in output
    assert "https://" not in output
    assert parsed_detail.safe_summary()["body_chars"] == len(BODY)
