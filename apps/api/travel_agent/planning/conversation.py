"""Versioned, trip-local choices and grounded local explanations for the normal chat."""

import re
from typing import Any, Literal
from uuid import uuid4
from pydantic import Field, field_validator
from travel_agent.preview.models import StrictModel
from travel_agent.preview.projection import fingerprint, safe_text
from .automatic_models import CONSENT, AutomaticAction


class ConversationAction(StrictModel):
    action: Literal[
        "message", "select", "exclude", "clear", "exclude_activity", "restore_activity", "continue"
    ]
    expected_revision: int = Field(ge=0)
    expected_conversation_version: int = Field(ge=0)
    option_id: str | None = Field(default=None, max_length=100)
    activity_id: str | None = Field(default=None, max_length=100)
    text: str = Field(default="", max_length=500)
    consent: Literal["PRIVATE_RESEARCH_AND_ADVICE_V2"] | None = None

    @field_validator("text")
    @classmethod
    def safe(cls, value: str) -> str:
        return safe_text(value, 500).strip()


def state(p: dict[str, Any]) -> dict[str, Any]:
    return dict(
        p.get(
            "conversation",
            dict(version=0, messages=[], selected=None, excluded=[], excluded_activities=[]),
        )
    )


def message(p: dict[str, Any], role: str, text: str, **fields: Any) -> None:
    c = p.setdefault(
        "conversation",
        dict(version=0, messages=[], selected=None, excluded=[], excluded_activities=[]),
    )
    c["messages"].append(dict(message_id=uuid4().hex, role=role, text=text, **fields))
    c["version"] = c.get("version", 0) + 1


