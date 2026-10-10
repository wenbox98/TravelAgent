"""Advisory production contracts: no clocks, honest money, reversible choices."""

from copy import deepcopy
from uuid import uuid4
import pytest
from travel_agent.planning.flow_models import PlanCreate, PlanDraft
from travel_agent.planning.guide_models import BudgetLine, TripBudget
from travel_agent.planning.trip_budget import calculate
from travel_agent.planning.advisory import validate, payload
from test_daily_workbench import normal as normal_fixture
from test_daily_workbench import permit
from test_planning_flow import act
from travel_agent.planning.suggestions import run_worker, payload_for
from travel_agent.planning.guide_view import export

normal = normal_fixture


def synthetic(s):
    return s.create(PlanCreate(destination="虚构双片区", demo="GUIDE_MULTI_DAY"), str(uuid4()))


def line(key, category, unit, low, high, **extra):
    return BudgetLine(
        line_id=key,
        label="合成预算目标",
        category=category,
        unit=unit,
        quantity=1,
        unit_amount=dict(min_fen=low * 100, max_fen=high * 100, currency="CNY"),
        status="ESTIMATED",
        basis="AI_BUDGET_PROPOSAL",
        is_synthetic=True,
        **extra,
    )


def test_four_item_subtotal_does_not_hide_unknown_round_trip():
    b = TripBudget(
        people=2,
        days=2,
        nights=1,
        rooms=1,
        lines=[
            line("room", "LODGING", "PER_ROOM_NIGHT", 300, 500),
            line("food", "FOOD", "PER_PERSON_DAY", 80, 120),
            line("ticket", "ACTIVITY", "PER_PERSON", 120, 120),
            line("local", "TRANSPORT", "PER_PERSON_DAY", 20, 40, transport_scope="LOCAL"),
            BudgetLine(
                line_id="return",
                label="往返未知",
                category="TRANSPORT",
                transport_scope="ROUND_TRIP",
            ),
        ],
    )
    out = calculate(b, ["a", "c"])
    assert out["known_total"] == {"min_fen": 94000, "max_fen": 138000, "currency": "CNY"}
    assert out["completeness"] == "PARTIAL" and "return" in out["unknown_line_ids"]


def test_unknown_people_rooms_not_assumed_and_paid_not_doubled():
    b = TripBudget(
        days=2,
        lines=[
            line("food", "FOOD", "PER_PERSON_DAY", 80, 120),
            line("room", "LODGING", "PER_ROOM_NIGHT", 300, 500),
        ],
    )
    out = calculate(b, [])
    assert out["known_total"]["min_fen"] is None
    assert out["per_person"]["min_fen"] == 16000
    paid = line("ticket", "ACTIVITY", "ONCE", 100, 100, paid_fen=4000, locked=True)
    out = calculate(TripBudget(lines=[paid]), [])
    assert out["known_total"]["min_fen"] == 10000 and out["paid_fen"] == 4000
    assert out["remaining_fen"]["min_fen"] == 6000


def proposal(data):
    ids = data["selected_activity_ids"]
    return dict(
        protocol_version=4,
        proposals=[
            dict(
                title="保留弹性的建议",
                reason="先选感兴趣的项目，再决定节奏。",
                activities=[
                    dict(
                        activity_id=i,
                        day=1 if n == 0 else 2,
                        period="UNDECIDED",
                        stay_min=40,
                        stay_max=70,
                        rest_minutes=None,
                    )
                    for n, i in enumerate(ids)
                ],
                citation_ids=data["allowed_citation_ids"],
                assumptions=["停留仅为建议"],
                unknowns=["交通与开放未核实"],
                impacts=["不用提前排满时刻"],
                dining=[dict(day=1, window="LUNCH", strategy="BETWEEN_ACTIVITIES")],
                lodging=dict(strategy="FEWER_MOVES", area_ids=[]),
                budget_lines=[],
            )
        ],
    )


@pytest.mark.parametrize("text", ["不代表价格已核实", "并非已核实", "不是已核实"])
def test_narrow_unverified_disclaimer_is_not_a_fact_assertion(normal, text):
    s, _ = normal
    v = synthetic(s)
    _, state = s.load(v["session_id"])
    data = payload(s.db, s.scope, v["session_id"], state["planning"])
    raw = proposal(data)
    raw["proposals"][0]["assumptions"] = ["金额仅为AI预留，" + text + "。"]
    assert validate(raw, data)["accepted_count"] == 1
    raw["proposals"][0]["assumptions"].append("价格已核实，公交20分钟即可到达。")
    assert validate(raw, data)["accepted_count"] == 0


