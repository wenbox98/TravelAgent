import json
from typing import Protocol
from travel_agent.domain.models import DomainModel
from travel_agent.settings import PROJECT_ROOT


class LLMProvider(Protocol):
    def overview(self) -> DomainModel: ...


class MockLLMProvider:
    def overview(self):
        data = json.loads((PROJECT_ROOT / "fixtures/overview.json").read_text(encoding="utf-8"))
        if data["is_synthetic"] is not True:
            raise ValueError("mock 输出必须为合成资料")
        return DomainModel.parse("OverviewResult", data)