def options(job: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not job:
        return []
    return [
        dict(
            option_id="option-" + fingerprint([job["job_id"], item])[:32],
            job_id=job["job_id"],
            index=i,
            proposal=item,
        )
        for i, item in enumerate(job.get("proposals", []))
    ]


def view(p: dict[str, Any], job: dict[str, Any] | None) -> dict[str, Any]:
    c = state(p)
    values = options(job)
    selected = c["selected"]
    ids = {v["option_id"] for v in values}
    return dict(
        c,
        intent_key=p.get("conversation_intent_key"),
        options=values,
        selected_current=bool(selected and selected["option_id"] in ids),
        choice_version=job["job_id"] if job else None,
        pending_question=question(p),
    )


def question(p: dict[str, Any]) -> dict[str, Any]:
    d = p["draft"]
    if d["transport"] == "UNKNOWN" and d["driving"] != "NO":
        return dict(
            text="愿意自己开车吗？这会影响区域跨度和衔接。",
            choices=["不想自驾", "想自驾", "暂不确定，先给建议"],
        )
    if d.get("days") is None:
        return dict(
            text="大概有几天？天数会影响选择面，也可以先保持未知。",
            choices=["只有3天", "只有5天", "暂不确定，先给建议"],
        )
    if p.get("automatic_coverage", {}).get("gaps"):
        return dict(
            text="资料仍有缺口。可以先比较局部玩法，也可以继续补充研究。",
            choices=["先比较现有方案", "继续补充研究"],
        )
    return dict(
        text="可以先选择方向，再补充偏好；采用并保存仍需单独确认。",
        choices=["为什么推荐这些", "先比较现有方案"],
    )


def model_context(p: dict[str, Any]) -> dict[str, Any]:
    """Only structured choices and a small filtered input summary cross the boundary."""
    from travel_agent.research.canonical import body_blocks
    from travel_agent.research.model_input import outbound_blocks

    c = state(p)

    def minimal(text: str) -> str:
        # A free-form address is unnecessary for advisory planning. Keep it local.
        if re.search(r"小区|单元|门牌|楼栋|密码|口令|[路街巷]\s*\d+号|token\s*[:=]", text, re.I):
            return "[个人位置或访问资料已省略]"
        return "\n".join(b.text for b in outbound_blocks(body_blocks(text), max_chars=500))

    return dict(
        version=1,
        user_inputs=[
            minimal(t) for t in [*p.get("automatic_input_history", []), p["request"]][-5:]
        ],
        selected=c["selected"],
        excluded=c["excluded"],
        excluded_activity_ids=c["excluded_activities"],
        recent_messages=[
            dict(role=m["role"], text=minimal(m["text"]))
            for m in [m for m in c["messages"] if m["role"] == "USER"][-6:]
        ],
        material_coverage=p.get("automatic_coverage"),
        pending_question=question(p),
        changes=p.get("automatic_changes", []),
        meaning="方向偏好可修改；不是长期偏好、作者事实或已采用版本。未知条件继续未知。",
    )


def explain(
    p: dict[str, Any], job: dict[str, Any] | None, refs: list[dict[str, Any]], text: str
) -> tuple[str, list[dict[str, Any]]]:
    choices = options(job)
    selected = state(p)["selected"]
    if selected:
        choices = [o for o in choices if o["option_id"] == selected["option_id"]] or choices
    citations = [
        dict(
            citation_id=r["claim_id"],
            text=r["text"][:220],
            conditions=r.get("conditions", []),
            source_title=r.get("source_title"),
            role=r.get("reference_kind"),
            review=r.get("review_status"),
        )
        for r in refs[:4]
    ]
    if re.search(r"为什么|依据|怎么选|对比|比较|区别|不同", text):
        reasons = "；".join(
            o["proposal"]["title"] + "：" + o["proposal"]["reason"] for o in choices
        )
        result = "现有方案的建议理由：" + reasons if reasons else "当前还没有可比较的合格方案。"
        result += " 下面是当前有效的来源引用；AI理由和停留均为建议，不是原文事实或可行性保证。"
    elif "暂不确定" in text:
        result = "可以保持未知，先看现有建议；没有替你选择交通、日期或预算，也没有发起新查询。"
    else:
        result = "这次只查看现有资料，没有更改选择或联网。当前资料未必能回答这个具体问题；可查看下方引用和缺口。若要调整，请明确天数、交通、节奏，或点选要保留/排除的方案或项目。"
    gaps = p.get("automatic_coverage", {}).get("gaps", [])
    if gaps:
        result += " 仍缺：" + "；".join(g["label"] for g in gaps)
    return result, citations


def action(db: Any, scope: str, sid: str, body: ConversationAction, key: str) -> dict[str, Any]:
    from .automatic import AutomaticService, save, invalidate, revise
    from .flow_models import PlanDraft
    from .guide_assessment import references

    service = AutomaticService(db, scope)
    payload = ["conversation", sid, body.model_dump()]
    with db.transaction():
        if service._receipt(key, payload):
            return service.plans.get(sid)
        row, container = service.plans.load(sid)
        p = container["planning"]
        if row["revision"] != body.expected_revision:
            raise ValueError("STALE_REVISION")
        current = service.plans.get(sid)
        c = p.setdefault(
            "conversation",
            dict(version=0, messages=[], selected=None, excluded=[], excluded_activities=[]),
        )
        if c["version"] != body.expected_conversation_version:
            raise ValueError("STALE_CONVERSATION_VERSION")
        dispatch: Literal["refine", "revise", "research_more"] | None = None
        local_changed = False
        if body.action in {"select", "exclude", "clear"}:
            chosen = next(
                (o for o in options(current["job"]) if o["option_id"] == body.option_id), None
            )
            historical = next(
                (
                    o
                    for o in [c["selected"], *c["excluded"]]
                    if o and o["option_id"] == body.option_id
                ),
                None,
            )
            if body.action == "clear" and historical:
                snapshot = historical
            elif chosen and current["job"].get("can_preview"):
                snapshot = dict(
                    option_id=chosen["option_id"],
                    job_id=chosen["job_id"],
                    title=chosen["proposal"]["title"],
                    activity_ids=[a["activity_id"] for a in chosen["proposal"]["activities"]],
                    order=[a["activity_id"] for a in chosen["proposal"]["activities"]],
                )
            else:
                raise ValueError("STALE_CONVERSATION_OPTION")
            if body.action == "select":
                c["selected"] = snapshot
                c["excluded"] = [o for o in c["excluded"] if o["option_id"] != body.option_id]
                answer = "已记住这个暂定方向。下次更新会带上它；没有采用或发起查询，可随时改选。"
            elif body.action == "exclude":
                c["excluded"] = [o for o in c["excluded"] if o["option_id"] != body.option_id] + [
                    snapshot
                ]
                if c["selected"] and c["selected"]["option_id"] == body.option_id:
                    c["selected"] = None
                answer = "已记住本轮不选这个方案，不等于排除其中每个地点。没有联网，可撤回。"
            else:
                c["selected"] = (
                    None
                    if c["selected"] and c["selected"]["option_id"] == body.option_id
                    else c["selected"]
                )
                c["excluded"] = [o for o in c["excluded"] if o["option_id"] != body.option_id]
                answer = "已撤回这个方案的暂时选择，原采用版保留。"
            message(
                p,
                "USER",
                {"select": "偏向：", "exclude": "本轮不选：", "clear": "撤回："}[body.action]
                + snapshot["title"],
            )
            message(p, "ASSISTANT", answer)
        elif body.action in {"exclude_activity", "restore_activity"}:
            a = next(
                (a for a in p["draft"]["activities"] if a["activity_id"] == body.activity_id), None
            )
            if not a:
                raise ValueError("STALE_CONVERSATION_OPTION")
            if (a.get("locked") or a.get("locked_start")) and body.action == "exclude_activity":
                raise ValueError("PLANNING_LOCKED_CONSTRAINT")
            ids = set(c["excluded_activities"])
            if body.action == "exclude_activity":
                ids.add(body.activity_id)
            else:
                ids.discard(body.activity_id)
            c["excluded_activities"] = sorted(ids)
            message(
                p,
                "USER",
                ("本轮不安排：" if body.action == "exclude_activity" else "恢复备选：") + a["name"],
            )
            message(
                p,
                "ASSISTANT",
                "已记住项目取舍。下一次显式更新会使用此选择；当前采用版没有变化，也没有联网。",
            )
        elif body.action == "continue":
            dispatch = "refine"
        else:
            if not body.text:
                raise ValueError("INVALID_INPUT")
            message(p, "USER", body.text)
            if body.text == "继续补充研究":
                dispatch = "research_more"
            elif body.text in {"继续", "更新方案", "按当前取舍更新"}:
                dispatch = "refine"
            elif body.text == "换一个" and c["selected"]:
                c["excluded"] = [
                    o for o in c["excluded"] if o["option_id"] != c["selected"]["option_id"]
                ] + [c["selected"]]
                c["selected"] = None
                local_changed = True
                message(
                    p,
                    "ASSISTANT",
                    "已记住不选上一方向。你可以改选现有备选，或按当前取舍更新；尚未联网或采用。",
                )
            elif (name := re.fullmatch(r"(?:不想去|不去|排除)(.+)", body.text)) and (
                activity := next(
                    (a for a in p["draft"]["activities"] if a["name"] == name[1].strip()), None
                )
            ):
                if activity.get("locked") or activity.get("locked_start"):
                    raise ValueError("PLANNING_LOCKED_CONSTRAINT")
                c["excluded_activities"] = sorted(
                    set(c["excluded_activities"]) | {activity["activity_id"]}
                )
                local_changed = True
                message(
                    p,
                    "ASSISTANT",
                    "已按当前项目身份记住排除项，下一次更新将落实；没有联网，也未覆盖采用版。",
                )
            elif re.search(
                r"为什么|依据|怎么选|对比|比较|区别|不同|[?？]|暂不确定|先给建议", body.text
            ):
                answer, citations = explain(
                    p, current["job"], references(db, scope, sid, p), body.text
                )
                message(
                    p,
                    "ASSISTANT",
                    answer,
                    citations=citations,
                    origin="LOCAL_REFERENCE_EXPLANATION",
                )
            else:
                # Only advertised, deterministic modifications start a new bounded loop.
                try:
                    revise(PlanDraft.model_validate(p["draft"]), body.text)
                    dispatch = "revise"
                except ValueError:
                    answer, citations = explain(
                        p, current["job"], references(db, scope, sid, p), body.text
                    )
                    message(
                        p,
                        "ASSISTANT",
                        answer,
                        citations=citations,
                        origin="LOCAL_REFERENCE_EXPLANATION",
                    )
        if dispatch:
            if body.consent != CONSENT:
                raise ValueError("OPERATION_NOT_AUTHORIZED")
            if any(
                a["activity_id"] in c["excluded_activities"]
                and (a.get("locked") or a.get("locked_start"))
                for a in p["draft"]["activities"]
            ):
                raise ValueError("PLANNING_LOCKED_CONSTRAINT")
            # A deliberate update is not adopting a proposal. Locks and sources stay bound.
            message(
                p,
                "ASSISTANT",
                "正在按当前取舍更新。先评估已有资料，缺口才有限补查；新结果仍需你明确采用。",
            )
        else:
            # Local explanation changes conversation, not the proposal input/revision.
            # Selections change model input and must invalidate any active generation.
            if body.action != "message" or local_changed:
                invalidate(db, sid, "CONVERSATION_CHANGED")
            # Completed proposals remain previewable after a local conversation event.
            p["conversation_intent_key"] = key
        revision = save(db, sid, container, bump=bool(dispatch))
        if dispatch:
            service.action(
                sid,
                AutomaticAction(
                    action=dispatch,
                    text=body.text if dispatch == "revise" else "",
                    expected_revision=revision,
                    consent=CONSENT,
                ),
                key + "-task",
            )
        service.db.connection.execute(
            "UPDATE preview_sessions SET state_json=json_set(state_json,'$.planning.conversation_intent_key',?) WHERE session_id=?",
            (key, sid),
        )
        from travel_agent.preview.service import PreviewService

        PreviewService(db, scope, "CACHED_PRIVATE_PREVIEW")._remember(
            key, ["automatic-receipt", payload], sid
        )
        return service.plans.get(sid)