def test_new_default_unknown_clock_movement_rest_still_useful(normal):
    s, _ = normal
    v = s.create(PlanCreate(destination="另一座城"), str(uuid4()))
    assert v["draft"]["planning_mode"] == "ADVISORY"
    assert v["draft"]["inputs"]["activity_start"] is None and v["draft"]["transport"] == "UNKNOWN"
    v = synthetic(s)
    _, state = s.load(v["session_id"])
    data = payload(s.db, s.scope, v["session_id"], state["planning"])
    assert data["first_start"] is None and data["known_map_values"] == []
    assert data["walking_allowed"] is None
    result = validate(proposal(data), data)
    assert (
        result["accepted_count"] == 1
        and result["proposals"][0]["activities"][0]["rest_minutes"] is None
    )
    wrong = proposal(data)
    wrong["proposals"][0]["reason"] = "步行不可用，只能另选交通"
    assert validate(wrong, data)["accepted_count"] == 0


def test_combination_cancel_adopt_locks_and_unknown_costs(normal):
    s, _ = normal
    v = act(s, synthetic(s), "adopt")
    original = deepcopy(v["adopted"])
    v = act(s, v, "preview_combination", activity_ids=["guide-a", "guide-b", "guide-d"])
    assert [a["activity_id"] for a in v["draft"]["activities"]] == ["guide-a", "guide-b", "guide-d"]
    assert v["adopted"] == original
    v = act(s, v, "cancel")
    assert v["draft"] == original
    d = PlanDraft.model_validate(v["draft"])
    d.activities[1].locked_start = "14:00"
    v = act(s, v, "save", draft=d)
    with pytest.raises(ValueError, match="LOCKED"):
        act(s, v, "preview_combination", activity_ids=["guide-a", "guide-b", "guide-d"])


def test_model_quote_forgery_rejected_but_budget_proposal_allowed(normal):
    s, _ = normal
    v = synthetic(s)
    _, state = s.load(v["session_id"])
    data = payload(s.db, s.scope, v["session_id"], state["planning"])
    raw = proposal(data)
    raw["proposals"][0]["budget_lines"] = [
        line("food", "FOOD", "PER_PERSON_DAY", 80, 120).model_dump()
    ]
    assert validate(raw, data)["accepted_count"] == 1
    raw["proposals"][0]["budget_lines"][0]["basis"] = "OBSERVED_QUOTE"
    raw["proposals"][0]["budget_lines"][0]["status"] = "QUOTED"
    assert validate(raw, data)["accepted_count"] == 0


def test_known_budget_factors_cannot_be_declared_unknown(normal):
    s, _ = normal
    v = synthetic(s)
    _, state = s.load(v["session_id"])
    data = payload_for(state["planning"], s.db, s.scope, v["session_id"])
    raw = proposal(data)
    good = deepcopy(raw["proposals"][0])
    raw["proposals"][0]["budget_lines"] = [
        line("food", "FOOD", "PER_DAY", 80, 120, conditions=["人数未定，按实际调整"]).model_dump()
    ]
    raw["proposals"].append(good)
    result = validate(raw, data)
    assert result["rejected_count"] == result["accepted_count"] == 1
    assert result["decisions"][0]["reason"] == "GUIDE_BUDGET_CONTEXT_CONFLICT"


def test_soft_anchor_not_locked_and_appointment_is(normal):
    s, _ = normal
    v = synthetic(s)
    _, state = s.load(v["session_id"])
    state["planning"]["draft"]["inputs"]["activity_start"] = "10:00"
    data = payload(s.db, s.scope, v["session_id"], state["planning"])
    assert data["first_start"] is None and data["flexible_start"] == "10:00"
    raw = proposal(data)
    data["activities"][0]["locked_start"] = "14:00"
    raw["proposals"][0]["activities"].pop(0)
    assert validate(raw, data)["accepted_count"] == 0


