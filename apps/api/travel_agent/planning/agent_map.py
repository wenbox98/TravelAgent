"""Authenticated local business-tool bridge; the server keeps temporary Amap returns."""

import hmac
import http.client
import json
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from pydantic import Field
from travel_agent.preview.models import StrictModel
from travel_agent.persistence.database import Database
from .flow import PlanningService
from .workbench import DailyBudget


class AgentMapAction(StrictModel):
    task_id: str = Field(pattern=r"^automatic-[a-f0-9]{32}$")
    leg_id: str = Field(min_length=1, max_length=170)
    expected_revision: int = Field(ge=0)


class AgentMapResult(StrictModel):
    status: Literal[
        "PUBLIC_PLACE_NOT_RESOLVED",
        "PUBLIC_PLACE_CONFIRMATION_REQUIRED",
        "MAP_REFERENCE_READY",
        "MAP_REFERENCE_UNAVAILABLE",
    ]
    executed: bool
    needs_confirmation: bool
    feasibility: Literal["UNVERIFIED"] = "UNVERIFIED"


def execute(service: Any, sid: str, body: AgentMapAction, key: str) -> dict[str, Any]:
    from .critical_map import view, binding
    from .automatic import save
    from .models import MapAction

    if not 8 <= len(key) <= 100:
        raise ValueError("INVALID_INPUT")

    with Database(service.database) as db, db.transaction():
        row, state = PlanningService(db, service.scope).load(sid)
        p = state["planning"]
        budget = DailyBudget(db, p["operation_grant"])
        budget.check_trip(service.scope, sid)
        budget.task("MAP")
        if p.get("automatic_task_id") != body.task_id or row["revision"] != body.expected_revision:
            raise ValueError("STALE_PROPOSAL")
        task = db.connection.execute(
            "SELECT request_json FROM planning_tasks WHERE task_id=?", (body.task_id,)
        ).fetchone()
        from .agent_contract import CONSENTS

        if not task or json.loads(task[0])["consent"] not in CONSENTS:
            raise ValueError("OPERATION_NOT_AUTHORIZED")
        status = view(db, service.scope, sid, p)
        if not status["configured"]:
            raise ValueError("MAP_NOT_CONFIGURED")
        pair = next((v for v in status["pairs"] if v["leg_id"] == body.leg_id), None)
        if not status["ready"] or not pair:
            raise ValueError("KEY_LEG_INPUT_REQUIRED")
        previous = p.get("agent_map_selection")
        if previous and previous != pair["leg_id"]:
            raise ValueError("AGENT_MAP_SINGLE_LEG_ONLY")
        p["agent_map_selection"] = pair["leg_id"]
        p["critical_map_task"] = dict(**pair, draft_hash=binding(p), grant_id=p["operation_grant"])
        db.connection.execute(
            "UPDATE research_continuations SET gate_json=json_set(gate_json,'$.critical_leg',json(?)) WHERE continuation_id=?",
            (json.dumps(p["critical_map_task"]), p["operation_grant"]),
        )
        save(db, sid, state, bump=False)
    maps = service.get(sid)
    places = {v["place_id"]: v for v in maps["places"]}
    for index, pid in enumerate(pair["place_ids"]):
        if places.get(pid, {}).get("confirmed"):
            continue
        if not places.get(pid, {}).get("candidates"):
            maps = service.mutate(
                MapAction(
                    action="resolve",
                    session_id=sid,
                    expected_revision=maps["revision"],
                    expected_preview_revision=maps["preview_revision"],
                    place_id=pid,
                    send_confirmed=True,
                ),
                key + "-place-" + str(index),
                _auto_confirm=False,
            )
            places = {v["place_id"]: v for v in maps["places"]}
        if not places.get(pid, {}).get("candidates"):
            return dict(status="PUBLIC_PLACE_NOT_RESOLVED", executed=True, needs_confirmation=True)
    if any(not places.get(pid, {}).get("confirmed") for pid in pair["place_ids"]):
        return dict(
            status="PUBLIC_PLACE_CONFIRMATION_REQUIRED", executed=True, needs_confirmation=True
        )
    maps = service.mutate(
        MapAction(
            action="route",
            session_id=sid,
            expected_revision=maps["revision"],
            expected_preview_revision=maps["preview_revision"],
            leg_id=pair["leg_id"],
            send_confirmed=True,
        ),
        key + "-route",
        _auto_confirm=False,
    )
    leg = next((v for v in maps["legs"] if v["leg_id"] == pair["leg_id"]), None)
    # The supervisor receives success/state only, not coordinates, providers' text or raw map returns.
    return dict(
        status="MAP_REFERENCE_READY"
        if leg and leg["status"] == "OK"
        else "MAP_REFERENCE_UNAVAILABLE",
        executed=True,
        needs_confirmation=False,
        feasibility="UNVERIFIED",
    )


def invoke(
    database: Path, sid: str, tid: str, revision: int, leg_id: str, key: str
) -> dict[str, Any]:
    from travel_agent.preview.local_entry import entry_proof
    import os

    port = int(os.environ.get("TRAVEL_PREVIEW_PORT", "8768"))
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    auth = (database.parent / "preview-auth.key").read_bytes()
    try:
        connection.request(
            "POST", "/local-entry", headers={"X-Local-Entry-Proof": entry_proof(auth)}
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("AGENT_LOCAL_TOOL_UNAVAILABLE")
        target = urlsplit(json.loads(response.read(2048))["entry_url"])
        if target.netloc != f"127.0.0.1:{port}" or target.path != "/bootstrap":
            raise ValueError("AGENT_LOCAL_TOOL_UNAVAILABLE")
        connection.request("GET", target.path + "?" + target.query)
        response = connection.getresponse()
        response.read()
        cookie = (response.getheader("Set-Cookie") or "").split(";", 1)[0]
        if response.status != 303 or not cookie:
            raise ValueError("AGENT_LOCAL_TOOL_UNAVAILABLE")
        headers = {
            "Cookie": cookie,
            "Origin": f"http://127.0.0.1:{port}",
            "Content-Type": "application/json",
            "X-CSRF-Token": hmac.digest(auth, b"preview-csrf", "sha256").hex(),
            "Idempotency-Key": key,
        }
        connection.request(
            "POST",
            "/api/v1/preview/agent-map/" + sid,
            json.dumps(dict(task_id=tid, leg_id=leg_id, expected_revision=revision)),
            headers,
        )
        response = connection.getresponse()
        raw = response.read(8192)
        if response.status != 200:
            raise ValueError("AGENT_MAP_NOT_COMPLETED")
        return dict(json.loads(raw))
    finally:
        connection.close()
