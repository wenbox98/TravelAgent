"""One bounded smoke run, not a research scheduler or an HTTP API."""

from collections.abc import Callable
from threading import RLock
from typing import Protocol

from .browser import BrowserManager, BrowserSession, SessionClosed
from .live_page import LiveReadStopped, StopCode
from .live_parsing import LiveCandidate, LiveDetail, LiveParseError, LiveSearch, parse_detail, parse_search
from .login import LoginLifecycle
from .models import SearchRequest


class LivePageReader(Protocol):
    def search(self, session: BrowserSession, keyword: str) -> object: ...
    def detail(
        self, session: BrowserSession, *, href: str, note_id: str, detail_number: int,
    ) -> object: ...


class LiveSmokeReader:
    """Permits are consumed before dispatch, including failed and interrupted reads."""

    def __init__(
        self, browser: BrowserManager, login: LoginLifecycle, backend: LivePageReader,
        *, checkpoint: Callable[[], None] | None = None,
    ) -> None:
        self.browser, self.login, self.backend = browser, login, backend
        self.search_operations = 0
        self.detail_operations = 0
        self.duplicate_details_avoided = 0
        self.search_result: LiveSearch | None = None
        self.details: dict[str, LiveDetail] = {}
        self._attempted: set[str] = set()
        self._generation: int | None = None
        self._session: BrowserSession | None = None
        self.stopped: StopCode | None = None
        self._lock = RLock()
        self._checkpoint = checkpoint or (lambda: None)

    def _scope(self) -> BrowserSession:
        state = self.login.status()
        if state.status != "AUTHENTICATED":
            raise LiveReadStopped("NEED_LOGIN")
        try:
            session = self.browser.get_session()
        except SessionClosed:
            raise LiveReadStopped("STALE_SESSION") from None
        if self._generation is None:
            self._generation, self._session = state.generation, session
        if self._generation != state.generation or self._session is not session:
            raise LiveReadStopped("STALE_SESSION")
        return session

    def search(self, request: SearchRequest) -> LiveSearch:
        with self._lock:
            if request.filters.specified():
                # No filter UI is implemented, so it cannot be reported APPLIED.
                raise LiveReadStopped("FILTERS_UNSUPPORTED")
            if self.stopped:
                raise LiveReadStopped(self.stopped)
            if self.search_operations >= 1:
                raise LiveReadStopped("BUDGET_EXHAUSTED")
            session = self._scope()
            self.search_operations += 1
            self._checkpoint()  # Safe durable counters, before any external operation.
            try:
                self._scope()
                raw = self.backend.search(session, request.keyword)
                result = parse_search(raw, session.session_id)
                self._scope()  # A late result cannot commit after generation revocation.
                self.search_result = result
                self.login.audit.emit("search_finished", count=len(result.candidates))
                return result
            except LiveReadStopped as error:
                self.stopped = error.code
                raise
            except LiveParseError:
                self.stopped = "PARSE_ERROR"
                raise LiveReadStopped("PARSE_ERROR") from None
            except Exception:
                self.stopped = "BROWSER_ERROR"
                raise LiveReadStopped("BROWSER_ERROR") from None

    def selection(self) -> tuple[int, ...]:
        """Title-based suitability is DERIVED and is never claimed as body evidence."""
        if self.search_result is None:
            return ()
        ranked: list[tuple[int, int]] = []
        for i, candidate in enumerate(self.search_result.candidates):
            title = candidate.title or ""
            if candidate.note_type != "normal" or candidate.href is None or candidate.locator is None:
                continue
            if "川西" not in title:
                continue
            score = sum(term in title for term in ("攻略", "路线", "环线", "国庆", "成都", "自驾"))
            if score:
                ranked.append((-score, i))
        ranked.sort()
        selected: list[int] = []
        titles: set[str] = set()
        for _, index in ranked:
            title = self.search_result.candidates[index].title or ""
            if title not in titles:
                selected.append(index)
                titles.add(title)
            if len(selected) == 2:
                break
        return tuple(selected)

    def detail(self, index: int) -> LiveDetail:
        with self._lock:
            session = self._scope()
            if self.search_result is None or type(index) is not int or not 0 <= index < len(
                self.search_result.candidates
            ):
                raise LiveReadStopped("NO_LOCATOR")
            candidate: LiveCandidate = self.search_result.candidates[index]
            key = candidate.source.source_id
            if key in self.details:
                self.duplicate_details_avoided += 1
                return self.details[key]
            if key in self._attempted:
                self.duplicate_details_avoided += 1
                raise LiveReadStopped("DUPLICATE_SOURCE")
            if self.stopped:
                raise LiveReadStopped(self.stopped)
            if self.detail_operations >= 2:
                raise LiveReadStopped("BUDGET_EXHAUSTED")
            if (
                candidate.locator is None or candidate.href is None
                or candidate.locator.session_id != session.session_id
            ):
                raise LiveReadStopped("NO_LOCATOR")
            # Both successful and unsuccessful attempts enter the deduplication set.
            self._attempted.add(key)
            self.detail_operations += 1
            self._checkpoint()
            self.login.audit.redactor.register(candidate.locator.xsec_token)
            self.login.audit.redactor.register(candidate.href)
            try:
                self._scope()
                raw = self.backend.detail(
                    session, href=candidate.href.get_secret_value(), note_id=candidate.source.note_id,
                    detail_number=self.detail_operations,
                )
                result = parse_detail(raw, candidate.source)
                self._scope()
                self.details[key] = result
                self.login.audit.emit("detail_finished")
                return result
            except LiveReadStopped as error:
                self.stopped = error.code
                raise
            except LiveParseError:
                self.stopped = "PARSE_ERROR"
                raise LiveReadStopped("PARSE_ERROR") from None
            except Exception:
                self.stopped = "BROWSER_ERROR"
                raise LiveReadStopped("BROWSER_ERROR") from None

    def safe_summary(self) -> dict[str, object]:
        return {
            "mode": "live_smoke", "is_synthetic": False,
            "max_search_operations": 1, "max_feed_details": 2,
            "search_operations": self.search_operations, "detail_operations": self.detail_operations,
            "duplicate_details_avoided": self.duplicate_details_avoided,
            "filter_requested": {}, "filter_applied": {}, "filter_status": "NOT_REQUESTED",
            "stopped": self.stopped,
            "search": self.search_result.safe_summary() if self.search_result is not None else None,
            "selected_indices": self.selection(),
            "selection_basis": "DERIVED:title_region_and_route_words;normal_notes;distinct_titles",
            "details": [value.safe_summary() for value in self.details.values()],
            "comments_expanded": False, "automatic_scrolls": 0, "image_analysis": False,
            "platform_content_writes": 0,
        }
