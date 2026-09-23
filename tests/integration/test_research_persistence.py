"""Two independent processes, real SQLite, synthetic rights, and no browser/network."""

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys


_CHILD = r'''
import json
import os
from pathlib import Path
import sys
from dataclasses import replace
from types import SimpleNamespace

def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendto"}:
        raise AssertionError("offline child forbids network")
sys.addaudithook(deny_network)

from travel_agent.domain.models import EvidenceBundle, SourcePolicy
from travel_agent.persistence.database import Database
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.models import Candidate, DetailMaterial, ResearchBudget, ResearchRequest
from travel_agent.research.service import ResearchService
from travel_agent.research.store import EvidenceStore

mode, database, fixture = sys.argv[1:]
data = json.loads(Path(fixture).read_text(encoding="utf-8"))
policy = SourcePolicy(data["policy"])
request = ResearchRequest(destination="synthetic-region")
with Database(Path(database)) as db:
    store = EvidenceStore(db)
    if mode == "A":
        by_source = {item["source_id"]: item for item in data["evidence"]}
        class SyntheticReader:
            text_first = False
            def __init__(self): self.calls = {"connect": 0, "search": 0, "detail": 0}
            def connect(self): self.calls["connect"] += 1
            def search(self, query):
                self.calls["search"] += 1
                return tuple(Candidate(source, "synthetic-region " + source, "normal", True)
                             for source in by_source)
            def detail(self, candidate, number):
                self.calls["detail"] += 1
                item = by_source[candidate.source_id]
                return DetailMaterial(item["source_id"], item["source_title"],
                                      "\n".join(claim["text"] for claim in item["claims"]),
                                      item["completeness"], item["fetched_at"], source_type="SYNTHETIC")
            def disable_text_first(self): raise AssertionError("no fallback")
        class FixtureExtractor:
            def extract(self, **kwargs):
                return SimpleNamespace(bundle=EvidenceBundle(by_source[kwargs["source_id"]]),
                                       gaps=(), mode="MOCK")
        reader = SyntheticReader()
        service = ResearchService(store, reader, FixtureExtractor(), policy)
        report = service.run(request, research_id="cross-process", revision=0,
                             account_scope="synthetic-scope", budget=ResearchBudget(1, 2))
        assert report.stop_reason == "EVIDENCE_SUFFICIENT", report.safe_summary()
        assert report.operations == {"search": 1, "detail": 2}
        assert reader.calls == {"connect": 1, "search": 1, "detail": 2}
        print(json.dumps({"pid": os.getpid(), "written": len(report.evidence),
                          "operations": report.operations, "calls": reader.calls}))
    else:
        class NoReader:
            text_first = False
            def __init__(self): self.calls = {"connect": 0, "search": 0, "detail": 0}
            def forbidden(self, kind):
                self.calls[kind] += 1
                raise AssertionError("sufficient cache must not touch reader")
            def connect(self): self.forbidden("connect")
            def search(self, query): self.forbidden("search")
            def detail(self, candidate, number): self.forbidden("detail")
            def disable_text_first(self): raise AssertionError("no fallback")
        loaded = store.lookup("cross-process", "synthetic-region", "synthetic-scope")
        assert [bundle.to_dict() for bundle in loaded] == data["evidence"]
        assert store.load_report("cross-process", "synthetic-scope") is not None
        reader = NoReader()
        service = ResearchService(store, reader, EvidenceExtractor(), policy)
        # Positive budget is intentional: sufficiency, rather than zero budget, prevents connect.
        report = service.run(request, research_id="cross-process", revision=0,
                             account_scope="synthetic-scope", budget=ResearchBudget(1, 2))
        assert report.stop_reason == "EVIDENCE_SUFFICIENT", report.safe_summary()
        assert reader.calls == {"connect": 0, "search": 0, "detail": 0}
        zero = service.run(request, research_id="cross-process", revision=0,
                           account_scope="synthetic-scope", budget=ResearchBudget(0, 0))
        restored = store.load_report("cross-process", "synthetic-scope")
        assert restored["summary"]["coverage"] == zero.safe_summary()["coverage"]
        incremental = service.run(replace(request, days=5, no_self_drive=True),
                                  research_id="cross-process", revision=1,
                                  account_scope="synthetic-scope", budget=ResearchBudget(0, 0))
        assert [b.to_dict() for b in incremental.evidence] == [b.to_dict() for b in report.evidence]
        assert {"DAYS_FIT", "NON_SELF_DRIVE"} <= {gap.gap_id for gap in incremental.gaps}
        assert reader.calls == {"connect": 0, "search": 0, "detail": 0}
        assert zero.operations == incremental.operations == {"search": 0, "detail": 0}
        print(json.dumps({"pid": os.getpid(), "calls": reader.calls,
                          "operations": report.operations, "summary": report.safe_summary(),
                          "zero_budget": zero.operations, "incremental": incremental.operations,
                          "restored": store.load_report("cross-process", "synthetic-scope") is not None}))
'''


