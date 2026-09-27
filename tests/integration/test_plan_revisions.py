"""Authored revisions through normal planning services and workers; no live access."""

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
import subprocess
import sys
from uuid import uuid4

import pytest

from travel_agent.planning.flow_models import PlanAction, PlanDraft
from travel_agent.planning.private_budget import DISCOVERY_IDENTIFIER, REVISION_IDENTIFIER, GRANTS
from travel_agent.planning.revisions import validate, base
from travel_agent.planning.revision_diagnostics import directory, replay, cleanup
from travel_agent.planning.suggestions import run_worker
from test_place_discovery import discovery as discovery_fixture, discover_and_check, Planner
from test_planning_flow import act

discovery = discovery_fixture


@pytest.fixture
def revision(discovery):
    s, v = discovery
    v, _, _ = discover_and_check(s, v, 2)
    v = act(s, v, "use_leads", activity_ids=[lead["lead_id"] for lead in v["place_leads"][:2]])
    v = act(s, v, "suggest")
    run_worker(s.db.path, v["job"]["job_id"], Planner())
    v = act(s, s.get(v["session_id"]), "use_proposal")
    v = act(s, v, "adopt")
    old = s.db.connection.execute(
        "SELECT * FROM research_continuations WHERE continuation_id=?", (DISCOVERY_IDENTIFIER,)
    ).fetchone()
    s.db.connection.execute(
        "INSERT INTO research_continuations VALUES(?,?,?,?,?,?,NULL,?,?)",
        (
            REVISION_IDENTIFIER,
            "owner",
            DISCOVERY_IDENTIFIER,
            old[3],
            s.db.stamp(),
            s.db.stamp(),
            json.dumps(GRANTS[REVISION_IDENTIFIER]),
            old["gate_json"],
        ),
    )
    yield s, s.get(v["session_id"])


def adjust(s, v, intent="LONGER_FIRST", minutes=None):
    d = PlanDraft.model_validate(v["draft"])
    d.adjustment, d.adjustment_minutes = intent, minutes
    return act(s, v, "save", draft=d)


def proposal(data):
    p = dict(
        reason_code=data["adjustment"],
        activities=[
            {k: a[k] for k in ("activity_id", "day", "stay_min", "stay_max", "rest_minutes")}
            for a in data["activities"]
        ],
        citation_ids=data["allowed_citation_ids"],
    )
    if data["adjustment"] == "LONGER_FIRST":
        for k in ("stay_min", "stay_max"):
            p["activities"][0][k] += data.get("adjustment_minutes") or 15
    else:
        p["activities"].pop()
    return p


class Model:
    def __init__(self, transform=None):
        self.calls = 0
        self.transform = transform

    def structured(self, task, data, schema):
        self.calls += 1
        assert task == "planning_revision_v3" and data["known_map_values"] == []
        p = proposal(data)
        return dict(
            protocol_version=3, proposals=self.transform(p, data) if self.transform else [p]
        )


