"""Normal knowledge-first API entry and local-only history reuse, authored fixtures."""

from uuid import uuid4
from copy import deepcopy
import json
import pytest

from fastapi.testclient import TestClient
from travel_agent.main import create_app
from travel_agent.settings import Settings
from travel_agent.preview.api import PreviewConfig
from test_daily_workbench import normal as normal_fixture
from test_scoped_context import scoped as scoped_fixture
from test_knowledge_library import organize
from test_planning_flow import act

normal = normal_fixture
scoped = scoped_fixture


def client_for(s):
    config = PreviewConfig(
        s.db.path,
        "owner",
        "CACHED_PRIVATE_PREVIEW",
        b"a" * 32,
        product_flow=True,
        daily_workbench=True,
    )
    client = TestClient(
        create_app(Settings.load(preferred_port=18768), preview=config),
        base_url="http://127.0.0.1:18768",
    )
    client.get("/bootstrap?ticket=" + config.ticket)
    client.headers.update(
        {
            "Origin": "http://127.0.0.1:18768",
            "X-CSRF-Token": client.get("/api/v1/preview").json()["csrf_token"],
        }
    )
    return client


def post(client, url, body):
    r = client.post(url, json=body, headers={"Idempotency-Key": str(uuid4())})
    assert r.status_code == 200, r.text
    return r.json()


def create(client, destination="合成青谷", **kw):
    # Exactly the ordinary PlanningPanel.create request, never bypass knowledge_first.
    return post(
        client,
        "/api/v1/preview/planning",
        dict(
            dict(
                destination=destination,
                request="",
                travel_kind="CITY",
                demo=None,
                validation_trip=False,
                knowledge_first=True,
            ),
            **kw,
        ),
    )


def test_default_page_create_exposes_existing_history_without_cards(normal):
    s, old = normal
    with client_for(s) as client:
        v = create(client)
        assert v["operation"]["status"] == "NOT_AUTHORIZED"
        assert not v["draft"]["activities"]
        assert any(o["session_id"] == old["session_id"] for o in v["reuse_options"])


def test_default_page_reuse_can_adopt_without_knowledge_binding(normal):
    s, old = normal
    from travel_agent.planning.workbench import reuse_options

    with client_for(s) as client:
        v = create(client)
        _, state = s.load(v["session_id"])
        # Exercise the second baseline defect even when the entry is hidden.
        option = next(
            o
            for o in reuse_options(s.db, s.scope, v["session_id"], state["planning"])
            if o["session_id"] == old["session_id"]
        )
        url = "/api/v1/preview/planning/" + v["session_id"]
        v = post(
            client,
            url,
            dict(
                action="reuse_activities",
                expected_revision=v["revision"],
                reuse_key=option["key"],
                activity_ids=[a["activity_id"] for a in option["activities"]],
            ),
        )
        v = post(client, url, dict(action="adopt", expected_revision=v["revision"]))
        assert v["adopted"]["activities"]


def change(client, v, action, **kw):
    return post(
        client,
        "/api/v1/preview/planning/" + v["session_id"],
        dict(action=action, expected_revision=v["revision"], **kw),
    )


def select(client, v, option=None):
    o = option or v["reuse_options"][0]
    return change(
        client,
        v,
        "reuse_activities",
        reuse_key=o["key"],
        activity_ids=[a["activity_id"] for a in o["activities"]],
    )


def update_fixture(s, old, modify):
    _, state = s.load(old["session_id"])
    modify(state["planning"])
    s.db.connection.execute(
        "UPDATE preview_sessions SET state_json=? WHERE session_id=?",
        (json.dumps(state), old["session_id"]),
    )


@pytest.mark.parametrize(
    "cards,history", [(False, False), (False, True), (True, False), (True, True)]
)
def test_four_material_branches_via_default_api(normal, cards, history):
    s, old = normal
    if cards:
        organize(s, old)
    if not history:
        update_fixture(s, old, lambda p: p.update(adopted=None))
    with client_for(s) as client:
        v = create(client)
        library = post(
            client, "/api/v1/preview/knowledge", dict(action="search", destination=v["destination"])
        )["result"]
        assert bool(library["cards"]) == cards
        assert bool(v["reuse_options"]) == history
        assert v["local_materials"]["can_select"] and not v["operation"]["history"]
        if cards:
            c = library["cards"][0]
            selected = post(
                client,
                "/api/v1/preview/knowledge",
                dict(
                    action="attach",
                    session_id=v["session_id"],
                    expected_revision=v["revision"],
                    refs=[{k: c[k] for k in ("card_id", "version", "card_hash")}],
                ),
            )["result"]
            assert selected["proposal_preview_active"]
            canceled = change(client, selected, "cancel")
            assert canceled["draft"] == v["draft"] and canceled["local_materials"]["can_select"]


