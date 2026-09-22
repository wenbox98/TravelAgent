from typing import Protocol
from travel_agent.domain.models import FetchResult


class XhsReadonlyAdapter(Protocol):
    """Internal service interface. Never expose this adapter directly to an LLM."""
    def search(self, query: str) -> FetchResult: ...
    def detail(self, note_handle: str) -> FetchResult: ...
