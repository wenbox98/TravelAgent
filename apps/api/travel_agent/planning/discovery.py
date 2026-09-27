"""Trip-bound public mentions. No claim approval, geocoding or inference on reads."""

from copy import deepcopy
import json
import re
from typing import Any

from travel_agent.preview.projection import fingerprint
from travel_agent.research.canonical import canonicalize
from travel_agent.research.content_store import SourceContentStore
from travel_agent.research.model_input import outbound_blocks
from .flow_models import Activity, PlanDraft
from .private_budget import DISCOVERY_IDENTIFIER, REVISION_IDENTIFIER, PrivatePlanningBudget
from .spatial import classify

VERSION = "public-mention-1"
# Conservative route grammar, not a general named-entity recognizer. No city/POI list.
NAME = re.compile(
    r"(?:从|走到|再到|经|途经|到达|→|➡|->|^)(?P<name>[\u4e00-\u9fffA-Za-z0-9]{2,24}?(?:博物馆|美术馆|公园|广场|步行街|街|路))"
    r"(?=出发|[，,。；;～~\s→➡]|$)"
)
FLAGS = {
    "PRIVATE_OR_IDENTIFIER": r"住宅|住址|家里|我家|私宅|私密|门牌|\d+号(?!线)|\d+室|电话|姓名|联系人|身份证|微信",
    "UNSAFE_INSTRUCTION": r"https?://|www\.|忽略.{0,8}(?:指令|规则)|系统提示|提示词|system\s*:|执行代码|```|<script|curl\s",
    "FICTION_OR_EXAMPLE": r"虚构|虚拟地点|编造|小说|示例|假设有|不存在的",
    "ACCESS_RESTRICTION": r"关闭|闭园|封闭|无法进入|禁止|谢绝|限制进入|危险|不要去|不能去|不对外",
    "NEGATIVE_CONTEXT": r"不喜欢|不推荐|没去过|未去过|不值得",
    "HYPOTHETICAL": r"如果|假如|计划|打算|还未出发",
}
BLOCKING = set(FLAGS) - {"NEGATIVE_CONTEXT", "HYPOTHETICAL"}


def contents(db: Any, scope: str, sid: str, p: dict[str, Any]) -> list[dict[str, Any]]:
    from .workbench import daily, local_contents

    if daily(p):
        return local_contents(db, scope, sid, p)
    budget = PrivatePlanningBudget.for_trip(db, sid)
    gate = budget.check_trip(scope, sid)["gate"]
    if budget.identifier not in {DISCOVERY_IDENTIFIER, REVISION_IDENTIFIER} or not gate.get(
        "content_ids"
    ):
        raise ValueError("DISCOVERY_NOT_AUTHORIZED")
    job = db.connection.execute(
        "SELECT research_id FROM preview_jobs WHERE job_id=? AND session_id=? AND account_scope=?",
        (p.get("research_job_id"), sid, scope),
    ).fetchone()
    if not job or p.get("demo"):
        raise ValueError("DISCOVERY_SOURCE_UNAVAILABLE")
    question = db.connection.execute(
        "SELECT request_json FROM research_questions WHERE research_id=? AND account_scope=?",
        (job[0], scope),
    ).fetchone()
    if not question or json.loads(question[0]).get("destination") != p["destination"]:
        raise ValueError("DISCOVERY_SOURCE_UNAVAILABLE")
    eligible = db.connection.execute(
        "SELECT DISTINCT c.content_id,s.source_id FROM research_run_contents c "
        "JOIN research_runs r ON r.run_id=c.run_id "
        "JOIN research_questions q ON q.research_id=r.research_id "
        "JOIN source_contents s ON s.content_id=c.content_id "
        "WHERE r.research_id=? AND q.account_scope=? AND r.revision=q.current_revision",
        (job[0], scope),
    ).fetchall()
    result = []
    for row in eligible:
        if row[0] not in gate["content_ids"]:
            continue
        for content in SourceContentStore(db).load(row[1], scope, purge=False):
            if content["content_id"] == row[0]:
                result.append(content)
    return result


def identify(content: dict[str, Any], destination: str, intent: str) -> list[dict[str, Any]]:
    view = canonicalize(
        content["raw_text"], content["dom_text"], completeness=content["content_completeness"]
    )
    outbound = {b.block_index for b in outbound_blocks(view.blocks)}
    result = []
    # Include surrounding framing/restrictions, even when names occur on another line.
    flags = [code for code, pattern in FLAGS.items() if re.search(pattern, view.text, re.I)]
    for block in view.blocks:
        if block.text.startswith("#"):
            continue
        for match in NAME.finditer(block.text):
            name = match["name"]
            start, end = block.start + match.start("name"), block.start + match.end("name")
            binding = {k: content[k] for k in ("source_id", "content_id", "content_hash")}
            lid = "lead-" + fingerprint([VERSION, binding, start, end])[:24]
            parent = [b for b in view.blocks if abs(b.block_index - block.block_index) <= 1]
            blocked = sorted(set(flags) & BLOCKING)
            if any(b.block_index not in outbound for b in parent):
                blocked.append("FILTERED_CONTEXT")
            source_fit, bases = classify(
                name, [dict(claim_id=lid, text=b.text, conditions=[]) for b in parent], intent
            )
            result.append(
                dict(
                    lead_id=lid,
                    public_name=name,
                    **binding,
                    start=start,
                    end=end,
                    locator=block.locator.rsplit(":chars:", 1)[0] + f":chars:{start}-{end}",
                    parent_blocks=[
                        dict(block_index=b.block_index, start=b.start, end=b.end, text=b.text)
                        for b in parent
                    ],
                    method=VERSION,
                    mention_only=True,
                    claim_references=[],
                    context_flags=flags + ["AUTHOR_ROLE_UNVERIFIED"],
                    quarantined=bool(blocked),
                    quarantine_reasons=blocked,
                    destination=destination,
                    source_scope_status=source_fit,
                    spatial_status="MISMATCH" if source_fit == "MISMATCH" else "UNKNOWN",
                    spatial_basis=bases,
                    identity_status="UNKNOWN",
                    identity_origin="UNKNOWN",
                    scope_acceptance="UNDECIDED",
                    suitability="UNKNOWN",
                )
            )
    return list({r["public_name"]: r for r in result}.values())[:12]