@pytest.mark.parametrize("trip_request", ["", "三天，公共交通", "市区一天，10点开始第一项"])
def test_local_preview_cancel_adopt_export_no_permit_no_old_constraints(normal, trip_request):
    s, old = normal

    def locked(p):
        for a in p["adopted"]["activities"]:
            a.update(day=7, locked=True, locked_start="15:00", timing_origin="AI_PROPOSED")

    update_fixture(s, old, locked)
    before = s.load(old["session_id"])[1]
    with client_for(s) as client:
        initial = create(client, request=trip_request)
        v = select(client, initial)
        assert v["proposal_preview_active"] and v["adopted"] is None
        assert not any(a["locked"] or a["locked_start"] for a in v["draft"]["activities"])
        assert all(a["day"] == 1 for a in v["draft"]["activities"])
        for k in ("days", "transport", "inputs", "trip_budget", "walking_allowed"):
            assert v["draft"][k] == initial["draft"][k]
        assert v["guide_view"]["local_reuse"] and v["job"] is None
        assert not v["research_available"] and not v["model_available"]
        v = change(client, v, "cancel")
        assert v["draft"] == initial["draft"] and v["reuse_options"]
        v = change(client, select(client, v), "adopt")
        assert not v["proposal_preview_active"]
        exported = client.get("/api/v1/preview/planning/" + v["session_id"] + "/guide-export")
        assert exported.status_code == 200 and "没有新模型生成" in exported.json()["markdown"]
        for operation in ("suggest", "research"):
            r = client.post(
                "/api/v1/preview/planning/" + v["session_id"],
                json=dict(action=operation, expected_revision=v["revision"]),
                headers={"Idempotency-Key": str(uuid4())},
            )
            assert r.status_code == 409
        assert s.load(old["session_id"])[1] == before
        assert (
            s.db.connection.execute("SELECT count(*) FROM continuation_operations").fetchone()[0]
            == 0
        )
        assert s.db.connection.execute("SELECT count(*) FROM preview_jobs").fetchone()[0] == 0


def test_development_material_filter_is_explicit_and_trip_local(normal):
    s, old = normal
    update_fixture(s, old, lambda p: p.update(validation_trip=True))
    with client_for(s) as client:
        v = create(client)
        assert not v["reuse_options"]
        v = change(client, v, "material_filter", include_test=True)
        assert v["reuse_options"][0]["test_input"]
        v = select(client, v)
        assert v["guide_view"]["test_input"]
        assert not create(client)["reuse_options"]


