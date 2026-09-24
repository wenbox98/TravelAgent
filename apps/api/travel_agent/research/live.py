"""Explicit live adapter reusing T03 ownership and T04 parsing. No public browser tool."""

from datetime import datetime, timezone
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from xhs_sidecar.browser import BrowserSession, SessionClosed
from xhs_sidecar.live_observability import LiveNetworkObserver
from xhs_sidecar.live_page import LiveBrowserBackend, LiveReadStopped
from xhs_sidecar.live_parsing import LiveCandidate, LiveParseError, parse_detail, parse_search
from xhs_sidecar.live_smoke import CountingBrowserManager
from xhs_sidecar.login import LoginLifecycle
from xhs_sidecar.profile import ProfileStore
from xhs_sidecar.resource_policy import ResourcePolicy

from .models import Candidate, DetailMaterial, ResearchStopped


def _stopped(code: str, *, technical: bool = False) -> ResearchStopped:
    if code in {"NEED_LOGIN", "STALE_SESSION"}:
        return ResearchStopped("NEED_LOGIN", code)
    if code == "VERIFICATION_REQUIRED":
        return ResearchStopped("VERIFICATION_REQUIRED", code)
    return ResearchStopped("SOURCE_UNAVAILABLE", code, fallback_eligible=technical and code in {
        "BROWSER_ERROR", "PARSE_ERROR", "UNKNOWN",
    })


