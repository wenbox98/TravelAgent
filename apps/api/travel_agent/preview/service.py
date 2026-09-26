"""Cache-only projections and transactional user choices. No research service/provider."""
from copy import deepcopy
import json
from typing import Any
from uuid import uuid4

from travel_agent.domain.models import EvidenceBundle, SourcePolicy
from travel_agent.domain.source_policy import scope_allowed
from travel_agent.persistence.database import Database
from travel_agent.persistence.repositories import EvidenceRepository, encode
from travel_agent.research.content_store import SourceContentStore, audit_grounding
from travel_agent.research.quality import is_grounded
from .models import Mode, PreviewCreate, PreviewMutation
from .projection import EMPTY, fingerprint, gaps, parse_preferences, project, questions, safe_text


class PreviewService:
    def __init__(self, db: Database, scope: str, mode: Mode):
        self.db, self.scope, self.mode = db, scope, mode

    def _cache(self, research_id: str) -> tuple[dict[str, Any], tuple[EvidenceBundle, ...]]:
        q = self.db.connection.execute("SELECT * FROM research_questions WHERE research_id=? AND account_scope=?",
                                       (research_id, self.scope)).fetchone()
        if q is None:
            raise ValueError("RESEARCH_UNAVAILABLE")
        report = self.db.connection.execute(
            "SELECT p.* FROM research_reports p JOIN research_runs r USING(run_id) "
            "WHERE r.research_id=? AND r.revision=? AND r.status='FINISHED' ORDER BY r.rowid DESC LIMIT 1",
            (research_id, q["current_revision"])).fetchone()
        if report is None:
            return dict(q), ()
        sources, claims = json.loads(report["source_handles_json"]), set(json.loads(report["claim_handles_json"]))
        repo, contents = EvidenceRepository(self.db), SourceContentStore(self.db)
        evidence = []
        for source_id in sources:
            b = repo.get(source_id, self.scope)
            if b is None or bool(b["is_synthetic"]) != (self.mode == "SYNTHETIC_DEMO"):
                continue
            p = self.db.connection.execute("SELECT policy_json FROM source_policies WHERE policy_id=? ORDER BY version DESC LIMIT 1", (b["policy_id"],)).fetchone()
            policy = SourcePolicy(json.loads(p[0])) if p else None
            if policy is None or not repo.permitted(policy) or not scope_allowed(policy, self.scope):
                continue
            cached = contents.load(source_id, self.scope, purge=False)
            accepted, metadata = [], {}
            for claim in b["claims"]:
                meta = b.get("claim_metadata", {}).get(claim["claim_id"], {})
                if claim["claim_id"] not in claims or meta.get("context_review_status") not in {"WORK_REVIEWED", "MODEL_CONTEXT_REVIEWED", "LOCAL_REVALIDATION"} or not is_grounded(b, claim):
                    continue
                review = self.db.connection.execute(
                    "SELECT c.context_status,c.claim_id FROM extraction_candidates c "
                    "JOIN extraction_attempts a USING(attempt_id) JOIN source_contents s USING(content_id) "
                    "WHERE c.attempt_id=? AND c.candidate_index=? AND s.account_scope=? AND s.source_id=?",
                    (meta.get("audit_attempt_id"), meta.get("audit_candidate_index"), self.scope, source_id)).fetchone()
                if meta.get("context_review_status") != "LOCAL_REVALIDATION" and (review is None or review["context_status"] != "ACCEPTED" or review["claim_id"] != claim["claim_id"]):
                    continue
                if meta.get('context_review_status') == 'MODEL_CONTEXT_REVIEWED':
                    model = self.db.connection.execute("SELECT results_json FROM context_review_runs WHERE review_id=? "
                        "AND attempt_id=? AND account_scope=? AND mode='RUNTIME' AND status='COMPLETED'",
                        (meta.get('context_review_id'),meta.get('audit_attempt_id'),self.scope)).fetchone()
                    if model is None or not any(i['candidate_index']==meta.get('audit_candidate_index') and
                        i['program']['action']=='ACCEPT' for i in json.loads(model[0])):
                        continue
                singleton = EvidenceBundle(b.to_dict() | {"claims": [claim], "claim_metadata": {claim["claim_id"]: meta}})
                if audit_grounding(singleton, cached)["unsupported"]:
                    continue
                try:
                    for text in [claim["text"], b["source_title"] or "", *meta.get("applicable_conditions", [])]:
                        safe_text(text)
                except ValueError:
                    continue
                accepted.append(claim)
                metadata[claim["claim_id"]] = meta
            if accepted:
                evidence.append(EvidenceBundle(b.to_dict() | {"claims": accepted, "claim_metadata": metadata}))
        return dict(q), tuple(evidence)

    def researches(self) -> list[dict[str, Any]]:
        result = []
        for row in self.db.connection.execute("SELECT research_id FROM research_questions WHERE account_scope=? ORDER BY updated_at DESC,research_id", (self.scope,)):
            q, evidence = self._cache(row[0])
            if not evidence:
                continue
            request = json.loads(q["request_json"])
            result.append({"research_id": q["research_id"], "research_revision": q["current_revision"],
                           "label": " · ".join(safe_text(request[k], 200) for k in ("departure", "destination", "time_hint") if request.get(k)) or "已有研究",
                           "evidence_count": sum(len(b["claims"]) for b in evidence)})
        return result

    def _receipt(self, key: str, payload: Any) -> str | None:
        if not 8 <= len(key) <= 128:
            raise ValueError("INVALID_IDEMPOTENCY_KEY")
        row = self.db.connection.execute("SELECT * FROM preview_receipts WHERE account_scope=? AND mode=? AND idempotency_key=?", (self.scope, self.mode, key)).fetchone()
        if row and row["request_hash"] != fingerprint(payload):
            raise ValueError("IDEMPOTENCY_CONFLICT")
        return str(row["session_id"]) if row else None

    def _remember(self, key: str, payload: Any, session_id: str) -> None:
        self.db.connection.execute("INSERT INTO preview_receipts VALUES(?,?,?,?,?)", (self.scope, self.mode, key, fingerprint(payload), session_id))

    def open(self, research_id: str | None, text: str, key: str) -> dict[str, Any]:
        PreviewCreate(research_id=research_id, text=text)
        payload = ["open", research_id, text]
        with self.db.transaction():
            previous = self._receipt(key, payload)
            if previous:
                return self.get(previous)
            # Exact destination substring only, with unambiguous research match. No semantic search.
            if research_id is None and text:
                matches = []
                for option in self.researches():
                    q, _ = self._cache(option["research_id"])
                    destination = json.loads(q["request_json"]).get("destination")
                    if destination and destination in text:
                        matches.append(option["research_id"])
                if len(matches) == 1:
                    research_id = matches[0]
            q, evidence = self._cache(research_id) if research_id else ({}, ())
            if research_id and not evidence:
                raise ValueError("RESEARCH_UNAVAILABLE")
            request = json.loads(q.get("request_json", "{}"))
            prefs = {"days": request.get("days"), "driving": "NO" if request.get("no_self_drive") else "UNKNOWN",
                     "budget_cny_fen": request.get("budget_cny_fen"), "traveler_count": request.get("traveler_count"),
                     "time_hint": request.get("time_hint"), "travel_date": None, "charter": "UNKNOWN", "answered": []}
            parsed, clarification = parse_preferences(text)
            prefs.update(parsed)
            state = {"input_text": text, "preferences": prefs, "confirmed_option_id": None,
                     "preview_option_id": None, "clarification": clarification}
            sid = "preview-" + uuid4().hex
            digest = fingerprint([b.to_dict() for b in evidence])
            self.db.connection.execute("INSERT INTO preview_sessions VALUES(?,?,?,?,?,?,0,?,?,?)",
                (sid, self.scope, self.mode, research_id, q.get("current_revision"), digest, encode(state), self.db.stamp(), self.db.stamp()))
            self._remember(key, payload, sid)
            return self.get(sid)

    def _load(self, session_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bool]:
        row = self.db.connection.execute("SELECT * FROM preview_sessions WHERE session_id=? AND account_scope=? AND mode=?", (session_id, self.scope, self.mode)).fetchone()
        if row is None:
            raise ValueError("SESSION_UNAVAILABLE")
        q, ev = self._cache(row["research_id"]) if row["research_id"] else ({}, ())
        stale = q.get("current_revision") != row["research_revision"] or fingerprint([b.to_dict() for b in ev]) != row["evidence_revision"]
        data = project(ev, scope=self.scope, research_id=row["research_id"] or "", now=self.db.clock())
        return dict(row), json.loads(row["state_json"]), data, stale

    def get(self, session_id: str) -> dict[str, Any]:
        row, state, data, stale = self._load(session_id)
        options = {o["option_id"]: o for o in data["options"]}
        current = options.get(state["confirmed_option_id"])
        proposed = options.get(state["preview_option_id"])
        def interests(option: dict[str, Any] | None) -> list[str]:
            if not option:
                return []
            ids = option["route_evidence_ids"] + option["experience_evidence_ids"]
            return list(dict.fromkeys(e["text"] for e in option["evidence"] if e["claim_id"] in ids))
        old, new = interests(current), interests(proposed)
        old_gaps, new_gaps = gaps(state["preferences"], current), gaps(state["preferences"], proposed)
        preview = ({"option_id": proposed["option_id"], "added": [x for x in new if x not in old],
                    "removed": [x for x in old if x not in new], "retained": [x for x in new if x in old],
                    "gaps_added": [x for x in new_gaps if x not in old_gaps],
                    "gaps_removed": [x for x in old_gaps if x not in new_gaps],
                    "gaps_retained": [x for x in new_gaps if x in old_gaps]} if proposed else None)
        return {"session_id": session_id, "revision": row["revision"], "research_id": row["research_id"],
                "research_revision": row["research_revision"], "mode": self.mode, "input_text": state["input_text"],
                **data, "preferences": state["preferences"], "confirmed_option_id": state["confirmed_option_id"],
                "preview": preview, "gaps": gaps(state["preferences"], proposed or current),
                "questions": [] if state["clarification"] else questions(state["preferences"]),
                "clarification": state["clarification"], "stale": stale,
                "interest_needs_confirmation":state.get('interest_needs_confirmation',False),
                "previous_interest":state.get('previous_interest'),
                "cache_message": None if data["options"] else EMPTY,
                "feasibility": "UNVERIFIED", "business_calls": {"connect": 0, "search": 0, "detail": 0, "xhs_browser": 0, "model": 0}}

    def latest(self) -> dict[str, Any] | None:
        row = self.db.connection.execute("SELECT session_id FROM preview_sessions WHERE account_scope=? AND mode=? ORDER BY updated_at DESC,rowid DESC LIMIT 1", (self.scope, self.mode)).fetchone()
        return self.get(row[0]) if row else None

    def mutate(self, session_id: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
        mutation = PreviewMutation.model_validate(payload)
        receipt = [session_id, payload]
        with self.db.transaction():
            previous = self._receipt(key, receipt)
            if previous:
                return self.get(previous)
            row, state, data, stale = self._load(session_id)
            if stale:
                raise ValueError("RESEARCH_CHANGED")
            if row["revision"] != mutation.expected_revision:
                raise ValueError("STALE_REVISION")
            action = mutation.action
            if action in {"preview", "confirm"}:
                if mutation.option_id not in {o["option_id"] for o in data["options"]}:
                    raise ValueError("OPTION_UNAVAILABLE")
                if action == "confirm":
                    if state["preview_option_id"] != mutation.option_id:
                        raise ValueError("PREVIEW_REQUIRED")
                    state["confirmed_option_id"], state["preview_option_id"] = mutation.option_id, None
                    state['interest_needs_confirmation']=False
                    state['previous_interest']=None
                else:
                    state["preview_option_id"] = mutation.option_id
            elif action == "cancel":
                state["preview_option_id"] = None
            else:
                if mutation.preferences is None and mutation.text is None:
                    raise ValueError("PREFERENCES_REQUIRED")
                prefs = deepcopy(state["preferences"])
                parsed, question = parse_preferences(mutation.text or "")
                state["clarification"] = question
                if mutation.preferences is not None:
                    parsed = mutation.preferences.model_dump(exclude_unset=True)
                    state["clarification"] = None
                    prefs["answered"] = sorted(set(prefs["answered"]) | parsed.keys())
                prefs.update(parsed)
                state["preferences"] = prefs
            self.db.connection.execute("UPDATE preview_sessions SET state_json=?,revision=revision+1,updated_at=? WHERE session_id=?", (encode(state), self.db.stamp(), session_id))
            self._remember(key, receipt, session_id)
            return self.get(session_id)

    def adopt_research(self, session_id: str, research_id: str, revision: int) -> dict[str, Any]:
        """Called by authorized adoption handlers inside their transaction."""
        row, state, old, _ = self._load(session_id)
        if row["revision"] != revision:
            raise ValueError("STALE_REVISION")
        # Snapshot the CURRENT choice, not the choice captured when the job was dispatched.
        current = next(
            (o for o in old["options"] if o["option_id"] == state["confirmed_option_id"]), None
        )
        q, ev = self._cache(research_id)
        from .projection import project

        new = project(ev, scope=self.scope, research_id=research_id, now=self.db.clock())
        matching = next(
            (
                o
                for o in new["options"]
                if current
                and set(o["route_evidence_ids"]) == set(current["route_evidence_ids"])
                and o["evidence"] == current["evidence"]
            ),
            None,
        )
        if matching:
            state["confirmed_option_id"] = matching["option_id"]
        elif state["confirmed_option_id"]:
            state["previous_interest"] = (
                current["label"] if current else state.get("previous_interest")
            )
            state["interest_needs_confirmation"] = True
        state["preview_option_id"] = None
        self.db.connection.execute(
            "UPDATE preview_sessions SET research_id=?,research_revision=?,evidence_revision=?,state_json=?,revision=revision+1,updated_at=? WHERE session_id=?",
            (
                research_id,
                q["current_revision"],
                fingerprint([b.to_dict() for b in ev]),
                json.dumps(state, ensure_ascii=False),
                self.db.stamp(),
                session_id,
            ),
        )
        return self.get(session_id)
