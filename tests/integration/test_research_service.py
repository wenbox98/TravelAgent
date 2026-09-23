"""SQLite + bounded research orchestration, entirely synthetic source material."""

from pathlib import Path

import pytest

from travel_agent.domain.models import EvidenceBundle, SourcePolicy
from travel_agent.persistence.database import Database
from travel_agent.research.extractor import EvidenceExtractor, ExtractionResult, body_blocks
from travel_agent.research.models import (
    Candidate, DetailMaterial, ResearchBudget, ResearchRequest, ResearchStopped,
)
from travel_agent.research.service import ResearchService
from travel_agent.research.planning import CandidateSelector
from travel_agent.research.store import EvidenceStore

REQUEST = ResearchRequest(departure="成都", destination="川西", time_hint="国庆")
TOPICS = ("ROUTE", "EXPERIENCE", "DURATION", "TRANSPORT")


def evidence(source_id="xhs:synthetic-a", topics=TOPICS, missing=()):
    texts = ({"ROUTE": "合成川西路线甲沿河出发", "EXPERIENCE": "作者体验了合成徒步",
              "DURATION": "作者用了7天", "TRANSPORT": "作者使用自驾交通"}
             if source_id.endswith("-a") else
             {"ROUTE": "合成川西乙环线围绕湖区", "EXPERIENCE": "另一作者体验合成温泉",
              "DURATION": "另一作者停留4天", "TRANSPORT": "另一作者乘坐合成班车"})
    direction = "甲环线" if source_id.endswith("-a") else "乙环线"
    texts = {topic: f"{direction}：{text}" for topic, text in texts.items()}
    blocks = body_blocks("\n".join(texts[topic] for topic in TOPICS), origin="STATE", normalized=True)
    claims = [{
        "claim_id": f"claim-{source_id}-{topic}", "source_id": source_id, "topic": topic,
        "text": texts[topic], "kind": "AUTHOR_OPINION", "support": "SUPPORTED",
        "locator": blocks[TOPICS.index(topic)].locator, "confidence": 0.6,
        "valid_from": None, "valid_until": None,
    } for topic in topics]
    return EvidenceBundle({
        "source_id": source_id, "source_type": "SYNTHETIC", "source_title": "合成川西研究",
        "destination": "川西", "applicable_conditions": [], "completeness": "PARTIAL_TEXT",
        "fetched_at": "2026-09-21T10:00:00+08:00", "source_published_at": None,
        "travel_occurred_at": "2026-09-20T00:00:00+00:00", "policy_id": "synthetic-all",
        "is_synthetic": True, "missing_fields": list(missing), "claims": claims,
        "claim_metadata": {c["claim_id"]: {
            "source_block_ids": [TOPICS.index(c["topic"])], "body_origin": "STATE",
            "extraction_method": "MOCK", "confidence_level": "MEDIUM",
            "extraction_basis": "合成正文逐字表达", "applicable_conditions": [],
            "canonical_relation": "STATE_ONLY", "truncation_risk": True,
            "block_locators": [c["locator"]],
        } for c in claims},
    })


class StubExtractor:
    """Only synthetic fixtures may supply high-confidence acceptance coverage."""
    def __init__(self, topics=TOPICS, gaps=()):
        self.topics, self.gaps, self.calls = topics, gaps, 0
    def extract(self, **args):
        assert args["source_type"] == "SYNTHETIC"
        self.calls += 1
        return ExtractionResult(evidence(args["source_id"], self.topics, self.gaps),
                                body_blocks(args["body"]), tuple(self.gaps), "MOCK", False, 0)