class LiveResearchReader:
    def __init__(self, project: Path, *, resource_policy: ResourcePolicy = ResourcePolicy.OBSERVE_ONLY,
                 login_prompt: Callable[[], None] | None = None) -> None:
        self.profile = ProfileStore(project)
        self.profile_present_at_start = self.profile.exists()
        self.observer = LiveNetworkObserver()
        self.backend = LiveBrowserBackend(self.profile, self.observer,
                                          resource_policy=resource_policy)
        self.browser = CountingBrowserManager(self.backend)
        self.login = LoginLifecycle(self.browser, self.profile)
        self._candidates: dict[str, LiveCandidate] = {}
        self._session: BrowserSession | None = None
        self._generation: int | None = None
        self.login_state = self.login.status().status
        self.closed = False
        self.connect_calls = 0
        self.detail_summaries: list[dict[str, Any]] = []
        self.search_summary: dict[str, object] | None = None
        self._last_operation = 0.0
        self.browser_info: dict[str, object] = {}
        self.login_prompt = login_prompt

    @property
    def text_first(self) -> bool:
        state = self.backend.resource_policy.snapshot()
        return state.get("requested") == "TEXT_FIRST" and not state.get("optimization_disabled")

    def disable_text_first(self) -> None:
        self.backend.disable_text_first()

    def connect(self) -> None:
        if self.closed:
            raise ResearchStopped("ERROR", "READER_CLOSED")
        if self.observer.stop_code:
            raise _stopped(self.observer.stop_code)
        self.connect_calls += 1
        if self.login.status().status == "AUTHENTICATED":
            self._scope()
            return
        self.login.connect()
        deadline = monotonic() + 40
        prompted = False
        while monotonic() < deadline:
            state = self.login.status()
            self.login_state = state.status
            if self.observer.stop_code:
                raise _stopped(self.observer.stop_code)
            if state.status == "AUTHENTICATED":
                self._generation, self._session = state.generation, self.browser.get_session()
                if self.backend.login_window_open:
                    self.observer.finish_window()
                    self.backend.login_window_open = False
                resource = self.backend.resource
                if resource is not None:
                    def info() -> dict[str, object]:
                        context = resource._context
                        return {
                            "version": context.browser.version if context and context.browser else None,
                            "executable_path": resource._driver.chromium.executable_path
                            if resource._driver else None,
                        }
                    self.browser_info = resource._run(info)
                return
            if state.status in {"LOGIN_REQUIRED", "WAITING_USER"}:
                if self.login_prompt is not None and not prompted:
                    prompted = True
                    self.login_prompt()  # Human action only; same page/session/generation.
                    deadline = monotonic() + 40
                    continue
                raise ResearchStopped("NEED_LOGIN")
            if state.status == "VERIFICATION_REQUIRED":
                raise ResearchStopped("VERIFICATION_REQUIRED")
            if state.status in {"ERROR", "CANCELLED", "DISCONNECTED"}:
                raise ResearchStopped("ERROR", "LOGIN_FAILED")
            sleep(0.1)
        raise ResearchStopped("ERROR", "LOGIN_OBSERVATION_TIMEOUT")

    def _scope(self) -> BrowserSession:
        state = self.login.status()
        if self.observer.stop_code:
            raise _stopped(self.observer.stop_code)
        if state.status == "VERIFICATION_REQUIRED":
            raise ResearchStopped("VERIFICATION_REQUIRED")
        if state.status != "AUTHENTICATED":
            raise ResearchStopped("NEED_LOGIN")
        try:
            session = self.browser.get_session()
        except SessionClosed:
            raise ResearchStopped("NEED_LOGIN", "STALE_SESSION") from None
        if session is not self._session or state.generation != self._generation:
            raise ResearchStopped("NEED_LOGIN", "STALE_SESSION")
        return session

    def _pace(self) -> None:
        # Existing conservative application gap; not human behaviour simulation.
        remaining = 8.0 - (monotonic() - self._last_operation)
        if remaining > 0:
            sleep(remaining)
        self._scope()
        self._last_operation = monotonic()

    def search(self, query: str) -> tuple[Candidate, ...]:
        session = self._scope()
        try:
            self._pace()
            result = parse_search(self.backend.search(session, query), session.session_id)
            self._scope()
        except LiveReadStopped as error:
            raise _stopped(error.code) from None
        except LiveParseError:
            self.disable_text_first()
            raise _stopped("PARSE_ERROR") from None
        self.search_summary = {key: value for key, value in result.safe_summary().items()
                               if key != "candidates"}
        for candidate in result.candidates:
            self._candidates[candidate.source.source_id] = candidate
        return tuple(Candidate(c.source.source_id, c.title, c.note_type,
                               c.href is not None and c.locator is not None)
                     for c in result.candidates)

    def detail(self, candidate: Candidate, detail_number: int) -> DetailMaterial:
        session = self._scope()
        observed = self._candidates.get(candidate.source_id)
        if (observed is None or observed.locator is None or observed.href is None
            or observed.locator.session_id != session.session_id):
            raise _stopped("NO_LOCATOR")
        self.login.audit.redactor.register(observed.locator.xsec_token)
        self.login.audit.redactor.register(observed.href)
        try:
            self._pace()
            payload = self.backend.detail(session, href=observed.href.get_secret_value(),
                                          note_id=observed.source.note_id,
                                          detail_number=detail_number)
            if (isinstance(payload, dict) and isinstance(payload.get("note"), dict)
                and payload["note"].get("noteId") != observed.source.note_id):
                raise _stopped("IDENTITY_MISMATCH")
            result = parse_detail(payload, observed.source)
            self._scope()
        except LiveReadStopped as error:
            raise _stopped(error.code, technical=True) from None
        except LiveParseError:
            self.disable_text_first()
            raise _stopped("PARSE_ERROR", technical=True) from None
        summary = result.safe_summary()
        summary.pop("anonymized_source_id", None)
        self.detail_summaries.append({"detail_number": detail_number, **summary})
        published: str | None = None
        if isinstance(payload, dict) and isinstance(payload.get("note"), dict):
            timestamp = payload["note"].get("time")
            if type(timestamp) is int and timestamp > 0:
                try:
                    published = datetime.fromtimestamp(timestamp / 1000 if timestamp > 10**11
                                                       else timestamp, tz=timezone.utc).isoformat()
                except (ValueError, OSError, OverflowError):
                    pass
        dom_body = payload.get("dom_body") if isinstance(payload, dict) else None
        return DetailMaterial(candidate.source_id, result.raw.title, result.raw.body or "",
                              result.classification.completeness,
                              datetime.now(timezone.utc).isoformat(), published, result.image_count,
                              dom_body=dom_body if isinstance(dom_body, str) else None)

    def close(self) -> None:
        if not self.closed:
            self.login.shutdown()  # Retain profile. Never disconnect here.
            if self.login.status().status == "ERROR":
                raise RuntimeError("浏览器关闭失败")
            self._candidates.clear()
            self._session = None
            self.closed = True
