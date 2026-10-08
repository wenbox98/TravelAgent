"""A renewed local-owner entry never substitutes cookie, Origin or CSRF checks."""

from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from travel_agent.main import create_app
from travel_agent.settings import Settings
from travel_agent.persistence.database import Database
from travel_agent.preview.api import PreviewConfig
from travel_agent.preview.local_entry import EntryTickets, entry_proof


@pytest.fixture
def entry(tmp_path):
    path = tmp_path / "authored.sqlite3"
    with Database(path):
        pass
    config = PreviewConfig(
        path, "owner", "CACHED_PRIVATE_PREVIEW", b"a" * 32, product_flow=True, daily_workbench=True
    )
    client = TestClient(
        create_app(Settings.load(preferred_port=18768), preview=config),
        base_url="http://127.0.0.1:18768",
        client=("127.0.0.1", 53000),
    )
    with client:
        yield client, config


def test_owner_can_reopen_running_service_without_changing_session_boundary(entry):
    c, config = entry
    assert c.get("/api/v1/preview").status_code == 401
    expired = c.get(
        "/bootstrap?ticket=expired-synthetic",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert expired.status_code == 303 and expired.headers["location"] == "/"
    assert c.get("/api/v1/preview").status_code == 401
    renewed = c.post("/local-entry", headers={"X-Local-Entry-Proof": entry_proof(config.auth_key)})
    assert renewed.status_code == 200
    assert c.get("/api/v1/preview").status_code == 401
    assert c.get(renewed.json()["entry_url"], follow_redirects=False).status_code == 303
    assert c.get(renewed.json()["entry_url"]).status_code == 401
    index = c.get("/api/v1/preview").json()
    assert index["product_flow_available"]
    body = dict(request="我想去合成北域玩7天", knowledge_first=True)
    # Cookie alone must not authorize a write.
    assert c.post("/api/v1/preview/planning", json=body).status_code == 403
    headers = {
        "Origin": "http://127.0.0.1:18768",
        "X-CSRF-Token": index["csrf_token"],
        "Idempotency-Key": str(uuid4()),
    }
    result = c.post("/api/v1/preview/planning", json=body, headers=headers)
    assert result.status_code == 200
    trip = result.json()
    assert trip["destination"] == "合成北域" and trip["draft"]["days"] == 7
    assert (
        trip["draft"]["transport"] == "UNKNOWN" and trip["operation"]["status"] == "NOT_AUTHORIZED"
    )
    assert not trip["draft"]["activities"] and not trip["job"]
    assert (
        c.post("/api/v1/preview/planning", json=body, headers=headers).json()["session_id"]
        == trip["session_id"]
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Local-Entry-Proof": "bad"},
        {"Origin": "http://127.0.0.1:18768"},
        {"Origin": "https://evil.invalid"},
    ],
)
def test_browser_or_unproved_renewal_is_denied(entry, headers):
    c, config = entry
    if "Origin" in headers:
        headers = {**headers, "X-Local-Entry-Proof": entry_proof(config.auth_key)}
    assert c.post("/local-entry", headers=headers).status_code == 403
    assert c.get("/api/v1/preview").status_code == 401


def test_tickets_expire_are_single_use_and_bounded():
    now = [1.0]
    tickets = EntryTickets("initial", lambda: now[0])
    assert tickets.consume("initial") and not tickets.consume("initial")
    first = tickets.issue()
    now[0] += 301
    assert not tickets.consume(first)
    values = [tickets.issue() for _ in range(20)]
    assert len(tickets.pending) == 8 and not tickets.consume(values[0])
    assert tickets.consume(values[-1])


@pytest.mark.parametrize(
    "idea,expected",
    [
        ("我想去合成北域玩7天", "合成北域"),
        ("计划到虚构海城旅游三天，公共交通", "虚构海城"),
        ("合成山谷2天", "合成山谷"),
        ("虚构湖城", "虚构湖城"),
    ],
)
def test_explicit_region_without_place_specific_rules(idea, expected):
    from travel_agent.planning.intake import destination_from_idea

    assert destination_from_idea(idea) == expected


@pytest.mark.parametrize("idea", ["想轻松一点", "去哪里玩", "去合成湖城或者虚构山谷玩三天", ""])
def test_ambiguous_region_is_not_guessed(idea):
    from travel_agent.planning.intake import destination_from_idea

    with pytest.raises(ValueError, match="DESTINATION_REQUIRED"):
        destination_from_idea(idea)
