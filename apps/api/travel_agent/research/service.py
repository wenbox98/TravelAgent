"""Program-owned budgets and revision gates; models never control the browser."""

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal, Protocol

from travel_agent.domain.models import SourcePolicy

from .extractor import EvidenceExtractor, policy_allows_model
from .models import (
    Candidate, CandidateChoice, DetailMaterial, ResearchBudget, ResearchGap,
    ResearchReport, ResearchRequest, ResearchStopped, StopReason,
)
from .planning import CandidateSelector, QueryPlanner, SufficiencyEvaluator
from .store import EvidenceStore


class ResearchReader(Protocol):
    @property
    def text_first(self) -> bool: ...
    def connect(self) -> None: ...
    def search(self, query: str) -> tuple[Candidate, ...]: ...
    def detail(self, candidate: Candidate, detail_number: int) -> DetailMaterial: ...
    def disable_text_first(self) -> None: ...


class ResearchService:
    @staticmethod
    def _material_gap(code: str) -> ResearchGap:
        descriptions = {
            "IMAGE_INFORMATION_REQUIRED": "关键内容指向图片，图片未分析，不能推测",
            "IMAGE_NOT_ANALYZED": "图片未分析，当前证据仅来自文字",
            "CONTENT_INCOMPLETE": "正文完整度不足，不能声称已阅读全文",
            "TRAVEL_TIME_UNKNOWN": "实际旅行时间未知，不能用发布日期替代",
            "PUBLISH_TIME_UNKNOWN": "来源发布日期未知",
            "LOCAL_EXTRACTIVE_ONLY": "当前仅本地低置信摘取，尚未经过模型整理或交叉核验",
            "LLM_UNAVAILABLE_OR_INVALID": "模型不可用或输出不合格，已使用保守摘取",
            "NO_GROUNDED_CLAIMS": "尚无能定位到实际正文的结论",
            "UNSUPPORTED_CLAIMS_REJECTED": "不能定位的模型输出已拒绝",
        }
        return ResearchGap(code, descriptions.get(code, "正文材料仍存在未验证信息"))

    def __init__(self, store: EvidenceStore, reader: ResearchReader,
                 extractor: EvidenceExtractor, policy: SourcePolicy,
                 *, selector: CandidateSelector | None = None,
                 checkpoint: Callable[[dict[str, int]], None] | None = None,
                 temporary_read_allowed: bool = False) -> None:
        self.store, self.reader, self.extractor, self.policy = store, reader, extractor, policy
        self.selector = selector or CandidateSelector()
        self.selector.allow_external = self.selector.allow_external and policy_allows_model(
            policy, external=True, now=datetime.now(timezone.utc),
        )
        self.checkpoint = checkpoint or (lambda _: None)
        self.temporary_read_allowed = temporary_read_allowed
        self.evaluator, self.planner = SufficiencyEvaluator(), QueryPlanner()

    def run(self, request: ResearchRequest, *, research_id: str, revision: int,
            account_scope: str, budget: ResearchBudget = ResearchBudget()) -> ResearchReport:
        run_id = self.store.begin(research_id, revision, request.to_dict(), account_scope)
        policy_error = False
        try:
            self.store.register_policy(run_id, revision, self.policy)
        except (ValueError, PermissionError):
            policy_error = True
        # Lookup precedes even connect. Empty budgets are a genuinely offline mode.
        evidence = self.store.lookup(research_id, request.destination, account_scope) if not policy_error else ()
        cached = len(evidence)
        gaps = self.evaluator.gaps(request, evidence)
        attempted = {bundle["source_id"] for bundle in evidence}
        modes: list[str] = []
        choices: list[CandidateChoice] = []
        candidate_count = query_count = 0
        extra_gaps = {code: self._material_gap(code)
                      for bundle in evidence for code in bundle["missing_fields"]}
        diagnostic: str | None = None
        fallback_used = False

        def current() -> None:
            if not self.store.is_current(run_id, revision):
                raise ResearchStopped("ERROR", "STALE_REVISION")

        def finish(reason: StopReason) -> ResearchReport:
            obsolete = not self.store.is_current(run_id, revision)
            report = ResearchReport(
                research_id, revision, run_id, request, evidence,
                tuple({gap.gap_id: gap for gap in (*gaps, *extra_gaps.values())}.values()),
                "ERROR" if obsolete else reason, self.store.operations(run_id), cached,
                query_count, candidate_count, tuple(modes), obsolete,
                "STALE_REVISION" if obsolete else diagnostic, tuple(choices),
            )
            self.store.finish(run_id, revision, [g.to_dict() for g in report.gaps], report.safe_summary())
            return report

        def reserve(kind: Literal["SEARCH", "DETAIL"], fingerprint: str, limit: int) -> None:
            current()
            if not self.store.reserve_operation(run_id, revision, kind, fingerprint, limit):
                current()
                raise ResearchStopped("BUDGET_EXHAUSTED")
            self.checkpoint(self.store.operations(run_id))
            current()

        def read(candidate: Candidate, fallback: bool = False) -> DetailMaterial:
            reserve("DETAIL", candidate.source_id + (":fallback" if fallback else ""),
                    budget.max_feed_details)
            result = self.reader.detail(candidate, self.store.operations(run_id)["detail"])
            current()
            if result.source_id != candidate.source_id or not result.identity_match:
                raise ResearchStopped("SOURCE_UNAVAILABLE", "IDENTITY_MISMATCH")
            if not result.body.strip():
                raise ResearchStopped("SOURCE_UNAVAILABLE", "EMPTY_BODY", fallback_eligible=True)
            return result

        if policy_error:
            diagnostic = "SOURCE_POLICY_REGISTRATION_FAILED"
            return finish("SOURCE_UNAVAILABLE")
        if not gaps:
            return finish("EVIDENCE_SUFFICIENT")
        if budget.max_search_operations == 0 or budget.max_feed_details == 0:
            return finish("BUDGET_EXHAUSTED")
        now = datetime.now(timezone.utc)
        expires = self.policy["expires_at"]
        transient_allowed = bool(
            self.temporary_read_allowed and self.policy["basis"] == "UNKNOWN"
            and self.policy["allow_read"] and self.policy["allow_inference"]
            and (expires is None or datetime.fromisoformat(expires) > now)
        )
        if not transient_allowed and not policy_allows_model(self.policy, external=False, now=now):
            diagnostic = "SOURCE_POLICY_READ_DENIED"
            return finish("SOURCE_UNAVAILABLE")
        try:
            current()
            self.reader.connect()
            current()
            while gaps:
                operations = self.store.operations(run_id)
                if (operations["search"] >= budget.max_search_operations
                    or operations["detail"] >= budget.max_feed_details):
                    return finish("BUDGET_EXHAUSTED")
                queries = self.planner.plan(request, evidence, gaps, self.store.queries(research_id))
                if not queries:
                    return finish("NO_USEFUL_CANDIDATES")
                query = queries[0]
                reserve("SEARCH", sha256(self.planner.normalize(query.text).encode()).hexdigest(),
                        budget.max_search_operations)
                if not self.store.record_query(run_id, revision, self.planner.normalize(query.text)):
                    current()
                    return finish("NO_USEFUL_CANDIDATES")
                query_count += 1
                candidates = self.reader.search(query.text)
                current()
                candidate_count += len(candidates)
                self.selector.allow_external = self.selector.allow_external and policy_allows_model(
                    self.policy, external=True, now=datetime.now(timezone.utc),
                )
                selected = self.selector.select(candidates, request, gaps, attempted)
                for choice in selected:
                    if self.store.operations(run_id)["detail"] >= budget.max_feed_details:
                        return finish("BUDGET_EXHAUSTED")
                    choices.append(choice)
                    candidate = choice.candidate
                    attempted.add(candidate.source_id)
                    was_text_first = self.reader.text_first
                    try:
                        material = read(candidate)
                    except ResearchStopped as error:
                        # Exactly one technical fallback, same source, same charged budget.
                        if (was_text_first and error.fallback_eligible and not fallback_used
                            and error.reason == "SOURCE_UNAVAILABLE"
                            and error.code in {"PARSE_ERROR", "BROWSER_ERROR", "UNKNOWN", "EMPTY_BODY"}
                            and self.store.operations(run_id)["detail"] < budget.max_feed_details):
                            fallback_used = True
                            self.reader.disable_text_first()
                            material = read(candidate, fallback=True)
                        else:
                            raise
                    current()
                    extracted = self.extractor.extract(
                        source_id=material.source_id, source_title=material.title,
                        body=material.body, completeness=material.completeness,
                        fetched_at=material.fetched_at, source_published_at=material.published_at,
                        policy=self.policy, source_type=material.source_type,
                        destination=request.destination, image_count=material.image_count,
                        temporary_read_allowed=self.temporary_read_allowed,
                        research_gaps=tuple(gap.gap_id for gap in gaps),
                    )
                    current()
                    modes.append(extracted.mode)
                    snapshot = {
                        "completeness": material.completeness, "body_chars": len(material.body),
                        "image_count": material.image_count, "identity_match": material.identity_match,
                        "published_at": material.published_at, "fetched_at": material.fetched_at,
                        "extraction_mode": extracted.mode,
                        "evidence_count": len(extracted.bundle["claims"]),
                    }
                    saved = self.store.save_evidence(run_id, revision, extracted.bundle,
                                                     self.policy, snapshot)
                    if not saved:
                        current()
                        diagnostic = "SOURCE_POLICY_STORAGE_DENIED"
                        return finish("SOURCE_UNAVAILABLE")
                    evidence = self.store.lookup(research_id, request.destination, account_scope)
                    for gap_code in extracted.gaps:
                        extra_gaps[gap_code] = self._material_gap(gap_code)
                    gaps = self.evaluator.gaps(request, evidence)
                    if not gaps and "IMAGE_INFORMATION_REQUIRED" not in extra_gaps:
                        return finish("EVIDENCE_SUFFICIENT")
                if not selected:
                    return finish("NO_USEFUL_CANDIDATES")
                if not gaps:
                    return finish("SOURCE_UNAVAILABLE")
        except ResearchStopped as error:
            diagnostic = error.code
            return finish(error.reason)
        except PermissionError:
            diagnostic = "SOURCE_POLICY_DENIED"
            return finish("SOURCE_UNAVAILABLE")
        except Exception:
            # Do not interpolate third-party exceptions, prompts, URLs or browser traces.
            diagnostic = "RESEARCH_ERROR"
            return finish("ERROR")
        return finish("EVIDENCE_SUFFICIENT")
