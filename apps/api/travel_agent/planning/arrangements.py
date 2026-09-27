"""V2: program-owned fixed constraints and independently checked model proposals."""

from copy import deepcopy
import re
from typing import Any
from pydantic import ValidationError
from travel_agent.preview.projection import fingerprint, safe_text
from .flow_models import Arrangement, GroundedActivity

VERSION = "locked-arrangement-2.2"


def envelope_schema() -> dict[str, Any]:
    # Transport validation only; complete per-item schemas are checked below.
    return dict(
        type="object",
        additionalProperties=False,
        required=["protocol_version", "proposals"],
        properties=dict(
            protocol_version={"const": 2},
            proposals=dict(type="array", minItems=1, maxItems=3, items={}),
            grounded_activities=dict(type="array", maxItems=12, items={}),
        ),
    )


def _safety(value: Any) -> None:
    if isinstance(value, str):
        try:
            safe_text(value, 2000)
        except ValueError:
            raise ValueError("PLANNING_UNSAFE_RESPONSE") from None
    elif isinstance(value, dict):
        for k, v in value.items():
            _safety(k)
            _safety(v)
    elif isinstance(value, list):
        for v in value:
            _safety(v)


class Rejected(ValueError):
    def __init__(self, reason: str, field: str, expected: str = "VALID", actual: str = "INVALID"):
        super().__init__(reason)
        self.reason, self.field, self.expected, self.actual = reason, field, expected, actual


