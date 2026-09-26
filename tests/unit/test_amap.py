"""Synthetic fixtures only. No map service traffic."""

import pytest
import json
from urllib.error import HTTPError, URLError
from pydantic import SecretStr

from travel_agent.providers.amap import AmapAdapter, coordinate, route_parameters
from travel_agent.planning.models import TripInputs
from travel_agent.planning.time_check import check_time


def fake_http(monkeypatch, response=None, failure=None):
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return json.dumps(response).encode()

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            if failure:
                raise failure
            return Response()

    monkeypatch.setattr("travel_agent.providers.amap.build_opener", lambda *a: Opener())
    return calls


@pytest.mark.parametrize(
    "mode,key", [("TRANSIT", "transits"), ("DRIVING", "paths"), ("WALKING", "paths")]
)
def test_v5_totals_do_not_add_steps_wait_or_taxi(monkeypatch, mode, key):
    calls = fake_http(
        monkeypatch,
        {
            "status": "1",
            "infocode": "10000",
            "count": "1",
            "route": {
                key: [
                    {
                        "distance": "2500",
                        "cost": {"duration": "1200"},
                        "steps": [{"cost": {"duration": "1200"}}],
                        "segments": [{"walking": {"duration": "300"}, "taxi": {"drivetime": "99"}}],
                    }
                ]
            },
        },
    )
    p = {"location": "121,31", "citycode": "021"}
    out = AmapAdapter(SecretStr("synthetic-key")).route(p, p, mode, None)
    assert len(calls) == 1 and out["duration_seconds"] == 1200 and out["distance_meters"] == 2500
    assert "show_fields=cost" in calls[0].full_url and "date=" not in calls[0].full_url
    assert out["includes_waiting"] == (mode == "TRANSIT")


@pytest.mark.parametrize("duration", ["", [], None, "NaN", "-1"])
def test_absent_invalid_duration_is_unknown(monkeypatch, duration):
    fake_http(
        monkeypatch,
        {
            "status": "1",
            "infocode": "10000",
            "count": "1",
            "route": {"paths": [{"distance": "3", "cost": {"duration": duration}}]},
        },
    )
    out = AmapAdapter(SecretStr("synthetic-key")).route(
        {"location": "121,31"}, {"location": "121,31"}, "WALKING", None
    )
    assert out["status"] == "PARTIAL" and out["duration_seconds"] is None


@pytest.mark.parametrize(
    "payload,failure,status",
    [
        (
            {"status": "0", "infocode": "10003", "info": "key=SECRET-sentinel"},
            None,
            "AUTH_OR_QUOTA_ERROR",
        ),
        ({"status": "0", "infocode": "20001"}, None, "UPSTREAM_ERROR"),
        (
            {"status": "1", "infocode": "10000", "count": "0", "route": {"transits": []}},
            None,
            "NO_ROUTE_RETURNED",
        ),
        (
            None,
            HTTPError("https://invalid/?key=SECRET-sentinel", 429, "raw PRIVATE-address", {}, None),
            "AUTH_OR_QUOTA_ERROR",
        ),
        (None, URLError("key=SECRET-sentinel PRIVATE-address"), "UPSTREAM_ERROR"),
    ],
)
def test_http_business_empty_network_errors_are_safe(monkeypatch, caplog, payload, failure, status):
    calls = fake_http(monkeypatch, payload, failure)
    p = {"location": "121,31", "citycode": "021"}
    out = AmapAdapter(SecretStr("SECRET-sentinel")).route(p, p, "TRANSIT", None)
    assert out["status"] == status and len(calls) == 1
    assert "SECRET-sentinel" not in json.dumps(out) + caplog.text
    assert "PRIVATE-address" not in json.dumps(out) + caplog.text


def test_place_small_page_no_sensitive_business_fields(monkeypatch):
    calls = fake_http(
        monkeypatch,
        {
            "status": "1",
            "infocode": "10000",
            "count": "2",
            "pois": [
                {
                    "name": "合成园区",
                    "location": "121,31",
                    "citycode": "021",
                    "adcode": "310000",
                    "business": {"tel": "secret"},
                },
                {"name": "合成园区入口", "location": "121.01,31.01"},
            ],
        },
    )
    out = AmapAdapter(SecretStr("synthetic-key")).resolve_place("合成园区", "合成市")
    assert len(out["candidates"]) == 2
    assert "page_size=3" in calls[0].full_url and "page_num=1" in calls[0].full_url
    assert "show_fields" not in calls[0].full_url
    assert "business" not in str(out) and out["candidates"][0]["citycode"] == "021"


