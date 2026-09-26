"""Read-only explanations and explicit adoption; no HTTP replay/approval endpoint."""

import json
from typing import Any
from fastapi import FastAPI, Request
from travel_agent.persistence.database import Database
from travel_agent.research.store import EvidenceStore
from travel_agent.research.review_replay import binding, verify_record
from .api import PreviewConfig
from .models import ReplayIndex, ReplayAdopt, PreviewView
from .projection import safe_text
from .service import PreviewService


def explanation(reason: str) -> tuple[str, str, str]:
    precise = {
        "ROLE_MISMATCH": (
            "来源性质",
            "计划、亲历或攻略整理的角色与引用上下文不一致。",
            "保留作者原来的计划/历史/建议性质，不能改称实测经历。",
        ),
        "CONTEXT_CONDITION_OMITTED": (
            "上下文条件",
            "必要的主体、否定、计划或适用条件未包含在引用集合中。",
            "先补足同源已发送条件；本轮不会自动改写原提议。",
        ),
        "DEPENDENCY_UNRESOLVED": (
            "对象或依赖",
            "缺少已经接纳且指向同一原文锚点的路线对象，或仓储关联检查未通过。",
            "保留日段和缺口，不能把未建立关系的片段拼成路线。",
        ),
        "CONTEXT_TIME_UNCERTAIN": (
            "时间适用性",
            "原模型未能确定相关时间及适用条件。",
            "需要明确来源时段；用户假期不能代替来源依据。",
        ),
        "CONTEXT_REVIEW_REQUIRED": (
            "原模型待审",
            "原模型主动保留待审，没有给出可采用的上下文判断。",
            "本地字段转换不能替模型作答；保持待审。",
        ),
    }
    if reason in precise:
        return precise[reason]
    if reason == "DURATION_SCOPE_MISMATCH":
        return (
            "契约或时间依据",
            "时间字段与候选含义不一致，或原文不足以证明时长。",
            "旧 v1 日序歧义是本次代码分析；仅有可验证日序锚点时可本地重校验，其他情况保留缺口。",
        )
    if reason == "UNVERIFIED_IMPORTANT_FACT":
        return (
            "当前事实",
            "运营、接驳、价格、安全或天气等重要事实尚未核实。",
            "以后围绕具体方向查可靠且适用的来源；本轮不新增访问。",
        )
    if reason in {
        "INVALID_REFERENCE",
        "REPLAY_UNAVAILABLE",
        "REVIEW_INPUT_CHANGED",
        "REPLAY_BINDING_CHANGED",
    }:
        return (
            "安全或引用异常",
            "引用快照、权限或保存的提议不足以支持本地回放。",
            "不可采用；保留原记录，先核对同源快照与读取权限。",
        )
    if reason == "MODEL_CONTEXT_SUPPORTED":
        return (
            "条件参考",
            "引用及上下文校验通过，仅作为带条件的参考。",
            "继续保留来源性质；尚未核实当前事实或行程可行性。",
        )
    return (
        "上下文或依赖",
        "主体、时间、条件、来源性质或所属路线仍有未解决的关系。",
        "需补足相应条件或同源对象锚点；待审不需要用户逐条强行批准。",
    )