def _check(p: dict[str, Any], data: dict[str, Any]) -> None:
    allowed = {a["activity_id"]: a for a in data["activities"]}
    ids = [a["activity_id"] for a in p["activities"]]
    if (
        len(ids) != len(set(ids))
        or not set(ids) <= allowed.keys()
        or not set(p["citation_ids"]) <= set(data["allowed_citation_ids"])
    ):
        raise Rejected("PLANNING_UNKNOWN_REFERENCE", "activities")
    if data.get("spatial_intent") == "CITY_CORE" and any(
        allowed[i].get("spatial_status")
        not in ({"MATCH", "UNKNOWN"} if data.get("discovery_mode") else {"MATCH"})
        for i in ids
    ):
        raise Rejected("PLANNING_SCOPE_UNVERIFIED", "activities", "MATCH", "UNKNOWN")
    needed = {
        e
        for i in ids
        for e in [*allowed[i].get("evidence_ids", []), *allowed[i].get("discovery_ids", [])]
    }
    if not needed <= set(p["citation_ids"]):
        raise Rejected("PLANNING_UNKNOWN_REFERENCE", "citation_ids")
    days = [a["day"] for a in p["activities"]]
    if days != sorted(days) or days[0] != data["first_day"]:
        raise Rejected("PLANNING_INVALID_TIME", "activities.day")
    for i, a in allowed.items():
        if a.get("locked_start") and (
            i not in ids
            or next(x for x in p["activities"] if x["activity_id"] == i)["day"] != a["day"]
        ):
            raise Rejected("PLANNING_LOCKED_CONSTRAINT", "activities.day")

    def minutes(t: str) -> int:
        h, m = map(int, t.split(":"))
        return h * 60 + m

    end: int | None = None
    previous_day = None
    for a in p["activities"]:
        if a["stay_min"] > a["stay_max"] or (data.get("days") and a["day"] > data["days"]):
            raise Rejected("PLANNING_INVALID_TIME", "activities.stay_max")
        locked = allowed[a["activity_id"]].get("locked_start")
        if a["day"] != previous_day:
            end = (
                minutes(data["first_start"])
                if a["day"] == data["first_day"] and data.get("first_start")
                else None
            )
        if locked:
            if end is not None and end > minutes(locked):
                raise Rejected("PLANNING_LOCKED_CONSTRAINT", "activities.locked_start")
            end = minutes(locked)
        if end is not None:
            end += a["stay_min"]
            deadline = data.get("return_deadline") or data.get("activity_end")
            if deadline and len(deadline) == 5:
                bound = minutes(deadline)
                if (
                    data.get("first_start")
                    and bound <= minutes(data["first_start"])
                    and data.get("activity_end") == deadline
                ):
                    bound += 1440
                if end > bound:
                    raise Rejected("PLANNING_LOCKED_CONSTRAINT", "return_deadline")
            end += a["rest_minutes"]
        previous_day = a["day"]
    proposed = p.get("unresolved_suggestions") or {}
    if data.get("first_start") and proposed.get("first_start"):
        raise Rejected("PLANNING_LOCKED_ANCHOR", "unresolved_suggestions.first_start")
    mode = proposed.get("transport")
    if mode and data["transport"] != "UNKNOWN":
        raise Rejected(
            "PLANNING_LOCKED_TRANSPORT", "unresolved_suggestions.transport", data["transport"], mode
        )
    if (mode == "SELF_DRIVE" and data["driving"] == "NO") or (
        mode == "LOCAL_SERVICE" and data["charter"] == "NO"
    ):
        raise Rejected("PLANNING_LOCKED_TRANSPORT", "unresolved_suggestions.transport")
    texts = [p["title"], p["reason"], *p["assumptions"], *p["unknowns"], *p["impacts"]]
    for value in texts:
        if data.get("discovery_mode"):
            for clause in re.split(r"[。；;，,]", value):
                # A missing opening time is a gap, not an asserted opening time.
                # Match assertions, never exempt an entire mixed clause as 'unknown'.
                if re.search(
                    r"建于|始建|历史悠久|展出(?:精美|珍贵|了|有)|正在展出|馆藏(?:丰富|精美|珍贵|包括|包含)|特色(?:是|为)|以.{1,12}闻名|开放时间\s*(?:为|是|[:：]|\d)|门票(?:为|是|免费)",
                    clause,
                ):
                    raise Rejected("PLANNING_UNSUPPORTED_FACT", "text")
        factual = re.sub(r"(?:不|无法|不能|并非|不作).{0,2}保证", "", value)
        if re.search(
            r"保证|已预订|已核实|\d+\s*(?:元|公里|km)|(?:车程|公交|驾车|接驳).{0,8}\d+\s*分钟",
            factual,
            re.I,
        ):
            raise Rejected("PLANNING_UNSUPPORTED_FACT", "text")
        # Negative constraints are allowed; affirmative driving/service instructions are not.
        for clause in re.split(r"[，。；;]", value):
            stripped = re.sub(
                r"(?:不建议|不安排|不采用|不需要|不应|不|无需|禁止|避免|拒绝).{0,3}(?:自驾|驾车|租车|开车|包车)",
                "",
                clause,
            )
            driving = bool(
                re.search(r"自驾|驾车|租车|开车|drive|driving|rental car", stripped, re.I)
            )
            charter = bool(re.search(r"包车|charter", stripped, re.I))
            if (
                driving
                and (data["transport"] in {"PUBLIC_TRANSIT", "WALKING"} or data["driving"] == "NO")
            ) or (
                charter
                and (data["transport"] in {"PUBLIC_TRANSIT", "WALKING"} or data["charter"] == "NO")
            ):
                raise Rejected(
                    "PLANNING_LOCKED_TRANSPORT",
                    "text",
                    data["transport"],
                    "SELF_DRIVE" if driving else "LOCAL_SERVICE",
                )
            if data.get("first_start"):
                for t in re.findall(r"(?:首项|第一个项目|开始|出发).{0,5}(\d{1,2}:\d{2})", clause):
                    if t.zfill(5) != data["first_start"]:
                        raise Rejected("PLANNING_LOCKED_ANCHOR", "text")