class GuideModel:
    calls = 0

    def structured(self, task, data, schema):
        self.calls += 1
        assert task == "planning_advisory_v4"
        raw = proposal(data)
        if data["synthetic"]:
            raw["proposals"][0]["budget_lines"] = [
                line("room", "LODGING", "PER_ROOM_NIGHT", 300, 500).model_dump(),
                line("food", "FOOD", "PER_PERSON_DAY", 80, 120).model_dump(),
                line(
                    "local", "TRANSPORT", "PER_PERSON_DAY", 20, 40, transport_scope="LOCAL"
                ).model_dump(),
                *[
                    line(
                        "cost-" + x, "ACTIVITY", "PER_PERSON", 60, 60, activity_ids=["guide-" + x]
                    ).model_dump()
                    for x in "abcd"
                ],
            ]
        return raw


def test_normal_grant_worker_combination_money_export_and_restart(normal):
    import json
    import subprocess
    import sys

    s, _ = normal
    v = permit(s, synthetic(s), 1)
    assert v["model_available"], v["model_status"]
    v = act(s, v, "suggest")
    model = GuideModel()
    run_worker(s.db.path, v["job"]["job_id"], model)
    v = s.get(v["session_id"])
    assert v["job"]["accepted_count"] == 1, v["job"]
    assert not v["model_available"]
    original = deepcopy(v["draft"])
    v = act(s, v, "use_proposal")
    assert v["draft"]["inputs"]["activity_start"] is None
    v = act(s, v, "cancel")
    assert v["draft"] == original
    v = act(s, act(s, v, "use_proposal"), "adopt")
    assert v["guide_view"]["budget"]["known_total"]["min_fen"] == 94000
    adopted = deepcopy(v["adopted"])
    v = act(s, v, "preview_combination", activity_ids=["guide-a", "guide-b", "guide-d"])
    assert v["guide_view"]["budget_difference"]["min_fen"] == 12000
    assert v["guide_view"]["origin"] == "USER_CONFIRMED"
    assert "原模型提议保留" in v["guide_view"]["reason"]
    assert v["draft"]["activities"][0]["timing_origin"] == "AI_PROPOSED"
    assert v["job"]["proposals"][0]["title"] == adopted["guide"]["title"]
    assert v["guide_view"]["budget"]["known_total"]["min_fen"] == 106000
    assert v["adopted"] == adopted
    v = act(s, v, "cancel")
    assert v["draft"] == adopted
    v = act(
        s, act(s, v, "preview_combination", activity_ids=["guide-a", "guide-b", "guide-d"]), "adopt"
    )
    out = export(s.db, s.scope, v["session_id"])
    assert "合成B手作" in out["markdown"] and "合成C漫步" not in out["markdown"]
    assert "1060.00–1500.00" in out["markdown"] and "自行安排" in out["markdown"]
    assert "api.deepseek.com" not in out["markdown"] and "sqlite" not in out["markdown"]
    assert model.calls == 1 and v["operation"]["cumulative_used"]["model"] == 1
    code = """
import sys,socket,json
from pathlib import Path
sys.path.insert(0,str(Path('apps/api').resolve()))
def denied(*a,**kw): raise AssertionError('NETWORK')
socket.getaddrinfo=denied;socket.socket.connect=denied
from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
from travel_agent.planning.guide_view import export
with Database(Path(sys.argv[1])) as db:
 v=PlanningService(db,'owner').get(sys.argv[2])
 assert v['draft']['inputs']['activity_start'] is None
 assert [a['activity_id'] for a in v['adopted']['activities']]==['guide-a','guide-b','guide-d']
 assert v['guide_view']['budget']['known_total']['min_fen']==106000
 assert v['guide_view']['dining'] and v['guide_view']['lodging']['text']
 print(json.dumps(export(db,'owner',sys.argv[2]),ensure_ascii=False))
"""
    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code, str(s.db.path), v["session_id"]],
        capture_output=True,
        text=True,
        encoding="utf8",
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["markdown"] == out["markdown"]


@pytest.mark.parametrize("change", ["edit", "cancel", "revoke"])
def test_late_guide_never_overwrites_adopted_or_refunds(normal, change):
    s, _ = normal
    v = permit(s, act(s, synthetic(s), "adopt"), 1)
    original = deepcopy(v["adopted"])
    v = act(s, v, "suggest")

    class Late(GuideModel):
        def structured(self, task, data, schema):
            value = super().structured(task, data, schema)
            current = s.get(v["session_id"])
            if change == "edit":
                d = PlanDraft.model_validate(current["draft"])
                d.days = 3
                act(s, current, "save", draft=d)
            else:
                act(s, current, "cancel_job" if change == "cancel" else "revoke_authorization")
            return value

    run_worker(s.db.path, v["job"]["job_id"], Late())
    now = s.get(v["session_id"])
    assert now["adopted"] == original and now["job"]["status"] in {"FAILED", "CANCELED"}
    assert now["operation"]["cumulative_used"]["model"] == 1


