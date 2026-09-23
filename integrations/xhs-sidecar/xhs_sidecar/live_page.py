"""Fixed first-page reads on the T03 owner thread; no arbitrary browser commands."""

from dataclasses import dataclass
from collections.abc import Callable
from time import monotonic
from typing import Literal, cast
from urllib.parse import SplitResult, urlencode, urlsplit

from playwright.sync_api import Page

from .browser import BrowserOptions, BrowserSession
from .detail_detection import (
    DETAIL_EVIDENCE_SCRIPT, classify_detail, detail_route, parse_detail_evidence,
)
from .live_observability import LiveNetworkObserver
from .ordinary_browser import OrdinaryBrowserBackend, OrdinaryBrowserResource
from .profile import ProfileStore

_split_uncached = cast(Callable[[str], SplitResult], getattr(urlsplit, "__wrapped__"))


StopCode = Literal[
    "NEED_LOGIN", "VERIFICATION_REQUIRED", "ACCESS_RESTRICTED", "RATE_LIMITED",
    "UNEXPECTED_PAGE", "PARSE_ERROR", "BROWSER_ERROR", "BUDGET_EXHAUSTED",
    "DUPLICATE_SOURCE", "STALE_SESSION", "FILTERS_UNSUPPORTED", "NO_LOCATOR",
    "ACCESS_DENIED", "NOT_FOUND", "REDIRECTED_OTHER_VALID_XHS_PAGE",
    "ACCESS_LOCATOR_INVALID", "IDENTITY_MISMATCH", "UNKNOWN",
]


class LiveReadStopped(RuntimeError):
    def __init__(self, code: StopCode) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class PageRead:
    payload: object = None
    stop: StopCode | None = None
    diagnostic: str | None = None


# Only whitelisted note metadata crosses into this process, never serialized state.
# Tokens/observed hrefs remain private parser inputs. Nothing here makes a request.
SEARCH_SCRIPT = r"""keyword => {
  if (!['https://www.xiaohongshu.com','https://xiaohongshu.com'].includes(location.origin)
      || location.pathname !== '/search_result'
      || new URL(location.href).searchParams.get('keyword') !== keyword) return {invalid_page:true};
  const unwrap = x => x && typeof x === 'object' ?
    (x.value !== undefined ? x.value : x._value !== undefined ? x._value : x) : x;
  const pick = (x, keys) => Object.fromEntries(keys.filter(k => x && x[k] !== undefined)
    .map(k => [k, x[k]]));
  const feeds = unwrap(window.__INITIAL_STATE__?.search?.feeds);
  const links = Array.from(document.querySelectorAll('a[href]')).flatMap(a => {
    try {
      const u = new URL(a.getAttribute('href'), location.origin);
      const m = u.pathname.match(/^\/(?:explore|search_result)\/([A-Za-z0-9_-]{1,80})\/?$/);
      return u.origin === location.origin && m ? [{note_id:m[1],href:u.href}] : [];
    } catch { return []; }
  }).slice(0,160);
  if (!Array.isArray(feeds)) return {state_available:false,links};
  return {state_available:true, observed_raw_count:feeds.length, batch_capped:feeds.length>80, links,
    feeds:feeds.slice(0,80).map(f => {
      const c = unwrap(f.noteCard);
      return {...pick(f,['id','modelType','xsecToken']), noteCard: {
        ...pick(c,['type','displayTitle','title','time','publishTime','publishedAt','summary','snippet']),
        user:pick(c?.user,['userId','nickname','nickName','avatar']),
        cover:{...pick(c?.cover,['url','urlPre','urlDefault','fileId','width','height']),
          infoList:Array.isArray(c?.cover?.infoList) ? c.cover.infoList.map(i => pick(i,['url'])) : undefined},
        interactInfo:pick(c?.interactInfo,['likedCount','commentCount','collectedCount','sharedCount'])
      }};
    })};
}"""