class FakeReader:
    def __init__(self, candidates=None, actions=(), callback=None):
        self.text_first = True
        self.candidates = candidates if candidates is not None else (
            Candidate("xhs:synthetic-a", "川西路线甲攻略", "normal", True),
            Candidate("xhs:synthetic-b", "川西体验乙攻略", "normal", True),
            Candidate("xhs:synthetic-c", "川西交通丙攻略", "normal", True),
        )
        self.actions = list(actions)
        self.callback = callback
        self.connects = self.disabled = 0
        self.searches, self.details = [], []
    def connect(self):
        self.connects += 1
    def search(self, query):
        self.searches.append(query)
        return self.candidates
    def detail(self, candidate, detail_number):
        self.details.append((candidate.source_id, detail_number))
        if self.callback:
            self.callback()
        if self.actions:
            action = self.actions.pop(0)
            if isinstance(action, Exception):
                raise action
            if action is not None:
                return action
        return DetailMaterial(
            candidate.source_id, candidate.title,
            "\n".join(c["text"] for c in evidence(candidate.source_id)["claims"]),
            "PARTIAL_TEXT", "2026-09-22T10:00:00+08:00", source_type="SYNTHETIC",
        )
    def disable_text_first(self):
        self.disabled += 1
        self.text_first = False


@pytest.fixture
def environment(clock, fixture_data):
    with Database(Path(":memory:"), clock=clock) as database:
        yield EvidenceStore(database), SourcePolicy(fixture_data("policies.json")["policies"][0])


def seed(store, policy, bundle, *, revision=0):
    run_id = store.begin("research-test", revision, REQUEST.to_dict(), "synthetic-local")
    assert store.save_evidence(run_id, revision, bundle, policy, {
        "completeness": bundle["completeness"], "body_chars": 50,
        "image_count": 0, "identity_match": True, "published_at": None,
        "fetched_at": bundle["fetched_at"], "extraction_mode": "MOCK",
        "evidence_count": len(bundle["claims"]),
    })
    return run_id


def run(service, *, revision=1, request=REQUEST, budget=None):
    return service.run(request, research_id="research-test", revision=revision,
                       account_scope="synthetic-local", budget=budget or ResearchBudget(1, 2))


def test_r01_sufficient_sqlite_cache_needs_no_connect_search_or_detail(environment):
    store, policy = environment
    seed(store, policy, evidence())
    seed(store, policy, evidence("xhs:synthetic-b"))
    reader = FakeReader()
    report = run(ResearchService(store, reader, StubExtractor(), policy))
    assert report.stop_reason == "EVIDENCE_SUFFICIENT" and report.cache_sources == 2
    assert report.operations == {"search": 0, "detail": 0}
    assert reader.connects == 0 and reader.searches == [] and reader.details == []


def test_r02_partial_cache_searches_only_remaining_gap(environment):
    store, policy = environment
    seed(store, policy, evidence(topics=("ROUTE", "EXPERIENCE", "DURATION")))
    reader = FakeReader(candidates=(Candidate("xhs:synthetic-b", "川西交通班车攻略", "normal", True),))
    report = run(ResearchService(store, reader, StubExtractor(topics=("TRANSPORT",)), policy))
    # A second source's unassociated transport clue cannot fill the first route's gap.
    assert report.stop_reason == "BUDGET_EXHAUSTED"
    assert {"TRANSPORT", "DIRECTION_ASSOCIATION"}.issubset({g.gap_id for g in report.gaps})
    assert len(reader.searches) == 1 and "交通" in reader.searches[0]
    assert "川西 国庆 攻略" not in reader.searches[0]
    assert report.cache_sources == 1 and len(report.evidence) == 2


def test_r04_repeated_source_is_detailed_once(environment, clock):
    store, policy = environment
    candidate = Candidate("xhs:synthetic-a", "川西路线甲攻略", "normal", True)
    reader = FakeReader(candidates=(candidate, candidate, Candidate(
        candidate.source_id, "川西另一个标题", "normal", True
    )))
    report = run(ResearchService(store, reader, EvidenceExtractor(clock=clock), policy))
    assert len(reader.details) == 1 and report.operations == {"search": 1, "detail": 1}
    assert report.stop_reason == "BUDGET_EXHAUSTED"