def test_real_services_preview_cancel_repreview_adopt_fewer_and_recovery(revision):
    s, v = revision
    initial = deepcopy(v["adopted"])
    old_rows = [tuple(r) for r in s.db.connection.execute("SELECT * FROM preview_jobs")]
    v = adjust(s, v)
    v = act(s, v, "suggest")
    jid = v["job"]["job_id"]
    model = Model()
    run_worker(s.db.path, jid, model)
    run_worker(s.db.path, jid, model)
    v = s.get(v["session_id"])
    assert model.calls == 1 and v["job"]["can_preview"]
    assert v["job"]["local_diagnostic"]["replayable"]
    assert (
        v["job"]["proposals"][0]["changes"][0]["after"]
        - v["job"]["proposals"][0]["changes"][0]["before"]
        == 15
    )
    v = act(s, v, "use_proposal")
    assert v["adopted"] == initial
    v = act(s, v, "cancel")
    assert base(v["draft"]) == base(initial) and v["job"]["can_preview"]
    v = act(s, v, "use_proposal")
    key = str(uuid4())
    action = PlanAction(action="adopt", expected_revision=v["revision"])
    v = s.mutate(v["session_id"], action, key)
    again = s.mutate(v["session_id"], action, key)
    assert v == again
    assert v["adopted"]["activities"][0]["stay_min"] == initial["activities"][0]["stay_min"] + 15
    assert v["adopted"]["activities"][1] == initial["activities"][1]
    assert not v["job"]["can_preview"]
    v = adjust(s, v, "FEWER")
    assert v["model_available"]
    v = act(s, v, "suggest")
    run_worker(s.db.path, v["job"]["job_id"], model)
    v = act(s, s.get(v["session_id"]), "use_proposal")
    v = act(s, v, "adopt")
    assert len(v["adopted"]["activities"]) == 1 and v["private_budget"]["used"]["model"] == 2
    assert not v["model_available"] and v["draft"]["inputs"]["activity_start"] == "10:00"
    assert v["draft"]["transport"] == "PUBLIC_TRANSIT"
    assert all(
        tuple(r) in [tuple(x) for x in s.db.connection.execute("SELECT * FROM preview_jobs")]
        for r in old_rows
    )
    before = s.db.connection.execute(
        "SELECT summary_json FROM preview_jobs WHERE job_id=?", (jid,)
    ).fetchone()[0]
    out = replay(s.db, "owner", jid, "a" * 40)
    assert out["kind"] == "LOCAL_REVALIDATION" and out["summary"]["accepted_count"] == 1
    assert (
        s.db.connection.execute(
            "SELECT summary_json FROM preview_jobs WHERE job_id=?", (jid,)
        ).fetchone()[0]
        == before
    )
    code = """
import sys,socket
from pathlib import Path
sys.path.insert(0,str(Path('apps/api').resolve()))
def deny(*a,**kw):raise AssertionError('NETWORK')
socket.getaddrinfo=deny;socket.socket.connect=deny
from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
with Database(Path(sys.argv[1])) as db:
 s=PlanningService(db,'owner');v=s.get(sys.argv[2]);assert len(v['adopted']['activities'])==1
 assert v['adopted']['activities'][0]['timing_origin']=='AI_PROPOSED'
 assert v['adopted']['activities'][0]['provenance']=='SOURCE_MENTION'
 assert v['private_budget']['used']['model']==2
 print('NONEMPTY_ZERO_ACCESS')
"""
    r = subprocess.run(
        [sys.executable, "-c", code, str(s.db.path), v["session_id"]],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "NONEMPTY_ZERO_ACCESS" in r.stdout


@pytest.mark.parametrize(
    "case",
    [
        "same",
        "swap",
        "wrong_target",
        "lower_only",
        "inverted",
        "other_stay",
        "rest",
        "day",
        "new_id",
        "repeat_id",
        "no_citation",
        "transport",
        "anchor",
        "unknown_fact",
        "url",
    ],
)
def test_intent_constraints_independently_keep_two_good_proposals(revision, case):
    s, v = revision
    v = adjust(s, v)

    def transform(p, data):
        bad = deepcopy(p)
        if case == "same":
            bad["activities"][0]["stay_min"] -= 15
            bad["activities"][0]["stay_max"] -= 15
        elif case == "swap":
            bad["activities"].reverse()
        elif case == "wrong_target":
            bad["activities"][0] = deepcopy(data["activities"][0])
            bad["activities"][1]["stay_min"] += 15
        elif case == "lower_only":
            bad["activities"][0]["stay_max"] -= 15
        elif case == "inverted":
            bad["activities"][0]["stay_max"] = 10
        elif case == "other_stay":
            bad["activities"][1]["stay_min"] += 5
        elif case == "rest":
            bad["activities"][1]["rest_minutes"] += 5
        elif case == "day":
            bad["activities"][1]["day"] = 2
        elif case == "new_id":
            bad["activities"][0]["activity_id"] = "cross-trip"
        elif case == "repeat_id":
            bad["activities"][1]["activity_id"] = bad["activities"][0]["activity_id"]
        elif case == "no_citation":
            bad["citation_ids"] = []
        elif case == "transport":
            bad["transport"] = "SELF_DRIVE"
        elif case == "anchor":
            bad["first_start"] = "09:00"
        elif case == "unknown_fact":
            bad["unknowns"] = ["开放时间：未知，但门票免费"]
        elif case == "url":
            bad["url"] = "https://unsafe.invalid"
        return [p, bad, deepcopy(p)]

    v = act(s, v, "suggest")
    run_worker(s.db.path, v["job"]["job_id"], Model(transform))
    v = s.get(v["session_id"])
    if case == "url":
        assert v["job"]["accepted_count"] == 0 and not v["job"]["local_diagnostic"]["replayable"]
    else:
        assert v["job"]["accepted_count"] == 2 and v["job"]["rejected_count"] == 1
        assert v["job"]["decisions"][1]["field"].startswith("proposals[1].")


def test_failure_replay_expiry_cleanup_and_manual_edit(revision):
    s, v = revision
    v = adjust(s, v, minutes=20)
    model = Model(
        lambda p, d: [
            dict(
                p,
                activities=[
                    dict(a, stay_min=a["stay_min"] - 1) if i == 0 else a
                    for i, a in enumerate(p["activities"])
                ],
            )
        ]
    )
    v = act(s, v, "suggest")
    jid = v["job"]["job_id"]
    run_worker(s.db.path, jid, model)
    v = s.get(v["session_id"])
    assert v["job"]["status"] == "FAILED" and v["job"]["local_diagnostic"]["replayable"]
    assert v["job"]["decisions"][0]["reason"] == "REVISION_NOT_LONGER"
    assert not v["model_available"]
    assert replay(s.db, "owner", jid, "b" * 40)["summary"]["decisions"] == v["job"]["decisions"]
    with pytest.raises(ValueError):
        replay(s.db, "other", jid, "b" * 40)
    d = PlanDraft.model_validate(v["draft"])
    d.activities[0].stay_min += 5
    v = act(s, v, "save", draft=d)
    assert v["draft"]["activities"][0]["timing_origin"] == "USER_CONFIRMED"
    assert model.calls == 1
    from datetime import datetime

    now = datetime.fromisoformat(
        json.loads((directory(s.db) / (jid + ".json")).read_text())["expires_at"]
    )
    s.db.clock = lambda: now + timedelta(days=8)
    with pytest.raises(ValueError, match="EXPIRED"):
        replay(s.db, "owner", jid, "b" * 40)
    assert cleanup(s.db) == 2 and not list(directory(s.db).glob("*.json"))


def test_sensitive_content_not_stored_or_exposed_and_late_response_cannot_adopt(revision):
    s, v = revision
    v = adjust(s, v)
    original = deepcopy(v["adopted"])
    v = act(s, v, "suggest")
    jid = v["job"]["job_id"]
    sentinel = "sk-" + sha256(b"authored-credential-sentinel").hexdigest()
    run_worker(s.db.path, jid, Model(lambda p, d: [p, dict(p, reason=sentinel)]))
    v = s.get(v["session_id"])
    assert v["job"]["accepted_count"] == 0 and not v["job"]["local_diagnostic"]["replayable"]
    assert (
        sentinel not in json.dumps(v)
        and sentinel not in (directory(s.db) / (jid + ".json")).read_text()
    )
    assert v["adopted"] == original


def test_request_snapshot_revision_and_cancel_wins(revision):
    s, v = revision
    v = adjust(s, v)
    v = act(s, v, "suggest")
    jid = v["job"]["job_id"]

    def changing(p, data):
        current = s.get(v["session_id"])
        act(s, current, "cancel_job")
        return [p]

    run_worker(s.db.path, jid, Model(changing))
    v = s.get(v["session_id"])
    assert v["job"]["status"] == "CANCELED" and not v["job"]["can_preview"]
    with pytest.raises(ValueError):
        act(s, v, "use_proposal")


def test_changed_base_and_tampered_record_cannot_replay_or_preview(revision):
    s, v = revision
    v = adjust(s, v)
    v = act(s, v, "suggest")
    jid = v["job"]["job_id"]
    run_worker(s.db.path, jid, Model())
    v = s.get(v["session_id"])
    d = PlanDraft.model_validate(v["draft"])
    d.inputs.activity_start = "11:00"
    v = act(s, v, "save", draft=d)
    assert not v["job"]["can_preview"]
    with pytest.raises(ValueError, match="STALE"):
        act(s, v, "use_proposal")
    path = directory(s.db) / (jid + ".json")
    record = json.loads(path.read_text())
    record["proposals"]["proposals"][0]["activities"][0]["stay_min"] += 1
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="BINDING_CHANGED"):
        replay(s.db, "owner", jid, "c" * 40)


