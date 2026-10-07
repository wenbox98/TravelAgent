"""Derived source-object context. Never converts membership into place features."""

import re
from typing import Any
from travel_agent.preview.projection import fingerprint, safe_text

VERSION = "scoped-context-1"
USE_RULE = "scoped-use-1.1"
REVIEWED = {"WORK_REVIEWED", "MODEL_CONTEXT_REVIEWED", "LOCAL_REVALIDATION"}
LIMIT = "仅为来源整体背景与组合线索，不证明每站特色、行政归属、亲历或当前人流/开放/可行性。"


def anchor(row: dict[str, Any]) -> tuple[str, str, str] | None:
    obj = row.get("route_association") or {}
    if (
        row.get("review_status") not in REVIEWED
        or not row.get("source_version")
        or obj.get("source_id") != row.get("source_id")
        or not obj.get("object_locator")
        or not obj.get("object_quote")
        or not row.get("locator")
    ):
        return None
    if row["locator"].split(":chars:")[0] != obj["object_locator"].split(":chars:")[0]:
        return None
    return row["source_id"], row["source_version"], obj["object_locator"]


def ids(activity: dict[str, Any]) -> set[str]:
    return set(
        [
            *activity.get("evidence_ids", []),
            *activity.get("discovery_ids", []),
            *activity.get("knowledge_citation_ids", []),
            *[r["card_id"] for r in activity.get("knowledge_refs", [])],
        ]
    )


