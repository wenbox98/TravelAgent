from threading import Lock
from typing import Protocol

from .models import NetworkSnapshot, RequestCounts, ResourceCategory


class NetworkObserver(Protocol):
    def navigation(self) -> None: ...
    def request(self, category: ResourceCategory, *, byte_count: int | None = None) -> None: ...
    def snapshot(self) -> NetworkSnapshot: ...


class FakeNetworkObserver:
    """Explicit synthetic measurement window; never claims live coverage."""

    def __init__(self, *, measured: bool = False) -> None:
        self._measured = measured
        self._navigation = 0
        self._counts: dict[ResourceCategory, int] = {
            "document": 0,
            "xhr_fetch": 0,
            "image": 0,
            "media": 0,
            "other": 0,
        }
        self._bytes: int | None = 0
        self._lock = Lock()

    def navigation(self) -> None:
        with self._lock:
            if self._measured:
                self._navigation += 1

    def request(self, category: ResourceCategory, *, byte_count: int | None = None) -> None:
        if category not in self._counts or (
            byte_count is not None and (type(byte_count) is not int or byte_count < 0)
        ):
            raise ValueError("网络事件无效")
        with self._lock:
            if self._measured:
                self._counts[category] += 1
                self._bytes = (
                    None if self._bytes is None or byte_count is None else self._bytes + byte_count
                )

    def snapshot(self) -> NetworkSnapshot:
        with self._lock:
            if not self._measured:
                return NetworkSnapshot()
            return NetworkSnapshot(
                measurement="SIMULATED",
                browser_navigation=self._navigation,
                requests=RequestCounts(**self._counts),
                total_requests=sum(self._counts.values()),
                total_bytes=self._bytes,
                scope="synthetic_events_only",
            )