def test_transport_disallows_ambient_proxy_and_redirect(monkeypatch):
    from travel_agent.providers.llm import _NoRedirect

    assert _NoRedirect().redirect_request(None, None, 302, "", {}, "https://invalid/") is None
    seen = []

    def build(*handlers):
        seen.extend(handlers)
        raise AssertionError("transport sentinel before network")

    monkeypatch.setattr("travel_agent.providers.amap.build_opener", build)
    with pytest.raises(AssertionError):
        AmapAdapter(SecretStr("synthetic-key")).resolve_place("合成地点", "")
    assert any(getattr(h, "proxies", None) == {} for h in seen)
    assert any(isinstance(h, _NoRedirect) for h in seen)


def test_lnglat_citycode_and_explicit_transit_time():
    with pytest.raises(ValueError):
        coordinate("31,121")
    start = {"location": "121,31", "citycode": "021", "adcode": "310000"}
    end = {"location": "121.1,31.1", "citycode": "021", "adcode": "310000"}
    params = route_parameters(start, end, "TRANSIT", "2026-10-01T22:30:00+08:00")
    assert params["city1"] == "021" and params["time"] == "22-30"
    assert params["date"] == "2026-10-01" and params["show_fields"] == "cost"
    with pytest.raises(ValueError):
        route_parameters(start | {"citycode": "310000"}, end, "TRANSIT", None)


def test_no_key_does_not_dispatch():
    adapter = AmapAdapter.from_env({})
    assert not adapter.configured
    assert adapter.resolve_place("合成公共车站", "")["status"] == "NOT_CONFIGURED"


def test_five_days_and_day_ordinal_are_not_elapsed_time():
    result = check_time(TripInputs(), [], checked_scope="LOCAL_DAY_SEGMENT")
    assert result["scenario"] == "UNKNOWN"
    assert result["completeness"] == "PARTIAL"
    assert result["available_minutes"] is None
    assert result["executable"] == "UNVERIFIED"


def test_overnight_window_unknown_stay_does_not_become_zero():
    inputs = TripInputs(
        depart_at="2026-10-01T23:00:00+08:00", return_by="2026-10-02T02:00:00+08:00"
    )
    legs = [{"leg_id": "s0-s1", "duration_seconds": 3600, "status": "OK"}]
    result = check_time(inputs, legs, checked_scope="LOCAL_DAY_SEGMENT")
    assert result["known_movement_minutes"] == 60
    assert result["scenario"] == "UNKNOWN"
    assert "STAY_UNKNOWN" in result["missing_inputs"]


def test_explicit_assumptions_window_and_exceed_not_reality_proof():
    inputs = TripInputs(
        depart_at="2026-10-01T23:00",
        return_by="2026-10-02T02:00",
        origin="合成站",
        destination="合成站",
        activity_start="22:00",
        activity_end="03:00",
        stay_minutes=60,
        rest_minutes=10,
        buffer_minutes=10,
        transfer_minutes=10,
    )
    assert inputs.depart_at.endswith("+08:00")
    legs = [{"leg_id": "a--b", "duration_seconds": 3600, "status": "OK"}]
    out = check_time(inputs, legs, checked_scope="WHOLE_SELECTED_OBJECT")
    assert out["available_minutes"] == 180 and out["known_components_minutes"] == 150
    assert out["scenario"] == "FITS_UNDER_STATED_ASSUMPTIONS" and out["executable"] == "UNVERIFIED"
    inputs.stay_minutes = 600
    out = check_time(inputs, legs, checked_scope="WHOLE_SELECTED_OBJECT")
    assert out["scenario"] == "EXCEEDS_UNDER_STATED_ASSUMPTIONS"
    assert out["assumptions"] and "非全程可靠下界" in out["meaning"]