def discover(db: Any, scope: str, sid: str, p: dict[str, Any]) -> list[dict[str, Any]]:
    draft = PlanDraft.model_validate(p["draft"])
    result = []
    for content in contents(db, scope, sid, p):
        leads = identify(content, p["destination"], draft.spatial.intent)
        refs = [
            dict(r)
            for r in db.connection.execute(
                "SELECT c.attempt_id,c.candidate_index,c.context_status,c.context_reason "
                "FROM extraction_candidates c JOIN extraction_attempts a ON a.attempt_id=c.attempt_id "
                "WHERE a.content_id=? AND a.content_hash=? ORDER BY a.rowid,c.candidate_index",
                (content["content_id"], content["content_hash"]),
            )
        ]
        for lead in leads:
            lead["claim_references"] = refs
        result.extend(leads)
    return result[:12]


def checked(db: Any, scope: str, sid: str, p: dict[str, Any]) -> dict[str, dict[str, Any]]:
    saved = p.get("discovery", {}).get("leads", [])
    if not saved:
        return {}
    current = {lead["lead_id"]: lead for lead in discover(db, scope, sid, p)}
    result = {}
    for lead in saved:
        actual = current.get(lead["lead_id"])
        if actual is None:
            raise ValueError("DISCOVERY_LINEAGE_UNAVAILABLE")
        for key in (
            "public_name",
            "source_id",
            "content_id",
            "content_hash",
            "start",
            "end",
            "locator",
            "method",
            "parent_blocks",
            "destination",
        ):
            if lead[key] != actual[key]:
                raise ValueError("DISCOVERY_LINEAGE_UNAVAILABLE")
        for key in ("identity_status", "identity_origin", "identity_revision", "scope_acceptance"):
            if key in lead:
                actual[key] = lead[key]
        result[lead["lead_id"]] = actual
    return result


def as_activity(lead: dict[str, Any]) -> Activity:
    if (
        lead["quarantined"]
        or lead["identity_status"] != "CHECKED"
        or lead["spatial_status"] == "MISMATCH"
    ):
        raise ValueError("DISCOVERY_IDENTITY_REQUIRED")
    return Activity(
        activity_id=lead["lead_id"],
        name=lead["public_name"],
        region=lead["destination"],
        discovery_ids=[lead["lead_id"]],
        provenance="SOURCE_MENTION",
        spatial_status=lead["spatial_status"],
        spatial_basis=lead["spatial_basis"],
        description="原文仅提及名称；身份曾匹配，范围与活动适用性未核实",
        reference_kinds=["PLACE_MENTION_ONLY"],
        conditions=["地点提及不证明作者亲历、推荐或当前开放；范围未定，暂作本次草案。"],
    )


def verify_activity(a: Activity, leads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    lead = leads.get(a.activity_id)
    if lead is None:
        raise ValueError("DISCOVERY_LINEAGE_UNAVAILABLE")
    expected = as_activity(lead)
    if any(
        getattr(a, k) != getattr(expected, k)
        for k in (
            "name",
            "region",
            "evidence_ids",
            "discovery_ids",
            "provenance",
            "conditions",
            "reference_kinds",
        )
    ):
        raise ValueError("DISCOVERY_LINEAGE_UNAVAILABLE")
    return lead


def model_references(
    db: Any, scope: str, sid: str, p: dict[str, Any], draft: PlanDraft
) -> list[dict[str, Any]]:
    leads = checked(db, scope, sid, p)
    refs = []
    sent: dict[str, int] = {}
    for activity in draft.activities:
        lead = verify_activity(activity, leads)
        policy = db.connection.execute(
            "SELECT policy_json FROM source_policies WHERE policy_id=(SELECT policy_id FROM source_contents WHERE content_id=?) ORDER BY version DESC LIMIT 1",
            (lead["content_id"],),
        ).fetchone()
        if not policy or not all(
            json.loads(policy[0]).get(k) for k in ("allow_inference", "allow_external_model")
        ):
            raise ValueError("DISCOVERY_POLICY_DENIED")
        context = "\n".join(b["text"] for b in lead["parent_blocks"])
        count = sent.get(lead["source_id"], 0) + len(context) + len(lead["public_name"])
        if count > 6000 or (lead["source_id"] not in sent and len(sent) >= 2):
            raise ValueError("DISCOVERY_INPUT_LIMIT")
        sent[lead["source_id"]] = count
        refs.append(
            dict(
                claim_id=lead["lead_id"],
                text=lead["public_name"],
                conditions=[context],
                reference_kind="PLACE_MENTION_ONLY",
                topic="PUBLIC_NAME",
            )
        )
    return deepcopy(refs)
