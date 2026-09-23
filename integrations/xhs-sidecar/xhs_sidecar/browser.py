"""Owned browser lifecycle shared by the synthetic and ordinary backends."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import SecretStr

from .models import LoginEvidence


class SessionClosed(RuntimeError):
    def __init__(self) -> None:
        super().__init__("浏览器会话已关闭")


class BrowserError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("普通浏览器操作失败，请检查本机浏览器安装与专用会话")


@dataclass(frozen=True, repr=False)
class AccountIdentity:
    """Private local identity; an absent stable identifier stays unknown."""

    stable_id: SecretStr | None = None


@dataclass(frozen=True)
class LoginObservation:
    state: Literal["AUTHENTICATED", "LOGIN_REQUIRED", "VERIFICATION_REQUIRED", "UNKNOWN"]
    identity: AccountIdentity = AccountIdentity()
    evidence: LoginEvidence | None = None


@dataclass(frozen=True)
class BrowserOptions:
    engine: Literal["chrome", "chromium"] = "chromium"
    headless: bool = True

    def __post_init__(self) -> None:
        if self.engine not in {"chrome", "chromium"} or type(self.headless) is not bool:
            raise ValueError("普通浏览器配置无效")


class BrowserResource(Protocol):
    def open_login(self) -> None: ...

    def observe_login(self) -> LoginObservation: ...

    def close(self) -> None: ...


class BrowserBackend(Protocol):
    def start(self, options: BrowserOptions) -> BrowserResource: ...


class FakeBrowserResource:
    def __init__(self) -> None:
        self.closed = False
        self.navigations = 0
        self.observations = 0

    def open_login(self) -> None:
        if self.closed:
            raise SessionClosed()
        if not self.navigations:
            self.navigations += 1

    def observe_login(self) -> LoginObservation:
        if self.closed:
            raise SessionClosed()
        self.observations += 1
        return LoginObservation("LOGIN_REQUIRED")

    def close(self) -> None:
        self.closed = True


class FakeBrowserBackend:
    kind = "fake"

    def __init__(self) -> None:
        self.starts = 0

    def start(self, options: BrowserOptions) -> FakeBrowserResource:
        self.starts += 1
        return FakeBrowserResource()


class BrowserSession:
    def __init__(self, resource: BrowserResource) -> None:
        self.session_id = uuid4().hex
        self._resource = resource
        self._closed = False
        self._cleanup_done = False

    def require_open(self) -> None:
        if self._closed:
            raise SessionClosed()

    def _close(self) -> None:
        if not self._cleanup_done:
            self._closed = True  # Revoke even if backend cleanup fails.
            self._resource.close()
            self._cleanup_done = True

    def open_login(self) -> None:
        self.require_open()
        self._resource.open_login()

    def observe_login(self) -> LoginObservation:
        self.require_open()
        return self._resource.observe_login()


class BrowserManager:
    def __init__(
        self, backend: BrowserBackend | None = None, options: BrowserOptions | None = None
    ) -> None:
        self.backend = backend if backend is not None else FakeBrowserBackend()
        self.options = options or BrowserOptions()
        self._session: BrowserSession | None = None
        self._lock = RLock()

    def start(self) -> BrowserSession:
        with self._lock:
            if self._session is None:
                self._session = BrowserSession(self.backend.start(self.options))
            self._session.require_open()
            return self._session

    def get_session(self) -> BrowserSession:
        with self._lock:
            if self._session is None:
                raise SessionClosed()
            self._session.require_open()
            return self._session

    @contextmanager
    def lease(self) -> Iterator[BrowserSession]:
        """Serialize operations and close; no page/navigation API is exposed."""
        with self._lock:
            yield self.start()

    def close(self) -> None:
        with self._lock:
            if self._session is not None:
                # Retain a revoked resource after failure so cleanup can be retried.
                self._session._close()
                self._session = None
            # A real backend may retain a partly started resource after failed cleanup.
            cleanup = getattr(self.backend, "close", None)
            if cleanup is not None:
                cleanup()