def test_r09_sufficient_first_detail_stops_before_second(environment):
    store, policy = environment
    seed(store, policy, evidence())  # Complete first direction, still only one source.
    reader = FakeReader()
    report = run(ResearchService(store, reader, StubExtractor(), policy))
    assert report.stop_reason == "EVIDENCE_SUFFICIENT" and len(reader.details) == 1
    assert report.operations == {"search": 1, "detail": 1}


@pytest.mark.parametrize("budget,expected", [(ResearchBudget(1, 2), 2), (ResearchBudget(3, 1), 1)])
def test_r10_r11_budget_caps_apply_to_actual_reader_invocations(environment, clock, budget, expected):
    store, policy = environment
    reader = FakeReader()
    report = run(ResearchService(store, reader, EvidenceExtractor(clock=clock), policy), budget=budget)
    assert report.stop_reason == "BUDGET_EXHAUSTED"
    assert report.operations == {"search": 1, "detail": expected}
    assert len(reader.searches) == 1 and len(reader.details) == expected
    assert report.gaps and all(bundle["completeness"] == "PARTIAL_TEXT" for bundle in report.evidence)


@pytest.mark.parametrize("reason", ["NEED_LOGIN", "VERIFICATION_REQUIRED"])
def test_r12_pause_reason_never_triggers_fallback_even_if_mislabeled(environment, reason):
    store, policy = environment
    reader = FakeReader(actions=[ResearchStopped(reason, fallback_eligible=True)])
    report = run(ResearchService(store, reader, StubExtractor(), policy))
    assert report.stop_reason == reason and len(reader.details) == 1
    assert reader.disabled == 0 and report.operations == {"search": 1, "detail": 1}


def test_r13_r14_zero_budget_incremental_request_preserves_evidence(environment):
    store, policy = environment
    seed(store, policy, evidence())
    seed(store, policy, evidence("xhs:synthetic-b"))
    reader = FakeReader()
    service = ResearchService(store, reader, StubExtractor(), policy)
    original = run(service, budget=ResearchBudget(0, 0))
    increment = run(service, revision=2, request=ResearchRequest(
        departure="成都", destination="川西", time_hint="国庆", days=5, no_self_drive=True
    ), budget=ResearchBudget(0, 0))
    assert original.stop_reason == "EVIDENCE_SUFFICIENT"
    assert increment.stop_reason == "BUDGET_EXHAUSTED"
    assert [b.to_dict() for b in increment.evidence] == [b.to_dict() for b in original.evidence]
    assert {g.gap_id for g in increment.gaps} == {"DAYS_FIT", "NON_SELF_DRIVE"}
    assert reader.connects == 0 and not reader.searches and not reader.details


def test_r15_late_detail_of_old_revision_never_saves_evidence(environment):
    store, policy = environment
    def newer_revision():
        store.begin("research-test", 2, REQUEST.to_dict(), "synthetic-local")
    reader, extractor = FakeReader(callback=newer_revision), StubExtractor()
    report = run(ResearchService(store, reader, extractor, policy))
    assert report.obsolete is True and report.diagnostic == "STALE_REVISION"
    assert report.stop_reason == "ERROR" and extractor.calls == 0
    assert store.lookup("research-test", "川西", "synthetic-local") == ()


def test_r18_one_technical_fallback_is_same_source_and_charged(environment):
    store, policy = environment
    reader = FakeReader(actions=[ResearchStopped("SOURCE_UNAVAILABLE", "PARSE_ERROR", fallback_eligible=True)])
    report = run(ResearchService(store, reader, StubExtractor(), policy))
    assert report.stop_reason == "BUDGET_EXHAUSTED" and reader.disabled == 1
    assert "SOURCE_CORROBORATION" in {gap.gap_id for gap in report.gaps}
    assert report.operations == {"search": 1, "detail": 2}
    assert len({source for source, _ in reader.details}) == 1
    assert [number for _, number in reader.details] == [1, 2]


