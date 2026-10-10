"""Cheap pre-extraction purpose matching, never evidence or semantic approval."""

import re

from .canonical import canonicalize
from .grounding import IMAGE_REFERENCE
from .model_input import outbound_blocks
from .models import ResearchGap, ResearchRequest

ROUTE = re.compile(r"路线|行程|自驾|班车|徒步|[一二三四五六七八九十两\d]+[天日]|D[1-9]|→")
PLAY_QUESTION = re.compile(r"玩法|怎么玩|体验|看点|取舍|游玩|观赏")
# These are content signals, not a place-name suffix allowlist. Downstream review
# must still establish the subject, role, conditions and exact references.
PLAY_CONTENT = re.compile(
    r"展陈|展览|参观|观赏|欣赏|手作|手工|互动|散步|拍照|体验|游玩|攀爬|观鸟|露营"
)


def play_focused(request: ResearchRequest) -> bool:
    """A mixed route/experience question retains the general research query."""
    return bool(
        PLAY_QUESTION.search(request.research_question)
        and not ROUTE.search(request.research_question)
    )


def skip_reason(
    request: ResearchRequest, gaps: tuple[ResearchGap, ...], state_body: str, dom_body: str | None
) -> str | None:
    usable = [
        b.text
        for b in outbound_blocks(canonicalize(state_body, dom_body).blocks)
        if not b.text.startswith("#")
    ]
    text = "\n".join(usable)
    # A picture pointer contributes no substantive text. Independent text next to
    # it can still be extracted; the original unmodified body goes to grounding.
    clauses = [
        p.strip()
        for p in re.split(r"[。！？\n]", text)
        if not IMAGE_REFERENCE.search(p) and not p.lstrip().startswith("#")
    ]
    enough = sum(map(len, clauses)) >= 40
    topics = {topic for gap in gaps for topic in gap.topics}
    if {gap.gap_id for gap in gaps} == {"LODGING"}:
        lodging = enough and any(len(p) >= 12 and re.search(
            r"住宿|住在|住哪|入住|旅馆|酒店|民宿|落脚", p) for p in clauses)
        return None if lodging else "INSUFFICIENT_TEXT_FOR_EXTRACTION"
    question = request.research_question
    route_needed = bool(ROUTE.search(question)) or bool(topics & {"ROUTE", "DURATION", "TRANSPORT"})
    play_needed = bool(PLAY_QUESTION.search(question)) or "EXPERIENCE" in topics
    route = route_needed and any(ROUTE.search(p) for p in clauses)
    play = play_needed and any(
        len(p) >= 12 and PLAY_CONTENT.search(p) for p in clauses
    )
    topic_signals = {
        "SEASON": r"季节|春季|夏季|秋季|冬季|雨季|雪季|月份|气温|天气|[一二三四五六七八九十\d]+月",
        "TRANSPORT": r"公交|地铁|公共交通|铁路|高铁|火车|接驳|包车|班车|大巴|巴士",
        "DURATION": r"停留|用时|耗时|小时|分钟|[一二三四五六七八九十\d]+天",
        "TRADEOFF": r"住宿|住在|入住|酒店|民宿|落脚|片区|取舍|不如|相比",
    }
    focused = any(
        topic in topics and any(len(p) >= 12 and re.search(pattern, p) for p in clauses)
        for topic, pattern in topic_signals.items()
    )
    if enough and (route or play or focused):
        return None
    return (
        "IMAGE_INFORMATION_REQUIRED"
        if IMAGE_REFERENCE.search(text)
        else "INSUFFICIENT_TEXT_FOR_EXTRACTION"
    )