def validate_arrangements(raw: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    from travel_agent.providers.llm import validate_structured

    validate_structured(raw, envelope_schema())
    _safety(raw)
    input_hash = fingerprint(data)
    data = deepcopy(data)
    refs = {r["claim_id"]: r for r in data.get("references", [])}
    catalog = []
    bad_keys = set()
    mapping = {}
    entries = raw.get("grounded_activities", [])
    keys = [e.get("candidate_key") for e in entries if isinstance(e, dict)]
    for e in entries:
        try:
            g = GroundedActivity.model_validate(e)
            if (
                keys.count(g.candidate_key) != 1
                or data["activities"]
                or not set(g.evidence_ids) <= refs.keys()
            ):
                raise ValueError("INVALID_CATALOG")
            from .materials import candidate_from_name

            a = candidate_from_name(
                g.place_name,
                [refs[i] for i in g.evidence_ids],
                data["destination"],
                data.get("spatial_intent", "UNDECIDED"),
            )
            catalog.append(a.model_dump())
            mapping[g.candidate_key] = a.activity_id
        except ValueError:
            if isinstance(e, dict) and isinstance(e.get("candidate_key"), str):
                bad_keys.add(e["candidate_key"])
    data["activities"] += catalog
    accepted = []
    decisions = []
    digest = input_hash
    for index, item in enumerate(raw["proposals"]):
        pid = f"proposal-{digest[:16]}-{index + 1}"
        try:
            if isinstance(item, dict) and ("transport" in item or "first_start" in item):
                field = "transport" if "transport" in item else "first_start"
                actual = item.get(field)
                raise Rejected(
                    "PLANNING_LOCKED_TRANSPORT"
                    if "transport" in item
                    else "PLANNING_LOCKED_ANCHOR",
                    field,
                    data["transport"] if field == "transport" else "PROGRAM_LOCKED",
                    actual
                    if isinstance(actual, str)
                    and actual
                    in {"UNKNOWN", "PUBLIC_TRANSIT", "SELF_DRIVE", "LOCAL_SERVICE", "WALKING"}
                    else "FORBIDDEN_FIELD",
                )
            p = Arrangement.model_validate(item).model_dump()
            for a in p["activities"]:
                if a["activity_id"] in bad_keys:
                    raise Rejected("PLANNING_UNKNOWN_REFERENCE", "activities")
                a["activity_id"] = mapping.get(a["activity_id"], a["activity_id"])
            _check(p, data)
            p.update(
                proposal_id=pid,
                first_start=data.get("first_start"),
                transport=data["transport"],
                fixed_origin="PROGRAM_INPUT",
            )
            accepted.append(p)
            decisions.append(
                dict(proposal_id=pid, status="ACCEPTED", reason="CONSTRAINTS_SUPPORTED", field=None)
            )
        except ValidationError as exc:
            loc = exc.errors(include_input=False)[0]["loc"]
            known = {
                "activities",
                "day",
                "stay_min",
                "stay_max",
                "rest_minutes",
                "citation_ids",
                "title",
                "reason",
                "assumptions",
                "unknowns",
                "impacts",
                "unresolved_suggestions",
            }
            path = ".".join(str(x) if isinstance(x, int) or x in known else "field" for x in loc)
            decisions.append(
                dict(
                    proposal_id=pid,
                    status="REJECTED",
                    reason="PLANNING_PROPOSAL_SCHEMA",
                    field=path,
                    expected="SCHEMA",
                    actual="INVALID",
                )
            )
        except Rejected as exc:
            decisions.append(
                dict(
                    proposal_id=pid,
                    status="REJECTED",
                    reason=exc.reason,
                    field=exc.field,
                    expected=exc.expected,
                    actual=exc.actual,
                )
            )
    return dict(
        protocol_version=2,
        rule_version=VERSION,
        input_hash=input_hash,
        proposals=accepted,
        decisions=decisions,
        accepted_count=len(accepted),
        rejected_count=len(decisions) - len(accepted),
        generated_count=len(decisions),
        activity_catalog=catalog,
        reason=None if accepted else "PLANNING_ALL_REJECTED",
    )
