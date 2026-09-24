"""Synthetic quality checks through production extraction, reports, and cache paths.

No live reader is imported. Fixture expectations are executable checks, not recorded
claims of success. A passing synthetic benchmark is never a real-model G1 pass.
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any

from travel_agent.domain.models import EvidenceBundle, SourcePolicy
from travel_agent.persistence.database import Database
from travel_agent.providers.llm import LLMError, OpenAICompatibleProvider
from travel_agent.providers.mock.llm import MockLLMProvider

from .extractor import EvidenceExtractor, ExtractionResult
from .freshness import assess_freshness
from .models import Candidate, DetailMaterial, ResearchBudget, ResearchReport, ResearchRequest
from .planning import CandidateSelector, SufficiencyEvaluator
from .quality import claim_clusters, evaluate_coverage, evidence_conflicts, has_locator, source_independence
from .reporting import render_material_report
from .service import ResearchService
from .store import EvidenceStore


class NoAccessReader:
    """A positive budget must still never bypass a sufficient cache."""

    text_first = False

    def __init__(self) -> None:
        self.calls = {"connect": 0, "search": 0, "detail": 0}

    def connect(self) -> None:
        self.calls["connect"] += 1
        raise AssertionError("BENCHMARK_READER_CALLED")

    def search(self, query: str) -> tuple[Candidate, ...]:
        self.calls["search"] += 1
        raise AssertionError("BENCHMARK_READER_CALLED")

    def detail(self, candidate: Candidate, detail_number: int) -> DetailMaterial:
        self.calls["detail"] += 1
        raise AssertionError("BENCHMARK_READER_CALLED")

    def disable_text_first(self) -> None:
        raise AssertionError("BENCHMARK_FALLBACK_CALLED")


def live_preflight(environ: Mapping[str, str] | None = None, *,
                   usage_mode: str = "PRIVATE_LOCAL_RESEARCH") -> dict[str, Any]:
    """Configuration presence only: no provider request, login or live permission grant."""
    try:
        configured = OpenAICompatibleProvider.from_env(environ) is not None
    except LLMError:
        return {"status": "G1_LIVE_LLM_BLOCKED", "reason": "LLM_CONFIG_INVALID", "live_operations": 0}
    if not configured:
        return {"status": "G1_LIVE_LLM_BLOCKED", "reason": "LLM_NOT_CONFIGURED", "live_operations": 0}
    return {"status": "PRIVATE_LOCAL_CONFIG_READY" if usage_mode == "PRIVATE_LOCAL_RESEARCH"
            else "G1_LIVE_SOURCE_POLICY_BLOCKED", "usage_mode": usage_mode,
            "real_model_verified": False, "live_operations": 0}


class QualityBenchmark:
    def __init__(self, project: Path) -> None:
        self.project = project
        self.spec = json.loads((project / "fixtures/research-quality-benchmark.json").read_text(encoding="utf-8"))
        if self.spec.get("is_synthetic") is not True:
            raise ValueError("benchmark 只接受明确合成夹具")
        self.now = datetime.fromisoformat(self.spec["assessed_at"])
        policies = json.loads((project / "fixtures/policies.json").read_text(encoding="utf-8"))["policies"]
        self.policy, self.unknown_policy = SourcePolicy(policies[0]), SourcePolicy(policies[1])
        self.request = ResearchRequest(departure="合成城", destination="合成地区")
        self.bodies: dict[str, str] = {}

    def extract(self, note: dict[str, Any], *, rows: list[dict[str, Any]] | None = None,
                body: str | None = None, dom: str | None = None,
                policy: SourcePolicy | None = None, image_count: int = 0) -> ExtractionResult:
        if not note["source_id"].startswith("synthetic:"):
            raise ValueError("benchmark 来源必须是合成标识")
        text = body if body is not None else "\n".join(block["text"] for block in note["blocks"])
        outputs = rows if rows is not None else [{
            "topic": block["topic"], "kind": "AUTHOR_OPINION", "claim": block["text"],
            "quote": block["text"], "source_block_ids": [index], "confidence": "MEDIUM",
            "applicable_conditions": [], "extraction_basis": "合成正文逐字引用",
        } for index, block in enumerate(note["blocks"])]
        result = EvidenceExtractor(MockLLMProvider({"extract_evidence": {"claims": outputs}}),
                                   clock=lambda: self.now).extract(
            source_id=note["source_id"], source_title=note["title"], body=text, dom_body=dom,
            completeness="PARTIAL_TEXT", fetched_at=self.now.isoformat(),
            source_published_at=note.get("published_at"), source_type="SYNTHETIC",
            destination=self.request.destination, policy=policy or self.policy, image_count=image_count,
        )
        self.bodies[note["source_id"]] = result.canonical.text if result.canonical else ""
        return result

    def bundles(self, notes: list[dict[str, Any]] | None = None) -> tuple[EvidenceBundle, ...]:
        result = []
        for note in notes if notes is not None else deepcopy(self.spec["notes"]):
            data = self.extract(note).bundle.to_dict()
            # The benchmark fixture explicitly supplies this author metadata. Never
            # infer it from publication or claim that the extractor discovered it.
            data["travel_occurred_at"] = note.get("travel_occurred_at")
            if data["travel_occurred_at"]:
                data["missing_fields"] = [code for code in data["missing_fields"] if code != "TRAVEL_TIME_UNKNOWN"]
            result.append(EvidenceBundle(data))
        return tuple(result)

    def custom(self, index: int, topic: str, *texts: str) -> dict[str, Any]:
        note: dict[str, Any] = deepcopy(self.spec["notes"][index])
        note["blocks"] = [{"topic": topic, "text": text} for text in texts]
        return note

    def report(self, evidence: tuple[EvidenceBundle, ...], request: ResearchRequest | None = None) -> ResearchReport:
        question = request or self.request
        coverage_gaps = SufficiencyEvaluator(lambda: self.now).gaps(question, evidence)
        material_gaps = [ResearchService._material_gap(code)
                         for bundle in evidence for code in bundle["missing_fields"]]
        gaps = tuple({gap.gap_id: gap for gap in (*coverage_gaps, *material_gaps)}.values())
        return ResearchReport("synthetic-benchmark", 0, "synthetic-run", question, evidence, gaps,
                              "BUDGET_EXHAUSTED" if coverage_gaps else "EVIDENCE_SUFFICIENT",
                              {"search": 0, "detail": 0}, len(evidence), assessed_at=self.now.isoformat())

    def grounding(self, evidence: tuple[EvidenceBundle, ...]) -> dict[str, Any]:
        total = supported = located = 0
        for bundle in evidence:
            body = self.bodies.get(bundle["source_id"], "")
            for claim in bundle["claims"]:
                total += 1
                located += int(has_locator(claim))
                match = re.search(r":chars:(\d+)-(\d+)$", claim["locator"])
                supported += int(bool(match and body[int(match[1]):int(match[2])] == claim["text"]))
        return {"evaluated_claim_instances": total, "unsupported_claims": total - supported,
                "located_claims": located, "locator_coverage": located / total if total else None}

    def evaluate(self, scenario: str) -> dict[str, Any]:
        self.bodies = {}
        evidence = self.bundles()
        observed: dict[str, Any] = {}
        if scenario in {"duration_conflict", "transport_conflict"}:
            topic, texts = ("DURATION", ("青岚环线五天比较宽松", "青岚环线5天很赶")) if scenario == "duration_conflict" else (
                "TRANSPORT", ("青岚环线没有班车", "青岚环线可以乘班车"))
            evidence = self.bundles([self.custom(i, topic, text) for i, text in enumerate(texts)])
            observed["averaged_claim"] = any("适中" in claim["text"] for b in evidence for claim in b["claims"])
        elif scenario in {"within_source_duplicate", "cross_source_duplicate"}:
            notes = [self.custom(0, "DURATION", "五天比较宽松", "5天比较宽松")]
            if scenario == "cross_source_duplicate":
                notes = [self.custom(i, "DURATION", "五天比较宽松") for i in (0, 1)]
            evidence = self.bundles(notes)
        elif scenario == "missing_duration":
            notes = deepcopy(self.spec["notes"])
            for note in notes:
                note["blocks"] = [row for row in note["blocks"] if row["topic"] != "DURATION"]
            evidence = self.bundles(notes)
        elif scenario in {"image_required", "hallucinated_claim", "invalid_block", "dom_overlap", "dom_conflict", "unknown_rights"}:
            note = self.custom(0, "ROUTE", "青岚环线经过雾谷")
            options: dict[str, Any] = {}
            if scenario == "image_required":
                note = self.custom(0, "ROUTE", "路线见图2")
                options["image_count"] = 2
            if scenario in {"hallucinated_claim", "invalid_block"}:
                options["rows"] = [{"topic": "ROUTE", "kind": "AUTHOR_OPINION",
                    "claim": "模型补造的神秘景点" if scenario == "hallucinated_claim" else note["blocks"][0]["text"],
                    "quote": "模型补造的神秘景点" if scenario == "hallucinated_claim" else note["blocks"][0]["text"],
                    "source_block_ids": [999] if scenario == "invalid_block" else [0],
                    "confidence": "HIGH", "applicable_conditions": [], "extraction_basis": "合成不合格输出"}]
            if scenario == "dom_overlap":
                options["dom"] = "青岚环线"
            if scenario == "dom_conflict":
                options["dom"] = "住宿费用八十元"
            if scenario == "unknown_rights":
                options["policy"] = self.unknown_policy
            extracted = self.extract(note, **options)
            evidence = (extracted.bundle,)
            assessments: dict[str, Any] = extracted.bundle.get("claim_metadata", {})
            first_assessment: dict[str, Any] = next(iter(assessments.values()), {})
            observed.update(rejected_claims=extracted.rejected_claims,
                            extraction_mode=extracted.mode, provider_called=extracted.provider_called,
                            canonical_relation=extracted.canonical.relation if extracted.canonical else None,
                            completeness=extracted.bundle["completeness"],
                            confidence=first_assessment.get("confidence_level"),
                            conflict_gap="BODY_VERSIONS_CONFLICT" in extracted.gaps,
                            image_gap="IMAGE_INFORMATION_REQUIRED" in extracted.gaps)
            if scenario == "unknown_rights":
                with Database(Path(":memory:"), clock=lambda: self.now) as db:
                    store = EvidenceStore(db)
                    run = store.begin("rights", 0, self.request.to_dict(), "synthetic")
                    observed["storage_blocked"] = False
                    try:
                        store.save_evidence(run, 0, extracted.bundle, self.unknown_policy, {})
                    except PermissionError:
                        observed["storage_blocked"] = True
        elif scenario == "single_source":
            evidence = evidence[:1]
        elif scenario == "publication_is_not_travel":
            note = deepcopy(self.spec["notes"][0])
            note["travel_occurred_at"] = None
            evidence = self.bundles([note])
            observed.update(publication_preserved=evidence[0]["source_published_at"] == note["published_at"],
                            travel_unknown=evidence[0]["travel_occurred_at"] is None)
        elif scenario in {"candidate_diversity", "selector_fallback"}:
            candidates = (Candidate("synthetic:rank-a", "合成地区五天环线路线攻略", "normal", True),
                          Candidate("synthetic:rank-b", "合成地区5天环线路线攻略", "normal", True),
                          Candidate("synthetic:rank-c", "合成地区班车公共交通体验", "normal", True))
            selector = CandidateSelector(MockLLMProvider() if scenario == "selector_fallback" else None,
                                         allow_external=scenario == "selector_fallback")
            selected = selector.select(candidates, self.request, (), set())
            observed.update(first_two=[row.candidate.source_id for row in selected[:2]],
                            selector_mode=selector.last_mode, candidate_count=len(selected))
        elif scenario in {"dynamic_price", "stale_experience"}:
            if scenario == "dynamic_price":
                evidence = self.bundles([self.custom(0, "PRICE", "作者当时支付门票八十元")])
            else:
                changed = evidence[0].to_dict()
                changed["fetched_at"] = (self.now - timedelta(days=181)).isoformat()
                evidence = (EvidenceBundle(changed),)
            freshness = assess_freshness(evidence[0]["claims"][0], evidence[0], now=self.now)
            observed.update(freshness_category=freshness.category, freshness_status=freshness.status)
        if scenario in {"cache_hit", "zero_budget", "clear_cache", "combined_constraints"}:
            with Database(Path(":memory:"), clock=lambda: self.now) as db:
                store = EvidenceStore(db)
                if scenario != "zero_budget":
                    run = store.begin("benchmark", 0, self.request.to_dict(), "synthetic")
                    for bundle in evidence:
                        store.save_evidence(run, 0, bundle, self.policy, {})
                    store.finish(run, 0, [], self.report(evidence).safe_summary())
                reader = NoAccessReader()
                service = ResearchService(store, reader, EvidenceExtractor(), self.policy)
                request = replace(self.request, days=5, no_self_drive=True) if scenario == "combined_constraints" else self.request
                report = service.run(request, research_id="benchmark", revision=int(scenario == "combined_constraints"),
                                     account_scope="synthetic", budget=ResearchBudget(1, 2) if scenario == "cache_hit" else ResearchBudget(0, 0))
                evidence = report.evidence
                observed.update(reader.calls)
                observed.update(stop_reason=report.stop_reason, has_gap=bool(report.gaps),
                                retained_sources=len(report.evidence), days_gap=any(g.gap_id == "DAYS_FIT" for g in report.gaps),
                                transport_gap=any(g.gap_id == "NON_SELF_DRIVE" for g in report.gaps))
                if scenario == "clear_cache":
                    store.clear_research_cache("synthetic")
                    observed.update(source_count_after=len(store.lookup("benchmark", None, "synthetic")),
                                    report_after=store.load_report("benchmark", "synthetic") is not None)
        question = replace(self.request, days=5) if scenario == "five_days" else (
            replace(self.request, no_self_drive=True) if scenario == "no_self_drive" else self.request)
        report = self.report(evidence, question)
        summary = report.safe_summary()
        coverage = {row.question_id: row.status for row in evaluate_coverage(evidence, now=self.now)}
        gaps = {gap.gap_id for gap in report.gaps}
        observed = {"direction_count": summary["candidate_direction_count"],
                    "all_supported": all(value == "SUPPORTED" for value in coverage.values()),
                    "conflict_count": len(evidence_conflicts(evidence)),
                    "duration_coverage": coverage["Q3_DURATION"], "limitation_coverage": coverage["Q4_LIMITATIONS"],
                    "route_coverage": coverage["Q1_ROUTES"], "duration_gap": "DURATION" in gaps,
                    "source_gap": "SOURCE_CORROBORATION" in gaps, "sufficient": not report.gaps,
                    "days_gap": "DAYS_FIT" in gaps, "transport_gap": "NON_SELF_DRIVE" in gaps,
                    "retained_sources": len(evidence), "source_conditions_invented": any(b["applicable_conditions"] for b in evidence),
                    "evidence_count": summary["evidence_count"], "source_count": len(evidence),
                    "cluster_count": len(claim_clusters(evidence)),
                    "confirmed_independent_sources": source_independence(evidence).confirmed_independent_sources,
                    **observed, **self.grounding(evidence)}
        return observed

    def run(self) -> dict[str, Any]:
        cases = []
        for case in self.spec["cases"]:
            try:
                observed = self.evaluate(case["scenario"])
                expected = {**case["expect"], "unsupported_claims": 0}
                checks = [{"field": key, "expected": value, "observed": observed.get(key),
                           "passed": observed.get(key) == value} for key, value in expected.items()]
                if observed["evaluated_claim_instances"]:
                    checks.append({"field": "locator_coverage", "expected": 1.0,
                                   "observed": observed["locator_coverage"], "passed": observed["locator_coverage"] == 1.0})
                cases.append({"id": case["id"], "scenario": case["scenario"], "purpose": case["purpose"],
                              "status": "PASS" if all(c["passed"] for c in checks) else "FAIL",
                              "checks": checks, "metrics": observed})
            except Exception as error:
                cases.append({"id": case["id"], "scenario": case["scenario"], "purpose": case["purpose"],
                              "status": "FAIL", "error": type(error).__name__, "checks": []})
        claims = sum(case.get("metrics", {}).get("evaluated_claim_instances", 0) for case in cases)
        located = sum(case.get("metrics", {}).get("located_claims", 0) for case in cases)
        return {"is_synthetic": True, "real_model_verified": False, "live_operations": 0,
                "scenario_count": len(cases), "passed": sum(case["status"] == "PASS" for case in cases),
                "failed": sum(case["status"] == "FAIL" for case in cases),
                "evaluated_claim_instances": claims,
                "unsupported_claims": sum(case.get("metrics", {}).get("unsupported_claims", 0) for case in cases),
                "locator_coverage": located / claims if claims else None, "cases": cases}

    def example_markdown(self) -> str:
        if self.policy["basis"] != "SYNTHETIC" or not self.policy["allow_export"]:
            raise PermissionError("合成示例导出需要明确的合成资料策略")
        evidence = self.bundles()
        first = self.report(evidence)
        incremental = self.report(evidence, replace(self.request, days=5, no_self_drive=True))
        return ("# T06 合成研究示例（非真实攻略）\n\n"
                "仅使用 fixtures/research-quality-benchmark.json 的虚构地区与 Mock 提取。"
                "没有访问小红书或真实模型；不能据此宣布 G1 真实质量通过。\n\n"
                + render_material_report(first.material_view())
                + "\n## 追加：只有 5 天，而且不想自驾\n\n"
                "保留上述来源与证据，未据用户要求改写作者适用条件。此离线增量不访问站点。\n\n"
                + "\n".join(f"- {gap.description}" for gap in incremental.gaps) + "\n")
