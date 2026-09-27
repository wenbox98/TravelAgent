"""P10 scope compatibility retains strict checks and immutable local replay."""

from copy import deepcopy
from datetime import timedelta

import pytest
from test_advisory_guide import normal as normal_fixture, synthetic, proposal, line, GuideModel
from test_daily_workbench import permit
from test_planning_flow import act
from travel_agent.planning.flow_models import PlanDraft, PlanCreate
from travel_agent.planning.guide_models import BudgetLine, TripBudget
from travel_agent.planning import advisory
from travel_agent.planning.lodging import context
from travel_agent.planning.guide_view import project, export
from travel_agent.planning.suggestions import payload_for, run_worker
from uuid import uuid4

normal = normal_fixture


@pytest.mark.parametrize(
    "days,nights,scope,want",
    [
        (1, None, "AUTO", "OUT_OF_SCOPE"),
        (1, 0, "AUTO", "OUT_OF_SCOPE"),
        (1, 1, "AUTO", "IN_SCOPE"),
        (2, None, "AUTO", "UNDECIDED"),
        (1, None, "INCLUDE", "IN_SCOPE"),
        (2, None, "EXCLUDE", "OUT_OF_SCOPE"),
        (2, 1, "EXCLUDE", "OUT_OF_SCOPE"),
    ],
)
def test_lodging_scope_not_amount(days, nights, scope, want):
    d = PlanDraft(days=days, trip_budget=TripBudget(nights=nights, lodging_scope=scope))
    d.trip_budget.lines = [BudgetLine(line_id="lodging", label="住宿", category="LODGING")]
    g = project({"draft": d.model_dump()})
    assert context(d)["state"] == want
    row = next(x for x in g["budget"]["lines"] if x["line_id"] == "lodging")
    assert row["total"]["min_fen"] is None and row["unit_amount"]["min_fen"] is None
    assert (row["counting"] == "EXCLUDED") == (want == "OUT_OF_SCOPE")
    assert g["budget"]["completeness"] == "PARTIAL"


@pytest.mark.parametrize(
    "extra", [dict(paid_fen=1000), dict(locked=True), dict(basis="USER_BUDGET_TARGET")]
)
def test_protected_lodging_kept_even_one_day(extra):
    cost = line("room", "LODGING", "ONCE", 300, 500).model_copy(update=extra)
    d = PlanDraft(days=1, trip_budget=TripBudget(nights=0, lodging_scope="EXCLUDE", lines=[cost]))
    assert context(d)["state"] == "IN_SCOPE"
    g = project({"draft": d.model_dump()})
    assert g["budget"]["known_total"]["min_fen"] == 30000
    assert g["budget"]["paid_fen"] == extra.get("paid_fen", 0)


def one_day(s):
    v = synthetic(s)
    d = PlanDraft.model_validate(v["draft"])
    d.days = 1
    d.trip_budget.nights = None
    d.trip_budget.rooms = None
    for a in d.activities:
        a.day = 1
    return act(s, v, "save", draft=d)


def empty_proposal(data):
    raw = proposal(data)
    p = raw["proposals"][0]
    for a in p["activities"]:
        a["day"] = 1
    p["lodging"]["strategy"] = "NOT_APPLICABLE"
    p["budget_lines"] = [
        BudgetLine(
            line_id="unknown-room",
            label="住宿预留（如需过夜）",
            category="LODGING",
            conditions=["金额未知"],
            is_synthetic=data["synthetic"],
        ).model_dump()
    ]
    return raw


def test_empty_line_normalization_and_independent_full_checks(normal):
    s, _ = normal
    v = one_day(s)
    _, st = s.load(v["session_id"])
    data = payload_for(st["planning"], s.db, s.scope, v["session_id"])
    raw = empty_proposal(data)
    bad = deepcopy(raw["proposals"][0])
    bad["budget_lines"][0] = line("nonempty", "LODGING", "ONCE", 100, 200).model_dump()
    raw["proposals"].append(bad)
    result = advisory.validate(raw, data)
    assert result["accepted_count"] == result["rejected_count"] == 1
    v = result["proposals"][0]["budget_lines"][0]
    assert (
        v["basis"] == "UNKNOWN"
        and v["inclusion"] == "OUT_OF_SCOPE"
        and v["unit_amount"]["min_fen"] is None
    )
    assert result["proposals"][0]["normalizations"][0]["original"]["basis"] == "UNKNOWN"
    for change in ("claim", "reference", "money"):
        r = empty_proposal(data)
        p = r["proposals"][0]
        if change == "claim":
            p["budget_lines"][0]["conditions"] = ["住宿已确认，无需另行预订"]
        elif change == "reference":
            p["citation_ids"] = ["invented"]
        else:
            p["activities"][0]["stay_min"] = 1000
        assert advisory.validate(r, data)["accepted_count"] == 0