def review_index(db: Database, scope: str, mode: Any) -> dict[str, Any]:
    store = EvidenceStore(db)
    items, updates = [], []
    reviews = db.connection.execute(
        "SELECT * FROM context_review_runs WHERE account_scope=? AND status='COMPLETED' ORDER BY rowid",
        (scope,),
    ).fetchall()
    source_numbers: dict[str, int] = {}
    for r in reviews:
        try:
            _, _, ctx, bound = binding(store, r["review_id"], scope)
        except ValueError, PermissionError:
            category, meaning, action = explanation("REPLAY_UNAVAILABLE")
            items.append(
                dict(
                    source_label="受限来源",
                    candidate_index=0,
                    topic="UNKNOWN",
                    origin="原审核",
                    rule_version=r["rule_version"],
                    action="NEEDS_REVIEW",
                    reason_code="REPLAY_UNAVAILABLE",
                    category=category,
                    explanation=meaning,
                    next_action=action,
                    quote=None,
                    locator=None,
                    conversion=None,
                )
            )
            continue
        number = source_numbers.setdefault(bound["source_id"], len(source_numbers) + 1)
        histories = [("原模型提议 + 原程序审核", r["rule_version"], json.loads(r["results_json"]))]
        local = db.connection.execute(
            "SELECT * FROM review_revalidations WHERE review_id=? AND status='COMPLETED' ORDER BY rowid",
            (r["review_id"],),
        ).fetchall()
        for record in local:
            try:
                verify_record(store, record["revalidation_id"], scope)
            except ValueError, PermissionError:
                continue
            histories.append(
                (
                    "本地重校验 · " + ("隔离评估" if record["mode"] == "EVALUATION" else "运行时"),
                    record["rule_version"],
                    json.loads(record["results_json"]),
                )
            )
            if record["mode"] == "RUNTIME" and record["research_id"]:
                _, evidence = PreviewService(db, scope, mode)._cache(record["research_id"])
                count = db.connection.execute(
                    "SELECT count(*) FROM revalidation_claims WHERE revalidation_id=?",
                    (record["revalidation_id"],),
                ).fetchone()[0]
                if count and evidence:
                    updates.append(
                        dict(
                            revalidation_id=record["revalidation_id"],
                            research_id=record["research_id"],
                            evidence_count=sum(len(b["claims"]) for b in evidence),
                            added=count,
                        )
                    )
        for origin, version, rows in histories:
            for row in rows:
                index, decision = row["candidate_index"], row["program"]
                raw = ctx["raw"].get(index)
                if raw is None:
                    continue
                category, meaning, action = explanation(decision["reason_code"])
                try:
                    quote = safe_text(raw["quote"][:120], 120)
                except ValueError:
                    quote = None
                items.append(
                    dict(
                        source_label=f"来源 {number}",
                        candidate_index=index,
                        topic=raw["topic"],
                        origin=origin,
                        rule_version=version,
                        action=decision["action"],
                        reason_code=decision["reason_code"],
                        category=category,
                        explanation=meaning,
                        next_action=action,
                        quote=quote,
                        locator=raw["reference_selection"]["statement"]["span_id"]
                        if quote
                        else None,
                        conversion="日序字段 DAY_SEGMENT → NONE；已保留同源日序锚点并继续完整审核。"
                        if row.get("conversion")
                        else None,
                    )
                )
    return {
        "items": items,
        "updates": updates,
        "message": "待审不等于错误，也不等于已通过。模型没有重新作答；本地校验不核实外部事实。",
    }


def install_replay(app: FastAPI, config: PreviewConfig) -> None:
    @app.get("/api/v1/preview/reviews", response_model=ReplayIndex)
    def read() -> dict[str, Any]:
        with Database(config.database) as db, db.transaction():
            return review_index(db, config.account_scope, config.mode)

    @app.post("/api/v1/preview/review-update", response_model=PreviewView)
    def adopt(body: ReplayAdopt, request: Request) -> dict[str, Any]:
        with Database(config.database) as db, db.transaction():
            record = verify_record(EvidenceStore(db), body.revalidation_id, config.account_scope)
            if (
                record["mode"] != "RUNTIME"
                or record["status"] != "COMPLETED"
                or not record["research_id"]
            ):
                raise ValueError("NEW_MATERIAL_UNAVAILABLE")
            preview = PreviewService(db, config.account_scope, config.mode)
            receipt = ["replay-adopt", body.model_dump()]
            key = request.headers.get("idempotency-key", "")
            previous = preview._receipt(key, receipt)
            if previous:
                return preview.get(previous)
            view = preview.get(body.session_id)
            _, _, ctx, _ = binding(EvidenceStore(db), record["review_id"], config.account_scope)
            if view["research_id"] not in {ctx["attempt"]["research_id"], record["research_id"]}:
                raise ValueError("RESEARCH_CHANGED")
            result = preview.adopt_research(
                body.session_id, record["research_id"], body.expected_revision
            )
            preview._remember(key, receipt, body.session_id)
            return result