def same_document(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return bool(
        a.get("source_id")
        and a.get("source_version")
        and a.get("locator")
        and all(a.get(k) == b.get(k) for k in ("source_id", "source_version"))
        and a["locator"].split(":chars:")[0] == b.get("locator", "").split(":chars:")[0]
    )


def derive(activities: list[dict[str, Any]], refs: list[dict[str, Any]]) -> dict[str, Any]:
    from .materials import activities as route_activities

    by_id = {r["claim_id"]: r for r in refs}
    routes = [r for r in refs if r.get("topic") == "ROUTE" and anchor(r)]
    rows, supplements = [], []
    selected_sources = {
        r.get("source_id") for a in activities for i in ids(a) if (r := by_id.get(i))
    }
    for e in refs:
        if e.get("topic") != "EXPERIENCE" or e.get("review_status") not in REVIEWED:
            continue
        obj = anchor(e)
        linked: dict[str, str] = {}
        basis = []
        for route in routes:
            if obj is None or anchor(route) != obj:
                continue
            members = {a.name for a in route_activities([route], "")}
            for a in activities:
                bound = [by_id[i] for i in ids(a) if i in by_id]
                if a["name"] in members and any(same_document(r, route) for r in bound):
                    linked[a["activity_id"]] = a["name"]
                    basis.append(
                        dict(
                            citation_id=route["claim_id"],
                            locator=route["locator"],
                            object_locator=obj[2],
                            kind="REVIEWED_OBJECT_AND_EXPLICIT_MEMBERS",
                        )
                    )
        scope = "GROUP_BACKGROUND"
        if not linked:
            # Exact reviewed object name or an explicit subject predicate, not substring matching.
            subject = re.sub(
                r"^[📍\s]+|[。\s]+$", "", (e.get("route_association") or {}).get("object_quote", "")
            )
            for a in activities:
                bound = [by_id[i] for i in ids(a) if i in by_id]
                explicit = subject == a["name"] or bool(
                    re.match(
                        re.escape(a["name"]) + r"(?:适合|可以|不适合|不推荐|需要|的体验)", e["text"]
                    )
                )
                if explicit and any(same_document(r, e) for r in bound):
                    linked[a["activity_id"]] = a["name"]
            if linked:
                scope = "DIRECT_PLACE"
                basis = [
                    dict(
                        citation_id=e["claim_id"],
                        locator=e["locator"],
                        object_locator=obj[2] if obj else e["locator"],
                        kind="EXPLICIT_SUBJECT",
                    )
                ]
        if not linked:
            if e.get("source_id") in selected_sources:
                supplements.append(
                    dict(
                        citation_id=e["claim_id"],
                        text=e["text"],
                        conditions=e["conditions"],
                        reference_kind=e["reference_kind"],
                        scope="UNASSOCIATED",
                        reason="没有可证明的对象与当前项目关系，不作地点特色依据。",
                    )
                )
            continue
        basis = list({fingerprint(b): b for b in basis}.values())
        identity = dict(
            rule_version=VERSION,
            citation_id=e["claim_id"],
            source_id=e["source_id"],
            source_version=e["source_version"],
            object_locator=obj[2] if obj else e["locator"],
            scope=scope,
            basis=basis,
        )
        row = dict(
            **identity,
            context_id="context-" + fingerprint(identity)[:24],
            activity_ids=sorted(linked),
            text=safe_text(e["text"], 1500),
            conditions=e["conditions"],
            subject=(e.get("route_association") or {}).get(
                "object_quote", next(iter(linked.values()))
            ),
            reference_kind=e["reference_kind"],
            review_status=e["review_status"],
            locator=e["locator"],
            activity_names=[linked[i] for i in sorted(linked)],
            limitation=LIMIT,
            use="COMPARE_OR_PACE_NOT_NEW_FACTS",
        )
        rows.append(row)
    return dict(
        rule_version=VERSION,
        backgrounds=rows,
        supplements=supplements,
        source_count=len({r["source_id"] for r in rows}),
        background_available=any(r["scope"] == "GROUP_BACKGROUND" for r in rows),
    )


def view(
    activities: list[dict[str, Any]], refs: list[dict[str, Any]], uses: list[Any]
) -> dict[str, Any]:
    result = derive(activities, refs)
    by_id = {c["context_id"]: c for c in result["backgrounds"]}
    valid = []
    for u in uses:
        row = u.model_dump() if hasattr(u, "model_dump") else u
        c = by_id.get(row["context_id"])
        if c and set(row["activity_ids"]) <= set(c["activity_ids"]):
            valid.append(dict(row, origin="AI_PROPOSED"))
    result["uses"] = valid
    return result


def attach_context(data: dict[str, Any], source_lengths: dict[str, int]) -> None:
    """Charge repeated context text too; never truncate away conditions to fit."""
    rows = derive(data["activities"], data["references"])["backgrounds"]
    lengths = dict(source_lengths)
    for row in rows:
        source = row["source_id"]
        lengths[source] = (
            lengths.get(source, 0)
            + len(row["text"])
            + len(row["subject"])
            + sum(map(len, row["conditions"]))
        )
    if len(lengths) > 2 or any(n > 6000 for n in lengths.values()):
        raise ValueError("PLANNING_CONTEXT_INPUT_LIMIT")
    data["scoped_context"] = rows


def scope_assertion(text: str) -> bool:
    """Recognize narrow uncertainty disclaimers, not arbitrary clauses containing 不."""
    for clause in re.split(r"[，,；;。！？!?]|但是|然而|不过|而是|但|却", text):
        clause = clause.strip()
        if re.fullmatch(
            r"(?:不|不能|不可|不得|无法|尚不能|不应)(?:据此)?(?:推断|证明|确认|保证|认定|声称)"
            r"(?:(?:每(?:一)?(?:站|处)|各(?:站|处)|具体地点|行政归属|实际人流|当前人流|人少|特色|氛围|关系|开放|可行性)(?:的)?|或|和|与|及)+",
            clause,
        ):
            continue
        if re.search(
            r"(?:每(?:一)?(?:站|处|个)|各(?:站|处|点)).{0,8}(?:都有|均有|都是|特色|氛围)|分别.{0,8}(?:特色|氛围)|属于|位于|坐落|必有|人少|人潮|馆藏|展品",
            clause,
        ):
            return True
    return False


def validate_uses(proposal: dict[str, Any], data: dict[str, Any]) -> None:
    from .arrangements import Rejected, _check

    by_id = {c["context_id"]: c for c in data.get("scoped_context", [])}
    selected = {a["activity_id"] for a in proposal["activities"]}
    seen = set()
    for use in proposal.get("context_uses", []):
        c = by_id.get(use["context_id"])
        targets = set(use["activity_ids"])
        if (
            not c
            or use["context_id"] in seen
            or len(targets) != len(use["activity_ids"])
            or not targets <= selected
            or not targets <= set(c["activity_ids"])
            or c["citation_id"] not in proposal["citation_ids"]
        ):
            raise Rejected("GUIDE_CONTEXT_REFERENCE", "context_uses")
        seen.add(use["context_id"])
        text = use["reason"]
        if scope_assertion(text):
            raise Rejected("GUIDE_CONTEXT_SCOPE", "context_uses.reason")
        # Existing fact, transport and fixed-constraint checks apply to rationale too.
        _check(dict(proposal, assumptions=[text]), data)