@pytest.mark.parametrize("obstacle", ["none", "edit", "expiry"])
def test_explicit_local_revalidation_preview_cancel_adopt(normal, monkeypatch, obstacle):
    s, _ = normal
    v = act(s, permit(s, one_day(s), 1), "suggest")

    class Saved(GuideModel):
        def structured(self, *args):
            return empty_proposal(args[1])

    validate = advisory.validate

    def old(raw, data):
        r = validate(raw, data)
        r.update(
            proposals=[],
            accepted_count=0,
            rejected_count=1,
            decisions=[
                dict(
                    proposal_id="old",
                    status="REJECTED",
                    reason="GUIDE_LODGING_NOT_APPLICABLE",
                    field="budget_lines",
                )
            ],
        )
        return r

    with monkeypatch.context() as m:
        m.setattr(advisory, "validate", old)
        run_worker(s.db.path, v["job"]["job_id"], Saved())
    v = s.get(v["session_id"])
    original = deepcopy(v["draft"])
    old_job = tuple(
        s.db.connection.execute(
            "SELECT status,request_json,summary_json FROM preview_jobs WHERE job_id=?",
            (v["job"]["job_id"],),
        ).fetchone()
    )
    v = act(s, v, "revalidate_guide")
    assert v["local_guide_review"]["summary"]["accepted_count"] == 1
    v = act(s, v, "use_revalidated_guide")
    assert v["proposal_preview_active"] and v["guide_view"]["local_revalidation"]
    v = act(s, v, "cancel")
    assert v["draft"] == original
    v = act(s, v, "use_revalidated_guide")
    if obstacle == "edit":
        d = PlanDraft.model_validate(v["draft"])
        d.days = 3
        v = act(s, v, "save", draft=d)
        with pytest.raises(ValueError, match="STALE_PROPOSAL"):
            act(s, v, "adopt")
    elif obstacle == "expiry":
        now = s.db.clock()
        monkeypatch.setattr(s.db, "clock", lambda: now + timedelta(days=8))
        with pytest.raises(ValueError, match="DIAGNOSTIC_EXPIRED"):
            act(s, v, "adopt")
    else:
        v = act(s, v, "adopt")
        assert (
            v["adopted"]
            and "LOCAL_REVALIDATION" in export(s.db, s.scope, v["session_id"])["markdown"]
        )
    assert (
        tuple(
            s.db.connection.execute(
                "SELECT status,request_json,summary_json FROM preview_jobs WHERE job_id=?",
                (v["job"]["job_id"],),
            ).fetchone()
        )
        == old_job
    )
    assert v["operation"]["cumulative_used"]["model"] == 1


def test_fixed_request_retains_known_conditions_without_old_defaults(normal):
    s, _ = normal
    v = s.create(
        PlanCreate(
            destination="成都",
            request="成都周边两天一晚，2个人、1间房，交通还没决定，不要排得太满。",
            validation_trip=True,
        ),
        str(uuid4()),
    )
    d = v["draft"]
    assert (
        d["days"] == 2
        and d["trip_budget"]["nights"] == 1
        and d["trip_budget"]["people"] == 2
        and d["trip_budget"]["rooms"] == 1
    )
    assert (
        d["transport"] == "UNKNOWN"
        and d["inputs"]["activity_start"] is None
        and d["walking_allowed"] is None
    )


def test_unknown_paid_lodging_never_disappears_from_payment_total():
    d = PlanDraft(
        days=1,
        trip_budget=TripBudget(
            lines=[
                BudgetLine(
                    line_id="old-room",
                    label="旧住宿",
                    category="LODGING",
                    basis="NOT_APPLICABLE",
                    paid_fen=2000,
                    locked=True,
                )
            ]
        ),
    )
    result = project({"draft": d.model_dump()})["budget"]
    assert result["paid_fen"] == 2000
    assert (
        "old-room" in result["unknown_line_ids"] and "old-room" not in result["excluded_line_ids"]
    )
    assert result["known_total"]["min_fen"] is None