def test_fallback_cannot_exceed_one_detail_budget(environment):
    store, policy = environment
    reader = FakeReader(actions=[ResearchStopped("SOURCE_UNAVAILABLE", "PARSE_ERROR", fallback_eligible=True)])
    report = run(ResearchService(store, reader, StubExtractor(), policy), budget=ResearchBudget(1, 1))
    assert report.stop_reason == "SOURCE_UNAVAILABLE" and reader.disabled == 0
    assert len(reader.details) == 1


def test_failed_fallback_is_not_repeated_again(environment):
    store, policy = environment
    failure = ResearchStopped("SOURCE_UNAVAILABLE", "PARSE_ERROR", fallback_eligible=True)
    reader = FakeReader(actions=[failure, failure])
    report = run(ResearchService(store, reader, StubExtractor(), policy))
    assert report.stop_reason == "SOURCE_UNAVAILABLE"
    assert len(reader.details) == 2 and reader.disabled == 1


def test_r19_r22_report_keeps_unknown_network_separate_and_lists_real_gaps(environment, clock):
    store, policy = environment
    reader = FakeReader(candidates=(Candidate("xhs:synthetic-a", "川西路线甲攻略", "normal", True),))
    report = run(ResearchService(store, reader, EvidenceExtractor(clock=clock), policy))
    summary = report.safe_summary()
    assert summary["operations"] == {"search": 1, "detail": 1}
    assert summary.get("actual_request_events") is None
    assert summary["is_final_itinerary"] is False and summary["gaps"]
    assert "LOCAL_EXTRACTIVE" in summary["extraction_modes"]
    assert "xhs:synthetic-a" not in str(summary) and "路线甲沿河出发" not in str(summary)


def test_image_information_gap_survives_cache_and_prevents_false_sufficiency(environment):
    store, policy = environment
    seed(store, policy, evidence(missing=("IMAGE_INFORMATION_REQUIRED",)))
    reader = FakeReader()
    report = run(ResearchService(store, reader, StubExtractor(), policy), budget=ResearchBudget(0, 0))
    assert report.stop_reason != "EVIDENCE_SUFFICIENT"
    assert "IMAGE_INFORMATION_REQUIRED" in {gap.gap_id for gap in report.gaps}
    assert reader.connects == 0 and not reader.searches and not reader.details


def test_model_permission_is_rechecked_after_search_before_sending_titles(environment):
    store, policy = environment
    class NoExternalCall:
        def structured(self, *args):
            pytest.fail("expired policy must not send metadata to external model")
    reader = FakeReader()
    selector = CandidateSelector(NoExternalCall(), allow_external=True)
    service = ResearchService(store, reader, StubExtractor(), policy, selector=selector)
    original = reader.search
    def expire_then_return(query):
        expired = policy.to_dict()
        expired["expires_at"] = "2026-09-21T00:00:00Z"
        service.policy = SourcePolicy(expired)
        return original(query)
    reader.search = expire_then_return
    run(service)
    assert selector.allow_external is False


def test_cached_report_preserves_material_uncertainty_without_re_extraction(environment, clock):
    store, policy = environment
    reader = FakeReader()
    service = ResearchService(store, reader, EvidenceExtractor(clock=clock), policy)
    first = run(service)
    before = (reader.connects, len(reader.searches), len(reader.details))
    cached = run(service, budget=ResearchBudget(0, 0))
    assert {gap.gap_id for gap in cached.gaps} == {gap.gap_id for gap in first.gaps}
    assert "LOCAL_EXTRACTIVE_ONLY" in {gap.gap_id for gap in cached.gaps}
    assert "CONTENT_INCOMPLETE" in {gap.gap_id for gap in cached.gaps}
    assert cached.operations == {"search": 0, "detail": 0}
    assert before == (reader.connects, len(reader.searches), len(reader.details))