def _evidence(fixture_data):
    sentences = (
        ("合成青岭路线：连接山谷和湖区", "合成青岭路线：能够观察高原湖泊", "合成青岭路线：作者用了五天", "合成青岭路线：需要提前安排包车"),
        ("虚构苍河环线：经过草原", "虚构苍河环线：体验侧重草原漫步", "虚构苍河环线：作者停留七天", "虚构苍河环线：班车每天两趟"),
    )
    result = []
    for index, texts in enumerate(sentences):
        data = fixture_data("evidence.json")
        source = f"synthetic-source-{index}"
        data.update(source_id=source, destination="synthetic-region", missing_fields=[],
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    travel_occurred_at="2026-09-01T00:00:00+08:00", claims=[], claim_metadata={})
        body_digest = sha256("\n".join(texts).encode()).hexdigest()
        offset = 0
        for block, (topic, text) in enumerate(zip(("ROUTE", "EXPERIENCE", "DURATION", "TRANSPORT"), texts, strict=True)):
            claim_id = f"claim-{index}-{block}"
            locator = f"note-body:v2:STATE:{body_digest}:chars:{offset}-{offset + len(text)}"
            offset += len(text) + 1
            data["claims"].append({
                "claim_id": claim_id, "source_id": source, "topic": topic, "text": text,
                "kind": "AUTHOR_OPINION", "locator": locator, "support": "SUPPORTED",
                "valid_from": None, "valid_until": None, "confidence": 0.6,
            })
            data["claim_metadata"][claim_id] = {
                "source_block_ids": [block], "body_origin": "STATE", "extraction_method": "MOCK",
                "extraction_basis": "合成正文定位夹具", "confidence_level": "MEDIUM",
                "applicable_conditions": [], "canonical_relation": "EQUAL",
                "truncation_risk": False, "block_locators": [locator],
            }
        result.append(data)
    return result


def test_two_independent_processes_restore_metadata_and_sufficient_cache(tmp_path, fixture_data):
    fixture = tmp_path / "synthetic-input.json"
    fixture.write_text(json.dumps({"policy": fixture_data("policies.json")["policies"][0],
                                   "evidence": _evidence(fixture_data)}, ensure_ascii=False), encoding="utf-8")
    project = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(project / "apps/api"), str(project / "integrations/xhs-sidecar")))
    env["PYTHONIOENCODING"] = "utf-8"
    outputs = []
    for mode in ("A", "B"):
        process = subprocess.run([sys.executable, "-c", _CHILD, mode,
                                  str(tmp_path / "cross-process.sqlite3"), str(fixture)],
                                 cwd=project, env=env, text=True, encoding="utf-8",
                                 capture_output=True, timeout=30, check=False)
        assert process.returncode == 0, (mode, process.stderr)
        outputs.append(json.loads(process.stdout))
    first, second = outputs
    assert first["pid"] != second["pid"]
    assert first["calls"] == {"connect": 1, "search": 1, "detail": 2}
    assert second["calls"] == {"connect": 0, "search": 0, "detail": 0}
    assert second["operations"] == {"search": 0, "detail": 0}
    assert second["restored"] is True
    assert second["summary"]["evidence_count"] == 8