def test_cleared_knowledge_guides_without_raw_and_withdrawal_blocks_export(normal):
    from test_knowledge_library import organize
    from travel_agent.knowledge.planning import attach
    from travel_agent.knowledge.store import Library, binding, no_raw
    from travel_agent.knowledge.cleanup import preview, clear

    s, old = normal
    card = next(c for c in organize(s, old) if c["entities"])
    v = s.create(
        PlanCreate(destination="合成青谷", knowledge_first=True, request="一天"), str(uuid4())
    )
    v = attach(s.db, s.scope, v["session_id"], [binding(card)], v["revision"], True)
    pre = preview(s.db, s.scope, [binding(card)])
    clear(s.db, s.scope, [binding(card)], pre["preview_hash"])
    with no_raw(s.db):
        _, state = s.load(v["session_id"])
        data = payload_for(state["planning"], s.db, s.scope, v["session_id"])
        assert data["protocol_version"] == 4 and data["first_start"] is None
        raw = proposal(data)
        for a in raw["proposals"][0]["activities"]:
            a["day"] = 1
        raw["proposals"][0]["lodging"]["strategy"] = "NOT_APPLICABLE"
        assert validate(raw, data)["accepted_count"] == 1
    v = act(s, v, "adopt")
    before = export(s.db, s.scope, v["session_id"])
    assert "来源依据" in before["markdown"]
    Library(s.db, s.scope).remove([binding(card)])
    with pytest.raises(ValueError):
        export(s.db, s.scope, v["session_id"])
    assert s.get(v["session_id"])["adopted"] == v["adopted"]


def test_budget_unknown_zero_partial_bundle_and_user_cannot_forge_quote():
    from pydantic import ValidationError
    from travel_agent.planning.trip_budget import preserve_edits

    with pytest.raises(ValidationError):
        BudgetLine(
            line_id="x",
            label="未知",
            category="FOOD",
            unit_amount=dict(min_fen=0, max_fen=0, currency="CNY"),
        )
    bundled = line("x", "ACTIVITY", "PER_PERSON", 120, 120, activity_ids=["a", "c"])
    out = calculate(TripBudget(people=2, lines=[bundled]), ["a", "b", "d"])
    assert out["known_total"]["min_fen"] is None and out["lines"][0]["counting"] == "UNKNOWN"
    quoted = line("q", "FOOD", "ONCE", 100, 100).model_copy(
        update=dict(
            basis="OBSERVED_QUOTE", status="QUOTED", quote_id="untrusted", queried_at="2026-01-01"
        )
    )
    with pytest.raises(ValueError, match="REFERENCE"):
        preserve_edits(TripBudget(), TripBudget(lines=[quoted]))


def test_legacy_missing_fields_keep_detailed_semantics_and_scope_isolation(normal):
    s, old = normal
    raw = deepcopy(old["draft"])
    for key in ("planning_mode", "start_constraint", "end_constraint", "guide", "trip_budget"):
        raw.pop(key, None)
    d = PlanDraft.model_validate(raw)
    assert (
        d.planning_mode == "DETAILED"
        and d.start_constraint == "LOCKED"
        and d.inputs.activity_start == "09:30"
    )
    for destination in ("另一座城", "合成青谷"):
        v = s.create(PlanCreate(destination=destination, travel_kind="REGIONAL"), str(uuid4()))
        assert v["draft"]["activities"] == [] and v["draft"]["transport"] == "UNKNOWN"
        assert not v["guide_view"]["available"]