DETAIL_SCRIPT = r"""id => {
  if (!['https://www.xiaohongshu.com','https://xiaohongshu.com'].includes(location.origin)
      || !['/explore/'+id,'/search_result/'+id].includes(location.pathname.replace(/\/$/,'')))
    return {invalid_page:true};
  const unwrap = x => x && typeof x === 'object' ?
    (x.value !== undefined ? x.value : x._value !== undefined ? x._value : x) : x;
  const pick = (x, keys) => Object.fromEntries(keys.filter(k => x && x[k] !== undefined)
    .map(k => [k,x[k]]));
  const map = unwrap(window.__INITIAL_STATE__?.note?.noteDetailMap);
  const note = unwrap(unwrap(map?.[id])?.note);
  if (!note || typeof note !== 'object') return {state_available:false};
  const body = document.querySelector('#detail-desc, .note-content .desc, .note-scroller .desc');
  return {state_available:true, note: {
    ...pick(note,['noteId','title','desc','type','time','ipLocation','summary']),
    tagList:Array.isArray(note.tagList) ? note.tagList.map(t => pick(t,['name','type'])) : undefined,
    location:typeof note.location === 'string' ? note.location : pick(note.location,['name']),
    user:pick(note.user,['userId','nickname','nickName','avatar']),
    interactInfo:pick(note.interactInfo,['likedCount','commentCount','collectedCount','sharedCount']),
    imageList:Array.isArray(note.imageList) ? note.imageList.map(i => pick(i,['width','height'])) : undefined
  }, dom_body_found:!!body, dom_body:body ? body.textContent : null,
  expandable:null, truncated:null};
}"""


