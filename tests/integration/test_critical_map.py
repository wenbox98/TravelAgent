# ruff: noqa: F811
"""Real service and grant lifecycle, with a fake Amap transport and synthetic sources."""

from uuid import uuid4
from pydantic import SecretStr
import pytest
from travel_agent.providers.amap import AmapAdapter
from travel_agent.planning.critical_map import CriticalMapAction, CONSENT, action
from travel_agent.planning.flow_maps import PrivateFlowMapService
from travel_agent.planning.flow_models import PlanDraft, PlanAction
from test_planning_conversation import conversation  # noqa: F401


class MapTransport(AmapAdapter):
    def __init__(self):
        super().__init__(SecretStr("authored-offline"))
        self.calls = []
        self.fail = False

    def resolve_place(self, name, region=""):
        self.calls.append(("PLACE", name, region))
        if self.fail:
            return dict(status="UPSTREAM_ERROR", candidates=[])
        return dict(
            status="OK",
            candidates=[
                dict(
                    name=name,
                    location="120.1,31.1",
                    type="风景名胜",
                    address="虚构公共位置",
                    pname="虚构省",
                    cityname=region,
                    adname="虚构区",
                    citycode="0512",
                    adcode="320500",
                    coordinate_system="GCJ02",
                )
            ],
        )

    def route(self, start, end, mode, at=None):
        self.calls.append(("ROUTE", mode, at))
        return dict(
            status="OK",
            duration_seconds=600.0,
            distance_meters=800.0,
            date_applicability="GENERAL_REFERENCE_ONLY",
        )


@pytest.fixture
def key_leg(conversation, monkeypatch):
    s, v, _, _ = conversation
    adapter = MapTransport()
    monkeypatch.setattr("travel_agent.providers.amap.AmapAdapter.from_env", lambda: adapter)
    draft = PlanDraft.model_validate(v["draft"])
    draft.transport = "WALKING"
    draft.walking_allowed = True
    draft.inputs.mode = "WALKING"
    for a in draft.activities:
        a.day = 1
    v = s.plans.mutate(
        v["session_id"],
        PlanAction(action="save", expected_revision=v["revision"], draft=draft),
        str(uuid4()),
    )
    maps = PrivateFlowMapService(s.db.path, "owner", "CACHED_PRIVATE_PREVIEW", adapter)
    assert v["critical_map"]["ready"], v["critical_map"]
    return s, v, maps, adapter


def send(s, maps, sid, kind, key=None, **fields):
    v = s.plans.get(sid)
    action(
        maps,
        sid,
        CriticalMapAction(action=kind, expected_revision=v["revision"], **fields),
        key or str(uuid4()),
    )
    return s.plans.get(sid)


def test_explicit_key_leg_resolve_confirm_route_and_restart_are_bounded(key_leg):
    s, v, maps, adapter = key_leg
    sid = v["session_id"]
    assert not adapter.calls
    pair = v["critical_map"]["pairs"][0]
    with pytest.raises(ValueError, match="OPERATION_NOT_AUTHORIZED"):
        send(s, maps, sid, "start", leg_id=pair["leg_id"])
    key = str(uuid4())
    before = v["operation"]["cumulative_used"]
    v = send(s, maps, sid, "start", key=key, leg_id=pair["leg_id"], consent=CONSENT)
    send(s, maps, sid, "start", key=key, leg_id=pair["leg_id"], consent=CONSENT)
    assert len(adapter.calls) == 2
    assert v["operation"]["cumulative_used"]["map_place"] == before["map_place"] + 2
    m = maps.get(sid)
    selected = [p for p in m["places"] if p["place_id"] in pair["place_ids"]]
    assert all(p["candidates"] and not p["confirmed"] for p in selected)
    with pytest.raises(ValueError, match="MAP_CONFIRM_PLACES_FIRST"):
        send(s, maps, sid, "route")
    for p in selected:
        v = send(
            s,
            maps,
            sid,
            "confirm",
            place_id=p["place_id"],
            candidate_id=p["candidates"][0]["candidate_id"],
            relation="SAME_OBJECT",
        )
    key = str(uuid4())
    v = send(s, maps, sid, "route", key=key)
    send(s, maps, sid, "route", key=key)
    assert len(adapter.calls) == 3 and adapter.calls[-1] == ("ROUTE", "WALKING", None)
    assert not v["adopted"]  # explicit narrow order confirmation is not guide adoption
    assert v["operation"]["cumulative_used"]["map_route"] == before["map_route"] + 1
    restored_maps = PrivateFlowMapService(s.db.path, "owner", "CACHED_PRIVATE_PREVIEW", adapter)
    assert restored_maps.get(sid)["map_result_state"] == "EXPIRED_OR_NOT_QUERIED"
    _, state = s.plans.load(sid)
    assert "120.1,31.1" not in str(state) and "虚构公共位置" not in str(state)
    assert len(adapter.calls) == 3


def test_failed_first_place_stops_and_receipt_never_retries(key_leg):
    s, v, maps, adapter = key_leg
    adapter.fail = True
    key = str(uuid4())
    pair = v["critical_map"]["pairs"][0]
    send(s, maps, v["session_id"], "start", key=key, leg_id=pair["leg_id"], consent=CONSENT)
    send(s, maps, v["session_id"], "start", key=key, leg_id=pair["leg_id"], consent=CONSENT)
    assert len(adapter.calls) == 1


def test_changed_order_invalidates_grant_and_does_not_call_map(key_leg):
    s, v, maps, adapter = key_leg
    sid = v["session_id"]
    v = send(s, maps, sid, "start", leg_id=v["critical_map"]["pairs"][0]["leg_id"], consent=CONSENT)
    draft = PlanDraft.model_validate(v["draft"])
    draft.activities.reverse()
    v = s.plans.mutate(
        sid, PlanAction(action="save", expected_revision=v["revision"], draft=draft), str(uuid4())
    )
    assert not v["critical_map"]["current"]
    with pytest.raises(ValueError, match="KEY_LEG_STALE_OR_CLOSED"):
        send(s, maps, sid, "resolve")
    assert len(adapter.calls) == 2


def test_key_pair_does_not_send_other_unsupported_activity(key_leg):
    from travel_agent.planning.flow_models import Activity

    s, v, maps, adapter = key_leg
    sid = v["session_id"]
    draft = PlanDraft.model_validate(v["draft"])
    draft.activities.append(
        Activity(
            activity_id="user-only",
            name="未采信的其他项目",
            provenance="USER_INPUT",
            region=v["destination"],
        )
    )
    v = s.plans.mutate(
        sid, PlanAction(action="save", expected_revision=v["revision"], draft=draft), str(uuid4())
    )
    pair = v["critical_map"]["pairs"][0]
    send(s, maps, sid, "start", leg_id=pair["leg_id"], consent=CONSENT)
    for place in [p for p in maps.get(sid)["places"] if p["place_id"] in pair["place_ids"]]:
        send(
            s,
            maps,
            sid,
            "confirm",
            place_id=place["place_id"],
            candidate_id=place["candidates"][0]["candidate_id"],
            relation="SAME_OBJECT",
        )
    send(s, maps, sid, "route")
    assert len(adapter.calls) == 3 and "未采信的其他项目" not in str(adapter.calls)