def test_request_times_and_independent_hard_constraint_rejection(normal):
    s, _ = normal
    v = s.create(
        PlanCreate(destination="另一座城", request="十点左右开始，预约下午两点，必须晚上九点返回"),
        str(uuid4()),
    )
    assert v["draft"]["inputs"]["activity_start"] == "10:00"
    assert v["draft"]["start_constraint"] == "FLEXIBLE"
    assert v["draft"]["return_deadline"] == "21:00"
    assert any("预约" in n for n in v["guide_view"]["unknowns"])
    v = synthetic(s)
    _, state = s.load(v["session_id"])
    data = payload_for(state["planning"], s.db, s.scope, v["session_id"])
    data["activities"][0]["locked_start"] = "14:00"
    data["return_deadline"] = "15:00"
    raw = proposal(data)
    bad = deepcopy(raw["proposals"][0])
    bad["activities"][0].update(stay_min=120, stay_max=180)
    raw["proposals"].append(bad)
    checked = validate(raw, data)
    assert checked["accepted_count"] == 1 and checked["rejected_count"] == 1
    assert checked["decisions"][1]["reason"] == "PLANNING_LOCKED_CONSTRAINT"


def test_failed_advisory_retains_bounded_local_replay(normal):
    from travel_agent.planning.revision_diagnostics import replay

    s, _ = normal
    v = act(s, permit(s, synthetic(s), 1), "suggest")

    class Invalid(GuideModel):
        def structured(self, task, data, schema):
            raw = super().structured(task, data, schema)
            raw["proposals"][0]["reason"] = "已核实房态充足"
            return raw

    model = Invalid()
    run_worker(s.db.path, v["job"]["job_id"], model)
    now = s.get(v["session_id"])
    assert now["job"]["accepted_count"] == 0
    assert now["job"]["local_diagnostic"]["replayable"]
    result = replay(s.db, s.scope, v["job"]["job_id"], "a" * 40)
    assert result["external_calls"] == 0 and result["summary"]["rejected_count"] == 1
    assert model.calls == 1 and s.get(v["session_id"])["adopted"] is None


def test_budget_target_optional_and_locked_payment():
    from travel_agent.planning.trip_budget import preserve_edits

    paid = line("paid", "ACTIVITY", "ONCE", 80, 120, paid_fen=3000, locked=True)
    optional = line("extra", "RESERVE", "ONCE", 500, 500, optional=True)
    b = TripBudget(lines=[paid, optional], target_fen=10000, target_locked=True)
    result = calculate(b, [])
    assert result["known_total"]["max_fen"] == 12000
    assert "上界" in result["target_note"] and result["paid_fen"] == 3000
    with pytest.raises(ValueError, match="LOCKED"):
        preserve_edits(b, TripBudget(lines=[optional]))


def test_older_walking_default_cannot_preview_after_contract_correction(normal):
    import json

    s, _ = normal
    v = act(s, permit(s, synthetic(s), 1), "suggest")
    run_worker(s.db.path, v["job"]["job_id"], GuideModel())
    jid = v["job"]["job_id"]
    row = s.db.connection.execute(
        "SELECT request_json FROM preview_jobs WHERE job_id=?", (jid,)
    ).fetchone()
    old = json.loads(row[0])
    old["payload"]["walking_allowed"] = False
    s.db.connection.execute(
        "UPDATE preview_jobs SET request_json=? WHERE job_id=?", (json.dumps(old), jid)
    )
    now = s.get(v["session_id"])
    assert not now["job"]["can_preview"] and now["job"]["accepted_count"] == 1
    with pytest.raises(ValueError, match="STALE_PROPOSAL"):
        act(s, now, "use_proposal")
    assert s.get(v["session_id"])["adopted"] is None


def test_guide_export_requires_local_authenticated_session(normal):
    from fastapi.testclient import TestClient
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.main import create_app
    from travel_agent.settings import Settings

    s, _ = normal
    v = act(s, synthetic(s), "adopt")
    config = PreviewConfig(
        s.db.path,
        "owner",
        "CACHED_PRIVATE_PREVIEW",
        b"a" * 32,
        product_flow=True,
        daily_workbench=True,
    )
    with TestClient(
        create_app(Settings.load(preferred_port=18768), preview=config),
        base_url="http://127.0.0.1:18768",
    ) as client:
        url = "/api/v1/preview/planning/" + v["session_id"] + "/guide-export"
        assert client.get(url).status_code == 401
        client.get("/bootstrap?ticket=" + config.ticket)
        out = client.get(url)
        assert out.status_code == 200 and "合成A慢游" in out.json()["markdown"]
        assert client.get(url, headers={"Origin": "https://untrusted.example"}).status_code == 403