class LiveBrowserBackend(OrdinaryBrowserBackend):
    """Reuse ordinary launch exactly; attach observation before the login navigation."""

    def __init__(self, profile: ProfileStore, observer: LiveNetworkObserver) -> None:
        super().__init__(profile)
        self.observer = observer
        self.resource: OrdinaryBrowserResource | None = None
        self.browser_starts = 0
        self.goto_attempts = 0
        self.login_window_open = False
        self.last_read_diagnostic: str | None = None
        self.detail_diagnostic: dict[str, object] | None = None

    def start(self, options: BrowserOptions) -> OrdinaryBrowserResource:
        resource = super().start(options)
        try:
            def attach() -> None:
                if resource._context is None:
                    raise LiveReadStopped("BROWSER_ERROR")
                self.observer.attach(resource._context)
                self.observer.start_window("LOGIN")
                self.login_window_open = True
                def context_closed(_: object) -> None:
                    self.observer.detach()
                    self.login_window_open = False
                resource._context.on("close", context_closed)
            resource._run(attach)
        except Exception:
            self._pending = resource
            self.close()
            raise LiveReadStopped("BROWSER_ERROR") from None
        self.resource = resource
        self.browser_starts += 1
        return resource

    def _owned(self, session: BrowserSession) -> OrdinaryBrowserResource:
        session.require_open()
        resource = self.resource
        if resource is None or session._resource is not resource or resource._closed:
            raise LiveReadStopped("STALE_SESSION")
        return resource

    def _guard(self, resource: OrdinaryBrowserResource) -> StopCode | None:
        if self.observer.stop_code is not None:
            return self.observer.stop_code
        observation = resource._observe()
        e = observation.evidence
        if e is None or e.current_url_classification in {"UNKNOWN", "FOREIGN_ORIGIN"}:
            return "UNEXPECTED_PAGE"
        if e.access_restriction_present is True:
            return "ACCESS_RESTRICTED"
        if observation.state == "VERIFICATION_REQUIRED":
            return "VERIFICATION_REQUIRED"
        if observation.state == "LOGIN_REQUIRED":
            return "NEED_LOGIN"
        # T03 intentionally only authenticates /explore. Other official read pages
        # are accepted here only after the outer reader verified that T03 session.
        if any(x is not False for x in (
            e.login_dialog_present, e.login_button_present,
            e.verification_present, e.access_restriction_present,
        )):
            return "UNEXPECTED_PAGE"
        return None

    def pump(self, session: BrowserSession) -> None:
        resource = self._owned(session)
        def consume() -> None:
            if resource._page is not None:
                resource._page.wait_for_timeout(50)
        with resource._lock:
            resource._run(consume)

    def _read(
        self, session: BrowserSession, url: str, *, note_id: str | None, detail_number: int = 0,
        keyword: str | None = None,
    ) -> object:
        resource = self._owned(session)

        def operation() -> PageRead:
            page = resource._page
            if page is None:
                return PageRead(stop="BROWSER_ERROR")
            started = False
            initial_route = detail_route(url, note_id) if note_id is not None else None
            status: int | None = None
            redirects: int | None = None

            def diagnose() -> str:
                assert note_id is not None
                e = parse_detail_evidence(page.evaluate(DETAIL_EVIDENCE_SCRIPT, note_id))
                classification = classify_detail(e, status)
                self.detail_diagnostic = {
                    "initial_route_class": initial_route, "final_route_class": e.route,
                    "redirect_count": redirects, "redirect_basis": "MAIN_DOCUMENT_HTTP_CHAIN",
                    "main_document_status": status, "classification": classification,
                    "evidence": e.model_dump(),
                    "route_alias_changed": initial_route != e.route,
                    "window_start": "DETAIL_NAVIGATION_START",
                    "window_end": "DETAIL_STABLE_OR_FAILURE",
                    "stability": "NOT_CONFIRMED",
                }
                return classification

            try:
                # Drain delivered idle events before switching the observation window.
                page.wait_for_timeout(50)
                stop = self._guard(resource)
                if stop:
                    return PageRead(stop=stop, diagnostic="PRE_NAVIGATION_GUARD")
                if note_id is not None and initial_route not in {
                    "DETAIL_EXPLORE", "DETAIL_SEARCH_RESULT"
                }:
                    self.detail_diagnostic = {
                        "initial_route_class": initial_route,
                        "classification": "ACCESS_LOCATOR_INVALID", "navigation_started": False,
                    }
                    return PageRead(stop="ACCESS_LOCATOR_INVALID", diagnostic="LOCAL_LOCATOR_INVALID")
                self.observer.start_window(
                    "SEARCH" if note_id is None else "DETAIL_1" if detail_number == 1 else "DETAIL_2"
                )
                started = True
                deadline = monotonic() + 17
                self.goto_attempts += 1
                response = page.goto(url, wait_until="domcontentloaded", timeout=9_000)
                status = response.status if response is not None else None
                if note_id is not None:
                    request = getattr(response, "request", None)
                    if request is not None:
                        redirects = 0
                        while request.redirected_from is not None and redirects < 20:
                            redirects += 1
                            request = request.redirected_from
                        if request.redirected_from is not None:
                            redirects = None
                    diagnose()
                if status == 429:
                    return PageRead(stop="RATE_LIMITED", diagnostic="DOCUMENT_STATUS")
                if status in {401, 403}:
                    return PageRead(stop="ACCESS_RESTRICTED", diagnostic="DOCUMENT_STATUS")
                if note_id is not None and status in {404, 410}:
                    return PageRead(stop="NOT_FOUND", diagnostic="DOCUMENT_STATUS")
                if status is not None and not 200 <= status < 300:
                    return PageRead(stop="BROWSER_ERROR")
                payload: object = None
                while monotonic() < deadline - 2:
                    if note_id is not None:
                        classification = diagnose()
                        if self.observer.stop_code:
                            return PageRead(stop=self.observer.stop_code, diagnostic="NETWORK_STOP")
                        if classification == "UNKNOWN":
                            page.wait_for_timeout(250)
                            continue
                        if classification != "DETAIL_EXPECTED":
                            detail_stop = cast(StopCode, "NEED_LOGIN" if classification == "LOGIN_REQUIRED"
                                               else classification)
                            return PageRead(stop=detail_stop, diagnostic="DETAIL_CLASSIFICATION")
                        before = self.detail_diagnostic
                        page.wait_for_timeout(1_500)
                        classification = diagnose()
                        if self.observer.stop_code:
                            return PageRead(stop=self.observer.stop_code, diagnostic="NETWORK_STOP")
                        if classification not in {"DETAIL_EXPECTED", "UNKNOWN"}:
                            detail_stop = cast(StopCode, "NEED_LOGIN" if classification == "LOGIN_REQUIRED"
                                               else classification)
                            return PageRead(stop=detail_stop, diagnostic="DETAIL_CLASSIFICATION")
                        if classification != "DETAIL_EXPECTED" or self.detail_diagnostic != before:
                            continue
                        payload = self._extract(page, note_id, keyword)
                        if not isinstance(payload, dict) or payload.get("state_available") is not True:
                            return PageRead(stop="PARSE_ERROR", diagnostic="DETAIL_STATE_INVALID")
                        note = payload.get("note")
                        if not isinstance(note, dict) or note.get("noteId") != note_id:
                            assert self.detail_diagnostic is not None
                            self.detail_diagnostic["extraction_identity"] = "IDENTITY_MISMATCH"
                            return PageRead(stop="IDENTITY_MISMATCH", diagnostic="EXTRACTION_IDENTITY")
                        payload["http_status"] = status
                        assert self.detail_diagnostic is not None
                        self.detail_diagnostic["stability"] = "TWO_MATCHING_OBSERVATIONS_1500MS"
                        return PageRead(payload=payload)
                    stop = self._guard(resource)
                    if stop:
                        return PageRead(stop=stop, diagnostic="POST_NAVIGATION_GUARD")
                    current = _split_uncached(page.url)
                    allowed_paths = {"/search_result"} if note_id is None else {
                        f"/explore/{note_id}", f"/search_result/{note_id}",
                    }
                    if current.path.rstrip("/") not in allowed_paths:
                        return PageRead(stop="UNEXPECTED_PAGE", diagnostic="ROUTE_MISMATCH")
                    payload = self._extract(page, note_id, keyword)
                    if isinstance(payload, dict) and payload.get("state_available") is True:
                        # Observe default initial-page resources, without scroll or fetch.
                        page.wait_for_timeout(1_500)
                        stop = self._guard(resource)
                        if stop:
                            return PageRead(stop=stop, diagnostic="FINAL_PAGE_GUARD")
                        payload = self._extract(page, note_id, keyword)
                        if not isinstance(payload, dict) or payload.get("state_available") is not True:
                            return PageRead(stop="UNEXPECTED_PAGE", diagnostic="FINAL_STATE_INVALID")
                        if isinstance(payload, dict):
                            payload["http_status"] = status
                        return PageRead(payload=payload)
                    page.wait_for_timeout(250)
                return PageRead(stop="UNKNOWN" if note_id is not None else "PARSE_ERROR",
                                diagnostic="STATE_NOT_OBSERVED")
            except Exception:
                # Never stringify Playwright errors: navigation URLs carry credentials.
                return PageRead(stop="BROWSER_ERROR", diagnostic="DRIVER_ERROR")
            finally:
                if started:
                    self.observer.finish_window()

        with resource._lock:
            session.require_open()
            if resource._revoked or resource._closed:
                raise LiveReadStopped("STALE_SESSION")
            result = resource._run(operation)
        self.last_read_diagnostic = result.diagnostic
        if result.stop is not None:
            raise LiveReadStopped(result.stop)
        return result.payload

    @staticmethod
    def _extract(page: Page, note_id: str | None, keyword: str | None) -> object:
        if note_id is None:
            return page.evaluate(SEARCH_SCRIPT, keyword)
        return page.evaluate(DETAIL_SCRIPT, note_id)

    def search(self, session: BrowserSession, keyword: str) -> object:
        url = "https://www.xiaohongshu.com/search_result?" + urlencode({
            "keyword": keyword, "source": "web_explore_feed",
        })
        return self._read(session, url, note_id=None, keyword=keyword)

    def detail(
        self, session: BrowserSession, *, href: str, note_id: str, detail_number: int,
    ) -> object:
        # href is a parser-validated private locator, never a CLI-supplied URL.
        return self._read(session, href, note_id=note_id, detail_number=detail_number)
