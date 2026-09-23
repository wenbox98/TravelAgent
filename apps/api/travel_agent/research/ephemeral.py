"""Short-lived source content references, never a persistent cache or credential store."""

from collections.abc import Callable
from time import monotonic


class EphemeralSourceContent:
    def __init__(self, state_body: str, dom_body: str | None = None,
                 *, ttl_seconds: float = 300, clock: Callable[[], float] = monotonic) -> None:
        if not 0 < ttl_seconds <= 300:
            raise ValueError("正文临时使用窗口必须在 300 秒以内")
        self._state, self._dom = state_body, dom_body
        self._clock, self._expires = clock, clock() + ttl_seconds
        self._closed = False

    def __repr__(self) -> str:
        return "EphemeralSourceContent(private)"

    def read(self) -> tuple[str, str | None]:
        if self._closed or self._clock() >= self._expires:
            self.close()
            raise ValueError("临时正文已过期或关闭")
        return self._state, self._dom

    def close(self) -> None:
        # Reference lifecycle only; Python cannot promise forensic memory erasure.
        self._state, self._dom, self._closed = "", None, True
