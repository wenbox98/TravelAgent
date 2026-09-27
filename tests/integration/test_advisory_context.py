"""UI-compatible save -> API -> actual worker input and versioned consistency."""

from copy import deepcopy
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from travel_agent.main import create_app
from travel_agent.preview.api import PreviewConfig
from travel_agent.settings import Settings
from travel_agent.planning.suggestions import run_worker
from travel_agent.planning.flow_models import PlanCreate, PlanDraft
from travel_agent.planning.guide_context import walking
from travel_agent.planning.advisory import validate, payload
from test_advisory_guide import normal as normal_fixture
from test_advisory_guide import GuideModel, proposal, synthetic, line


@pytest.mark.parametrize(
    ("value", "expected"), [(None, "UNKNOWN"), (True, "ALLOWED"), (False, "DECLINED")]
)
def test_saved_page_dto_reaches_worker_and_adopted_export(normal, monkeypatch, value, expected):
    s, old = normal
    old_snapshot = s.db.connection.execute(
        "SELECT state_json FROM preview_sessions WHERE session_id=?", (old["session_id"],)
    ).fetchone()[0]
    config = PreviewConfig(
        s.db.path,
        "owner",
        "CACHED_PRIVATE_PREVIEW",
        b"a" * 32,
        product_flow=True,
        daily_workbench=True,
    )
    monkeypatch.setattr("travel_agent.planning.flow_api.launch", lambda *a, **kw: None)
    captured = []

    class Capture(GuideModel):
        def structured(self, task, data, schema):
            captured.append(deepcopy(data))
            assert schema["$defs"]["BudgetLine"]["properties"]["quantity"]["const"] == 1
            return super().structured(task, data, schema)

    with TestClient(
        create_app(Settings.load(preferred_port=18768), preview=config),
        base_url="http://127.0.0.1:18768",
    ) as client:
        client.get("/bootstrap?ticket=" + config.ticket)
        headers = {
            "Origin": "http://127.0.0.1:18768",
            "X-CSRF-Token": client.get("/api/v1/preview").json()["csrf_token"],
        }

        def post(url, body):
            out = client.post(url, json=body, headers={**headers, "Idempotency-Key": str(uuid4())})
            assert out.status_code == 200, out.text
            return out.json()

        v = post(
            "/api/v1/preview/planning", {"destination": "虚构双片区", "demo": "GUIDE_MULTI_DAY"}
        )
        url = "/api/v1/preview/planning/" + v["session_id"]

        def action(name, **fields):
            nonlocal v
            v = post(url, dict(action=name, expected_revision=v["revision"], **fields))

        draft = deepcopy(v["draft"])
        draft.update(walking_allowed=value, walking_origin="USER_EXPLICIT")
        action("save", draft=draft)
        action("authorize", authorization=dict(confirm=True, tasks=["PLANNING"], model=1))
        action("suggest")
        run_worker(s.db.path, v["job"]["job_id"], Capture())
        v = client.get(url).json()
        assert len(captured) == 1
        data = captured[0]
        assert data["walking_allowed"] is value and data["walking_preference"] == expected
        assert data["first_start"] is None and data["known_map_values"] == []
        assert data["budget_context"]["known_conditions"] == ["2人", "2天", "1晚", "1间房"]
        action("use_proposal")
        action("cancel")
        action("use_proposal")
        action("adopt")
        assert v["guide_view"]["walking"]["state"] == expected
        assert v["adopted"]["walking_allowed"] is value
        assert v["guide_view"]["budget_context"] == data["budget_context"]
        assert v["guide_view"]["budget"]["known_total"]["min_fen"] == 94000
        md = client.get(url + "/guide-export").json()["markdown"]
        assert "已知条件：2人、2天、1晚、1间房" in md and v["guide_view"]["walking"]["label"] in md
    assert s.get(v["session_id"])["adopted"] == v["adopted"]
    assert (
        s.db.connection.execute(
            "SELECT state_json FROM preview_sessions WHERE session_id=?", (old["session_id"],)
        ).fetchone()[0]
        == old_snapshot
    )


@pytest.mark.parametrize(
    ("text", "state"),
    [
        ("", "UNKNOWN"),
        ("不想多走路", "UNKNOWN"),
        ("明确不接受步行", "DECLINED"),
        ("公共交通和步行", "ALLOWED"),
    ],
)
def test_new_and_legacy_walking_semantics(normal, text, state):
    s, _ = normal
    v = s.create(PlanCreate(destination="另一座城", request=text), str(uuid4()))
    assert v["guide_view"]["walking"]["state"] == state
    legacy = PlanDraft(walking_allowed=False)
    before = legacy.model_dump()
    assert walking(legacy, text)["state"] == ("DECLINED" if state == "DECLINED" else "UNKNOWN")
    assert legacy.model_dump() == before


def test_optional_walking_and_independent_context_failures(normal):
    s, _ = normal
    v = synthetic(s)
    _, state = s.load(v["session_id"])
    data = payload(s.db, s.scope, v["session_id"], state["planning"])
    raw = proposal(data)
    good = raw["proposals"][0]
    good["walking_requirement"] = "OPTIONAL"
    good["reason"] = "步行只作为待选择建议，尚未确认"
    good["budget_lines"] = [
        line(
            "food", "FOOD", "PER_PERSON_DAY", 80, 100, conditions=["实际餐饮价格未知，金额仅为预留"]
        ).model_dump()
    ]
    bad = deepcopy(good)
    bad["walking_requirement"] = "REQUIRED"
    raw["proposals"].append(bad)
    out = validate(raw, data)
    assert out["accepted_count"] == out["rejected_count"] == 1
    assert out["decisions"][1]["field"] == "walking_requirement"
    data.update(walking_allowed=False, walking_preference="DECLINED")
    assert validate(raw, data)["accepted_count"] == 0
    data.update(walking_allowed=None, walking_preference="UNKNOWN")
    for change, reason in [
        ("quantity", "GUIDE_QUANTITY_FACTOR"),
        ("people", "GUIDE_BUDGET_CONTEXT_CONFLICT"),
    ]:
        raw = proposal(data)
        bad = line("food", "FOOD", "PER_PERSON_DAY", 80, 100).model_dump()
        if change == "quantity":
            bad["quantity"] = 2
        else:
            bad["conditions"] = ["按3人预留"]
        raw["proposals"][0]["budget_lines"] = [bad]
        assert validate(raw, data)["decisions"][0]["reason"] == reason


normal = normal_fixture