def test_fewer_keeps_locked_appointments_and_exact_count():
    from test_scope_locked_planning import inputs

    data = inputs() | dict(protocol_version=3, adjustment="FEWER", target_activity_id="a")
    for a in data["activities"]:
        a.update(stay_min=40, stay_max=70, rest_minutes=10)
    data["activities"][1]["locked_start"] = "15:00"
    good = proposal(data)
    good["activities"] = [dict(activity_id="b", day=1, stay_min=40, stay_max=70, rest_minutes=10)]
    bad = proposal(data)
    out = validate(dict(protocol_version=3, proposals=[bad, good]), data)
    assert (
        out["accepted_count"] == 1 and out["decisions"][0]["reason"] == "PLANNING_LOCKED_CONSTRAINT"
    )
    nochange = deepcopy(good)
    nochange["activities"].insert(
        0, dict(activity_id="a", day=1, stay_min=40, stay_max=70, rest_minutes=10)
    )
    assert validate(dict(protocol_version=3, proposals=[nochange]), data)["accepted_count"] == 0


@pytest.mark.parametrize(
    "text",
    [
        "开放时间未知",
        "开放时间：未知",
        "尚未查询开放时间，请先确认",
        "开放时间未知，但门票免费",
        "不保证十点开放",
        "已核实十点开放",
        "无需包车，保持公共交通",
        "改成自驾",
        "改成包车",
    ],
)
def test_legacy_text_is_not_a_v3_executable_channel(text):
    from test_scope_locked_planning import inputs, proposal as old_proposal
    from travel_agent.planning.arrangements import validate_arrangements

    data = inputs() | dict(discovery_mode=True, adjustment="LONGER_FIRST", target_activity_id="a")
    for a in data["activities"]:
        a.update(stay_min=40, stay_max=70, rest_minutes=10)
    old = old_proposal() | dict(reason=text)
    historical = validate_arrangements(dict(protocol_version=2, proposals=[old]), data)
    if text == "开放时间：未知":
        assert historical["accepted_count"] == 0
    good = proposal(data)
    result = validate(dict(protocol_version=3, proposals=[good, dict(good, reason=text)]), data)
    assert result["accepted_count"] == 1 and result["rejected_count"] == 1
    assert result["proposals"][0]["unknowns"] == ["活动范围、开放与到达时间仍待核实"]
    # V3 disallows free explanations; legacy decisions are not changed or promoted.