@pytest.mark.parametrize(
    "cause", ["destination", "kind", "account", "deleted", "withdrawn", "version"]
)
def test_history_filter_and_stale_selection_cannot_cross_source_boundaries(normal, cause):
    s, old = normal
    with client_for(s) as client:
        v = create(client)
        choice = v["reuse_options"][0]
        if cause in {"destination", "kind"}:
            update_fixture(
                s,
                old,
                lambda p: p.update(
                    **(
                        {"destination": "合成异城"}
                        if cause == "destination"
                        else {"travel_kind": "REGIONAL"}
                    )
                ),
            )
        elif cause == "account":
            s.db.connection.execute(
                "UPDATE preview_sessions SET account_scope='someone-else' WHERE session_id=?",
                (old["session_id"],),
            )
        elif cause == "deleted":
            s.db.connection.execute("UPDATE sources SET deleted_at=?", (s.db.stamp(),))
        elif cause == "withdrawn":
            for row in s.db.connection.execute("SELECT source_id FROM sources"):
                s.db.connection.execute(
                    "INSERT INTO knowledge_withdrawals VALUES(?,?,?)",
                    ("owner", row[0], s.db.stamp()),
                )
        else:
            s.db.connection.execute("UPDATE source_contents SET content_hash=?", ("0" * 64,))
        fresh = client.get("/api/v1/preview/planning/" + v["session_id"]).json()
        assert not fresh["reuse_options"]
        r = client.post(
            "/api/v1/preview/planning/" + v["session_id"],
            json=dict(
                action="reuse_activities",
                expected_revision=v["revision"],
                reuse_key=choice["key"],
                activity_ids=[a["activity_id"] for a in choice["activities"]],
            ),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert r.status_code == 409 and not s.get(v["session_id"])["draft"]["activities"]


def test_no_mixed_overwrite_or_lock_loss_and_card_versions_remain_checked(normal):
    s, old = normal
    cards = organize(s, old)
    from travel_agent.knowledge.store import binding, Library

    with client_for(s) as client:
        blank = create(client)
        v = select(client, blank)
        draft = deepcopy(v["draft"])
        draft["activities"][0]["locked"] = True
        v = change(client, v, "save", draft=draft)
        before = s.load(v["session_id"])[1]
        r = client.post(
            "/api/v1/preview/knowledge",
            json=dict(
                action="attach",
                session_id=v["session_id"],
                expected_revision=v["revision"],
                refs=[binding(cards[0])],
            ),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert r.status_code == 409 and s.load(v["session_id"])[1] == before
        Library(s.db, s.scope).remove([binding(cards[0])])
        v = change(client, v, "cancel")
        assert not v["draft"]["activities"]
        r = client.post(
            "/api/v1/preview/knowledge",
            json=dict(
                action="attach",
                session_id=v["session_id"],
                expected_revision=v["revision"],
                refs=[binding(cards[0])],
            ),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert r.status_code == 409


def test_scoped_background_and_independent_process_restore_without_source_promotion(scoped):
    s, old = scoped
    old = act(s, old, "adopt")
    with client_for(s) as client:
        v = create(client, request="两天轻松玩")
        v = select(client, v)
        context = v["guide_view"]["context"]
        assert context["source_count"] == 1 and len(context["backgrounds"]) == 1
        assert "作者未亲历" in context["backgrounds"][0]["text"]
        assert all(
            m["level"] == "ROUTE_CONTEXT" for m in v["guide_view"]["assessment"]["materials"]
        )
        v = change(client, v, "adopt")
        sid = v["session_id"]
        expected = client.get("/api/v1/preview/planning/" + sid + "/guide-export").json()[
            "markdown"
        ]
        import subprocess
        import sys

        code = """
import sys,socket,json
sys.path.insert(0,'apps/api')
def deny(*a,**k):raise AssertionError('NETWORK_DENIED')
socket.getaddrinfo=socket.create_connection=socket.socket.connect=socket.socket.connect_ex=deny
from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
from travel_agent.planning.guide_view import export
with Database(sys.argv[1]) as db:
 v=PlanningService(db,'owner').get(sys.argv[2])
 assert v['adopted']['activities'] and not v['operation']['history']
 print(json.dumps(export(db,'owner',sys.argv[2])['markdown'],ensure_ascii=True))
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(s.db.path), sid], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == expected


def test_closed_permit_does_not_block_local_actions_or_enable_dispatch(normal):
    s, _ = normal
    with client_for(s) as client:
        v = create(client)
        # Nonzero permission exists only in this authored isolated fixture.
        v = change(
            client, v, "authorize", authorization=dict(confirm=True, tasks=["PLANNING"], model=1)
        )
        v = change(client, v, "revoke_authorization")
        v = select(client, v)
        v = change(client, v, "cancel")
        v = change(client, select(client, v), "adopt")
        assert v["operation"]["status"] == "CLOSED" and not v["model_available"]
        assert (
            client.get("/api/v1/preview/planning/" + v["session_id"] + "/guide-export").status_code
            == 200
        )
        assert (
            s.db.connection.execute("SELECT count(*) FROM continuation_operations").fetchone()[0]
            == 0
        )


def test_nested_combination_cancel_keeps_outer_material_bindings(normal):
    s, _ = normal
    with client_for(s) as client:
        initial = create(client)
        v = select(client, initial)
        selected = deepcopy(v["draft"])
        v = change(
            client,
            v,
            "preview_combination",
            activity_ids=[v["draft"]["activities"][0]["activity_id"]],
        )
        assert len(v["draft"]["activities"]) == 1
        v = change(client, v, "cancel")
        assert v["draft"] == selected and v["proposal_preview_active"]
        assert not s.load(v["session_id"])[1]["planning"]["knowledge_mode"]
        v = change(client, v, "cancel")
        assert v["draft"] == initial["draft"] and v["reuse_options"]


def test_withdraw_after_preview_blocks_adoption_keeps_preview_and_history(normal):
    s, old = normal
    with client_for(s) as client:
        v = select(client, create(client))
        before = deepcopy(v["draft"])
        for row in s.db.connection.execute("SELECT source_id FROM sources"):
            s.db.connection.execute(
                "INSERT INTO knowledge_withdrawals VALUES(?,?,?)", ("owner", row[0], s.db.stamp())
            )
        r = client.post(
            "/api/v1/preview/planning/" + v["session_id"],
            json=dict(action="adopt", expected_revision=v["revision"]),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert r.status_code == 409
        assert s.get(v["session_id"])["draft"] == before
        assert s.get(old["session_id"])["adopted"] == old["adopted"]


@pytest.mark.parametrize(
    "region,count,days",
    [("合成海城", 1, 1), ("合成海城", 2, 3), ("合成林城", 1, 5), ("合成林城", 2, 2)],
)
def test_other_destinations_same_names_counts_and_days(normal, region, count, days):
    s, old = normal
    update_fixture(s, old, lambda p: p.update(destination=region))
    for row in s.db.connection.execute("SELECT research_id,request_json FROM research_questions"):
        data = json.loads(row[1])
        data["destination"] = region
        s.db.connection.execute(
            "UPDATE research_questions SET request_json=? WHERE research_id=?",
            (json.dumps(data), row[0]),
        )
    with client_for(s) as client:
        v = create(client, destination=region, request=f"{days}天")
        o = v["reuse_options"][0]
        v = change(
            client,
            v,
            "reuse_activities",
            reuse_key=o["key"],
            activity_ids=[a["activity_id"] for a in o["activities"][:count]],
        )
        v = change(client, v, "adopt")
        assert len(v["adopted"]["activities"]) == count and v["adopted"]["days"] == days
        assert v["guide_view"]["assessment"]["coverage"]["missing_days"] == list(range(2, days + 1))
