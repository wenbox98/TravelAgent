"""Source-labelled spatial intent, never a geocoder or an administrative boundary guess."""

import re
from typing import Any, Literal
from .flow_models import SpatialIntent
from travel_agent.research.planning import CandidateSelector

CORE = r"中心城区|主城区|市区内?|市内|城内"
OUTSIDE = r"城市周边|市区外|城外|近郊|远郊|郊区|周边游|周边地区"
DEPARTURE = re.compile(r"从.{0,16}(?:市区|城区|市内)出发")


def parse_intent(text: str, kind: str, test: bool) -> SpatialIntent:
    intent = (
        "CITY_AND_SURROUNDINGS"
        if re.search(r"(?:城市|市区|市内).{0,3}(?:与|和|及|含|及其)?周边", text)
        else "CITY_CORE"
        if re.search(CORE, text)
        else "REGIONAL"
        if kind == "REGIONAL"
        else "UNDECIDED"
    )
    return SpatialIntent.model_validate(
        dict(
            intent=intent,
            origin="TEST_INPUT"
            if test
            else "USER_EXPLICIT"
            if intent != "UNDECIDED"
            else "UNKNOWN",
        )
    )


def classify(
    name: str, rows: list[dict[str, Any]], intent: str
) -> tuple[Literal["MATCH", "MISMATCH", "UNKNOWN"], list[dict[str, str]]]:
    """Only explicit body/condition labels establish source-supported fit; title is weak.

    A specific named clause wins over general route framing. A departure clause alone
    says nothing about every destination. Conflicting specific labels remain unknown.
    """
    specific: list[tuple[str, dict[str, str]]] = []
    general: list[tuple[str, dict[str, str]]] = []
    hints: list[dict[str, str]] = []
    for e in rows:
        title = e.get("source_title", "")
        if re.search(CORE + "|" + OUTSIDE, title):
            hints.append(dict(kind="TITLE_WEAK", reference_id=e["claim_id"], text=title[:200]))
        for text in [e["text"], *e.get("conditions", [])]:
            if (
                re.match(
                    r"^(?:[^：:]{0,16})?(?:市区|市内|主城区|中心城区)(?:一日游|游览|游玩|路线|行程)*[：:]",
                    text,
                )
                and not re.search(OUTSIDE, text)
                and not DEPARTURE.search(text)
            ):
                general.append(
                    (
                        "CORE",
                        dict(kind="SOURCE_CONTEXT", reference_id=e["claim_id"], text=text[:200]),
                    )
                )
            for clause in re.split(r"[。；;\n]|→|➡|->", text):
                clause = clause.strip()
                if not clause or DEPARTURE.search(clause):
                    continue
                label = (
                    "UNSURE"
                    if re.search(r"是否|不确定|未知|可能", clause)
                    else "OUTSIDE"
                    if re.search(r"(?:不在|不属于|不是|远离|离开).{0,3}(?:" + CORE + r")", clause)
                    else "OUTSIDE"
                    if re.search(OUTSIDE, clause)
                    else "CORE"
                    if re.search(CORE, clause)
                    else None
                )
                if label is None:
                    continue
                basis = dict(kind="SOURCE_CONTEXT", reference_id=e["claim_id"], text=clause[:200])
                # Route chains can carry one explicitly scoped header; mixed chains
                # require each clause to identify its own activities.
                if name in clause:
                    specific.append((label, basis))
                elif re.search(r"(?:路线|行程|一日游|游玩|游览)", clause) and not re.search(
                    r"位于|坐落|在.{1,20}(?:区|郊)|→|➡", clause
                ):
                    from .materials import place_name

                    names = [place_name(part) for part in re.split(r"→|➡|->", e["text"])]
                    if not any(other and other != name and other in clause for other in names):
                        general.append((label, basis))
    selected = specific or general
    labels = {item[0] for item in selected}
    bases = [item[1] for item in selected] + hints
    status: Literal["MATCH", "MISMATCH", "UNKNOWN"]
    if intent == "CITY_CORE":
        status = (
            "MATCH" if labels == {"CORE"} else "MISMATCH" if labels == {"OUTSIDE"} else "UNKNOWN"
        )
    elif intent == "CITY_AND_SURROUNDINGS":
        status = "MATCH" if labels and labels <= {"CORE", "OUTSIDE"} else "UNKNOWN"
    else:
        status = "UNKNOWN"
    return status, list({(b["kind"], b["reference_id"], b["text"]): b for b in bases}.values())[:20]


def title_risk(title: str, intent: str) -> int:
    if intent != "CITY_CORE":
        return 0
    if re.search(OUTSIDE + r"|周边|周末自驾", title):
        return 1
    return -1 if re.search(CORE, title) else 0


class ScopedSelector(CandidateSelector):
    """Reorder only: title hints never establish an activity's geography."""

    def __init__(self, intent: str):
        super().__init__()
        self.intent = intent

    def select(self, *args: Any, **kwargs: Any) -> Any:
        choices = super().select(*args, **kwargs)
        return tuple(
            sorted(choices, key=lambda c: title_risk(c.candidate.title or "", self.intent))
        )
