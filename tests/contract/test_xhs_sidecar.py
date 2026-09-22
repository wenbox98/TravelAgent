import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from xhs_sidecar.app import SidecarConfig, create_app
from xhs_sidecar.backend import FakeXhsBackend
from xhs_sidecar.models import (
    AccessLocator,
    DetailRequest,
    NetworkSnapshot,
    SearchFilters,
    SearchRequest,
    SearchResult,
    SourceIdentity,
    RawDetail,
)
from xhs_sidecar.service import SidecarService, BackendContractError

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("status", ["FAILED", "UNKNOWN"])
def test_T02_07_failed_filters_do_not_claim_applied(status):
    service = SidecarService(backend=FakeXhsBackend(filter_status=status))
    result = service.search(SearchRequest(keyword="合成", filters=SearchFilters(sort_by="最新")))
    assert result.filter_status == status
    assert result.filter_requested.sort_by == "最新"
    assert result.filter_applied.specified() == {}
    with pytest.raises(ValidationError):
        SearchResult(
            candidates=[],
            filter_requested=SearchFilters(sort_by="最新"),
            filter_applied=SearchFilters(sort_by="最新"),
            filter_status=status,
            network=NetworkSnapshot(),
        )
    service.close()


def test_successful_and_absent_filters_are_explicit():
    service = SidecarService()
    assert service.search(SearchRequest(keyword="合成")).filter_status == "NOT_REQUESTED"
    result = service.search(SearchRequest(keyword="合成", filters=SearchFilters(note_type="图文")))
    assert result.filter_status == "APPLIED"
    assert result.filter_applied == result.filter_requested
    service.close()


def test_T02_09_identity_is_stable_and_locator_is_private():
    backend = FakeXhsBackend()
    service = SidecarService(backend=backend)
    first = service.search(SearchRequest(keyword="合成"))
    old_id = first.candidates[0].source.source_id
    sentinel = "SECRET_XSEC_TOKEN_SHOULD_NEVER_APPEAR"
    backend.token = SecretStr(sentinel)
    second = service.search(SearchRequest(keyword="合成"))
    assert second.candidates[0].source.source_id == old_id == "xhs:synthetic-note-1"
    assert first.candidates[0].note_handle == second.candidates[0].note_handle
    detail = service.detail(DetailRequest(note_handle=second.candidates[0].note_handle))
    assert sentinel not in second.model_dump_json() + detail.model_dump_json()
    locator = AccessLocator(second.candidates[0].source, "synthetic-session", backend.token)
    assert locator.ttl_status == "UNKNOWN"
    assert sentinel not in repr(locator)
    with pytest.raises(TypeError):
        json.dumps(locator)
    with pytest.raises(ValidationError):
        SourceIdentity(note_id="id", source_id="id+" + sentinel)
    service.close()


def test_sidecar_openapi_snapshot_matches_registered_contract():
    app = create_app(SidecarConfig(secret=SecretStr("SYNTHETIC_LOCAL_SECRET_" * 2)))
    checked_in = json.loads((ROOT / "contracts/xhs-sidecar.openapi.json").read_text("utf-8"))
    assert app.openapi() == checked_in
    assert "/mcp" not in checked_in["paths"]
    assert "AccessLocator" not in checked_in["components"]["schemas"]


def test_offline_http_reuses_session_and_revokes_handles():
    secret = "SYNTHETIC_LOCAL_SECRET_" * 2
    app = create_app(SidecarConfig(secret=SecretStr(secret)))
    with TestClient(
        app, base_url="http://127.0.0.1:18061", headers={"Authorization": "Bearer " + secret}
    ) as client:
        first = client.post("/v1/feeds/search", json={"keyword": "合成"}).json()
        handle = first["candidates"][0]["note_handle"]
        session = client.get("/v1/browser/session").json()["session_id"]
        detail = client.post("/v1/feeds/detail", json={"note_handle": handle})
        assert detail.status_code == 200
        assert detail.json()["completeness"] == "PARTIAL_TEXT"
        assert client.get("/v1/browser/session").json()["session_id"] == session
        assert client.delete("/v1/browser/session").status_code == 200
        assert client.post("/v1/feeds/detail", json={"note_handle": handle}).status_code == 404
        assert client.get("/v1/browser/session").json()["state"] == "CLOSED"


@pytest.mark.parametrize(
    "payload",
    [
        {"keyword": "合成", "filters": [{"sort_by": "最新"}]},
        {"keyword": "合成", "filters": {"location": "川西"}},
        {"keyword": "合成", "cursor": "unimplemented"},
        {"keyword": "   "},
    ],
)
def test_strict_search_rejects_unsupported_inputs_before_browser(payload):
    service = SidecarService()
    with pytest.raises(ValidationError):
        service.search(SearchRequest.model_validate(payload))
    assert service.browser_state().state == "CLOSED"


def test_unknown_network_cannot_be_fabricated_as_zero():
    with pytest.raises(ValidationError):
        NetworkSnapshot(total_requests=0)


@pytest.mark.parametrize("wrong_id,http_status", [(True, 200), (False, 500)])
def test_wrong_source_and_failed_http_are_not_successful_details(wrong_id, http_status):
    class InconsistentBackend(FakeXhsBackend):
        def detail(self, session, locator):
            return RawDetail(
                source=SourceIdentity(note_id="different") if wrong_id else locator.source,
                title="合成",
                body="合成正文",
                http_status=http_status,
            )

    service = SidecarService(backend=InconsistentBackend())
    handle = service.search(SearchRequest(keyword="合成")).candidates[0].note_handle
    with pytest.raises(BackendContractError):
        service.detail(DetailRequest(note_handle=handle))
    service.close()
