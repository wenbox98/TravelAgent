"""Normal research evidence cannot enter a store without a source locator."""

from pathlib import Path

import pytest

from travel_agent.domain.models import EvidenceBundle, SourcePolicy
from travel_agent.persistence.database import Database
from travel_agent.research.store import EvidenceStore


@pytest.mark.parametrize("locator", [None, ""])
def test_q03_locatorless_evidence_rejected_before_persistence(fixture_data, clock, locator):
    data = fixture_data("evidence.json")
    data["claims"][0]["locator"] = locator
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        run = store.begin("locator-test", 0, {}, "synthetic-local")
        with pytest.raises(ValueError):
            store.save_evidence(run, 0, EvidenceBundle(data),
                                SourcePolicy(fixture_data("policies.json")["policies"][0]), {})
        assert db.connection.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
        assert db.connection.execute("SELECT count(*) FROM source_snapshots").fetchone()[0] == 0
