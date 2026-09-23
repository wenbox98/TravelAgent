import json
from typing import Any, cast
from travel_agent.domain.models import DomainModel
from travel_agent.providers.llm import LLMError, LLMProvider, validate_structured
from travel_agent.settings import PROJECT_ROOT

__all__ = ["LLMProvider", "MockLLMProvider"]


class MockLLMProvider:
    is_external = False
    is_mock = True

    def __init__(self, outputs: dict[str, dict[str, Any]] | None = None) -> None:
        self._outputs = outputs or {}

    def overview(self) -> DomainModel:
        data = json.loads((PROJECT_ROOT / "fixtures/overview.json").read_text(encoding="utf-8"))
        if data["is_synthetic"] is not True:
            raise ValueError("mock 输出必须为合成资料")
        return cast(DomainModel, DomainModel.parse("OverviewResult", data))

    def structured(
        self, task: str, payload: dict[str, Any], schema: dict[str, Any],
    ) -> dict[str, Any]:
        if payload.get("is_synthetic") is not True:
            raise LLMError("LLM_POLICY_BLOCKED")
        if task not in self._outputs:
            raise LLMError("LLM_UNAVAILABLE")
        return validate_structured(self._outputs[task], schema)
