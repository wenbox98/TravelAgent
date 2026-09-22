from threading import RLock
from uuid import uuid4

from .backend import FakeXhsBackend, ReadonlyBackend
from .browser import BrowserManager, SessionClosed
from .completeness import classify_completeness
from .models import (
    AccessLocator,
    BrowserState,
    Candidate,
    DetailRequest,
    DetailResult,
    SearchRequest,
    SearchResult,
)
from .observability import FakeNetworkObserver, NetworkObserver
from .redaction import SafeAuditLog


class InvalidHandle(ValueError):
    def __init__(self) -> None:
        super().__init__("定位句柄无效或已失效")


class BackendContractError(ValueError):
    def __init__(self) -> None:
        super().__init__("读取结果不符合内部契约")


class SidecarService:
    """Local readonly operations only, not a research planner or evidence store."""

    def __init__(
        self,
        *,
        browser: BrowserManager | None = None,
        backend: ReadonlyBackend | None = None,
        observer: NetworkObserver | None = None,
    ) -> None:
        self.browser = browser or BrowserManager()
        self.backend = backend or FakeXhsBackend()
        self.observer = observer or FakeNetworkObserver()
        self.audit = SafeAuditLog()
        self._locators: dict[str, AccessLocator] = {}
        self._handles: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def browser_state(self) -> BrowserState:
        with self._lock:
            try:
                session = self.browser.get_session()
            except SessionClosed:
                return BrowserState(state="CLOSED")
            return BrowserState(state="ACTIVE", session_id=session.session_id)

    def start(self) -> BrowserState:
        with self._lock:
            self.browser.start()
            self.audit.emit("session_started")
            return self.browser_state()

    def close(self) -> BrowserState:
        with self._lock:
            self._locators.clear()
            self._handles.clear()
            self.audit.redactor.clear()
            self.browser.close()
            self.audit.emit("session_closed")
            return self.browser_state()

    def search(self, request: SearchRequest) -> SearchResult:
        with self._lock, self.browser.lease() as session:
            raw = self.backend.search(session, request)
            candidates = []
            for item in raw.candidates:
                key = (session.session_id, item.source.source_id)
                handle = self._handles.get(key, uuid4().hex)
                if handle not in self._locators and len(self._locators) >= 100:
                    raise ValueError("会话定位容量已满")
                self._handles[key] = handle
                self._locators[handle] = AccessLocator(item.source, session.session_id, item.token)
                self.audit.redactor.register(item.token)
                candidates.append(
                    Candidate(source=item.source, note_handle=handle, title=item.title)
                )
            result = SearchResult(
                candidates=candidates,
                filter_requested=request.filters,
                filter_applied=raw.applied,
                filter_status=raw.status,
                network=self.observer.snapshot(),
            )
            self.audit.emit("search_finished", count=len(candidates))
            return result

    def detail(self, request: DetailRequest) -> DetailResult:
        with self._lock:
            locator = self._locators.get(request.note_handle)
            if locator is None:
                raise InvalidHandle()
            session = self.browser.get_session()
            if locator.session_id != session.session_id:
                raise InvalidHandle()
            raw = self.backend.detail(session, locator)
            if raw.source != locator.source or not 200 <= raw.http_status < 300:
                raise BackendContractError()
            classification = classify_completeness(raw)
            result = DetailResult(
                source=raw.source,
                title=raw.title,
                body=raw.body,
                summary=raw.summary,
                completeness=classification.completeness,
                completeness_reason=classification.reason,
                network=self.observer.snapshot(),
            )
            self.audit.emit("detail_finished")
            return result
