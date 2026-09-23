"""Passive, bounded BrowserContext event counts, separate from the HTTP contract.

Windows attribute requests by their initiation event, not by response arrival time.
Late outcomes update their original window. These are context events observed since
attachment, not all browser/OS traffic, transferred bytes, or business operations.
"""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import hmac
import re
import secrets
from threading import RLock
from time import monotonic
from typing import Any, Literal, cast
from urllib.parse import SplitResult, urlsplit
from weakref import WeakKeyDictionary

from playwright.sync_api import BrowserContext, Request, Response

_CATEGORIES = ("document", "xhr_fetch", "image", "media", "font", "stylesheet", "script", "other")
_PURPOSES = ("comment", "analytics", "image", "media", "document", "other", "unknown")
_LABELS = frozenset({
    "LOGIN", "SEARCH", "SEARCH_2", "SEARCH_3",
    "DETAIL_1", "DETAIL_2", "DETAIL_3", "DETAIL_4", "DETAIL_5", "DETAIL_6",
})
_METHODS = frozenset({"GET", "POST", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE"})
_COMMENT_SEGMENTS = frozenset({"comment", "comments"})
_ANALYTICS_SEGMENTS = frozenset({"analytics", "collect", "beacon", "track", "tracking"})
_ANALYTICS_LABELS = frozenset({"analytics", "tracking", "track", "log", "logs"})
_Event = Literal["request", "response", "requestfailed", "requestfinished"]
NetworkStopCode = Literal["RATE_LIMITED", "ACCESS_RESTRICTED"]
# Python 3.14's urlsplit is memoized. Its documented functools __wrapped__ escape
# avoids retaining credential-bearing URL arguments in the global parsing cache.
_split_uncached = cast(Callable[[str], SplitResult], getattr(urlsplit, "__wrapped__"))


@dataclass(frozen=True)
class LiveNetworkSnapshot:
    measurement: Literal["NOT_MEASURED", "OBSERVED"] = "NOT_MEASURED"
    scope: Literal["none", "context_events_since_attach"] = "none"
    window: str = "TOTAL"
    attachment_active: bool = False
    browser_navigation: int | None = None
    navigation_unknown: int | None = None
    requests: dict[str, int | None] = field(
        default_factory=lambda: dict.fromkeys(_CATEGORIES)
    )
    total_requests: int | None = None
    total_bytes: None = None
    response_status: dict[str, int] | None = None
    failed_requests: int | None = None
    finished_requests: int | None = None
    hosts: dict[str, int] | None = None
    methods: dict[str, int] | None = None
    purposes: dict[str, int] | None = None
    purpose_classification: Literal["DERIVED"] = "DERIVED"
    association_losses: int | None = None
    callback_errors: int | None = None
    elapsed_seconds: float | None = None
    window_finished: bool = False
    resource_policy: str | None = None
    routing_cache_affected: bool | None = None
    route_attempts: int | None = None
    blocked_requests: int | None = None
    continued_requests: int | None = None
    route_errors: int | None = None
    blocked_by_category: dict[str, int] | None = None
    continued_by_category: dict[str, int] | None = None
    attempted_requests: int | None = None
    attempted_by_category: dict[str, int] | None = None
    allowed_requests: int | None = None
    allowed_by_category: dict[str, int] | None = None
    allowed_semantics: str = "APPLICATION_UNBLOCKED_EVENT_OR_SUCCESSFUL_ROUTE_CONTINUE"
    unresolved_policy_requests: int | None = None
    unresolved_policy_by_category: dict[str, int] | None = None
    unblocked_request_events: int | None = None
    unblocked_by_category: dict[str, int] | None = None
    completed_requests: int | None = None
    completed_by_category: dict[str, int] | None = None
    failed_by_category: dict[str, int] | None = None
    actual_sent_requests: None = None
    actual_sent_by_category: dict[str, None] = field(
        default_factory=lambda: dict.fromkeys(_CATEGORIES)
    )
    actual_sent_measurement: Literal["NOT_MEASURED"] = "NOT_MEASURED"
    transferred_bytes: None = None
    transferred_bytes_measurement: Literal["NOT_MEASURED"] = "NOT_MEASURED"
    repeated_resource_events: int | None = None
    repeated_by_category: dict[str, int] | None = None
    repeat_classification: str = "DERIVED_METHOD_RESOURCE_ORIGIN_PATH_WITHOUT_QUERY"
    duplicate_request_events: int | None = None
    repeat_tracking_evictions: int | None = None
    outcome_conflicts: int | None = None
    resource_retry_assessment: Literal["UNKNOWN"] = "UNKNOWN"
    lazy_load_assessment: Literal["UNKNOWN"] = "UNKNOWN"
    service_worker_assessment: Literal["UNKNOWN"] = "UNKNOWN"


@dataclass
class _Counts:
    started: float
    ended: float | None = None
    navigation: int = 0
    navigation_unknown: int = 0
    requests: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_CATEGORIES, 0))
    response_status: dict[str, int] = field(default_factory=dict)
    failed: int = 0
    finished: int = 0
    hosts: dict[str, int] = field(default_factory=dict)
    methods: dict[str, int] = field(default_factory=dict)
    purposes: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_PURPOSES, 0))
    association_losses: int = 0
    callback_errors: int = 0
    resource_policies: set[str] = field(default_factory=set)
    routing_cache_affected: bool = False
    route_attempts: int = 0
    route_errors: int = 0
    blocked: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_CATEGORIES, 0))
    continued: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_CATEGORIES, 0))
    unblocked: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_CATEGORIES, 0))
    completed: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_CATEGORIES, 0))
    failed_by_category: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_CATEGORIES, 0))
    repeated: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_CATEGORIES, 0))
    duplicate_request_events: int = 0
    repeat_tracking_evictions: int = 0
    outcome_conflicts: int = 0
    unresolved_policy: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_CATEGORIES, 0))


@dataclass
class _Association:
    window: str
    category: str
    response_seen: bool = False
    unblocked: bool = False
    route_seen: bool = False
    route_outcome: str | None = None
    terminal: str | None = None
    completed_counted: bool = False
    policy_unresolved: bool = False


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _resource_category(resource: str) -> str:
    category = "xhr_fetch" if resource in {"xhr", "fetch"} else resource
    return category if category in _CATEGORIES else "other"


def _request_metadata(request: Request) -> tuple[str, str, str, str]:
    """Only host and fixed enums survive; URL/path/query never enter stored state.

    Purpose is a heuristic, not a claim that an endpoint is necessary or that its
    response contains comments. Path segments are examined only transiently.
    Unclassified XHR/fetch purpose remains unknown; no response body is read.
    """
    category = _resource_category(request.resource_type)
    method = request.method if request.method in _METHODS else "OTHER"
    parts = _split_uncached(request.url)
    hostname = parts.hostname
    host = (
        hostname.lower()
        if hostname and len(hostname) <= 253 and re.fullmatch(r"[a-zA-Z0-9.:-]+", hostname)
        else "UNKNOWN"
    )
    segments = set(parts.path.lower().split("/"))
    if segments & _COMMENT_SEGMENTS:
        purpose = "comment"
    elif segments & _ANALYTICS_SEGMENTS or set(host.split(".")) & _ANALYTICS_LABELS:
        purpose = "analytics"
    elif category in {"image", "media", "document"}:
        purpose = category
    elif category == "xhr_fetch":
        purpose = "unknown"
    else:
        purpose = "other"
    return category, host, method, purpose


class LiveNetworkObserver:
    """Observe existing requests; never navigate, fetch, intercept, or inspect secrets.

    Call attach/detach on the context's Playwright owner thread. Snapshot/window
    methods only read local counts. No callbacks perform additional driver calls.
    Unfinished outcomes can remain unknown: status/failure counts are lower bounds
    at snapshot time, especially when association_losses/callback_errors are > 0.
    No bytes are claimed, since headers/body sizes are deliberately not inspected.
    """

    def __init__(
        self, *, max_associations: int = 4096, max_fingerprints: int = 2048,
        fingerprint_ttl_seconds: float = 60.0,
    ) -> None:
        if type(max_associations) is not int or max_associations < 1:
            raise ValueError("网络观测容量无效")
        if (type(max_fingerprints) is not int or max_fingerprints < 1
            or not 0 < fingerprint_ttl_seconds <= 300):
            raise ValueError("重复资源观测容量无效")
        self._max_associations = max_associations
        self._max_fingerprints = max_fingerprints
        self._fingerprint_ttl_seconds = fingerprint_ttl_seconds
        self._fingerprint_key = secrets.token_bytes(32)
        self._fingerprints: OrderedDict[bytes, float] = OrderedDict()
        self._lock = RLock()
        self._context: BrowserContext | None = None
        self._measured = False
        self._stop_code: NetworkStopCode | None = None
        self._routing_cache_affected = False
        self._route_handler_active = False
        self._active: str | None = None
        self._counts: dict[str, _Counts] = {}
        self._associations: WeakKeyDictionary[Request, _Association] = WeakKeyDictionary()
        # Weak, bounded terminal metadata permits idempotence and route outcomes
        # arriving after requestfinished/requestfailed; no Request is retained.
        self._terminal: WeakKeyDictionary[Request, _Association] = WeakKeyDictionary()
        self._handlers: tuple[tuple[_Event, Callable[..., Any]], ...] = (
            ("request", self._on_request),
            ("response", self._on_response),
            ("requestfailed", self._on_failed),
            ("requestfinished", self._on_finished),
        )

    def __repr__(self) -> str:
        return "LiveNetworkObserver(aggregate_events_only)"

    @property
    def stop_code(self) -> NetworkStopCode | None:
        """First official document/XHR/fetch 401/403/429 observed since attach.

        This deliberately includes official API responses unrelated to the main
        document and responses whose initiation was outside our measured window.
        The consumer must stop further operations; observation itself stays passive.
        """
        with self._lock:
            return self._stop_code

    def attach(self, context: BrowserContext) -> None:
        with self._lock:
            if self._context is context:
                return
            if self._measured:
                raise ValueError("网络观测不可切换会话")
            attached: list[tuple[_Event, Callable[..., Any]]] = []
            try:
                for event, handler in self._handlers:
                    context.on(event, handler)
                    attached.append((event, handler))
            except Exception:
                for event, handler in attached:
                    try:
                        context.remove_listener(event, handler)
                    except Exception:
                        pass
                raise ValueError("网络观测未启用") from None
            now = monotonic()
            self._counts = {"TOTAL": _Counts(now), "OUTSIDE_WINDOW": _Counts(now)}
            self._context = context
            self._measured = True

    def detach(self) -> None:
        with self._lock:
            context = self._context
            if context is None:
                return
            for event, handler in self._handlers:
                try:
                    context.remove_listener(event, handler)
                except Exception:
                    self._counts["TOTAL"].callback_errors += 1
            now = monotonic()
            for counts in self._counts.values():
                if counts.ended is None:
                    counts.ended = now
            self._context = None
            self._active = None
            self._associations.clear()
            self._terminal.clear()
            self._fingerprints.clear()
            self._fingerprint_key = b""
            self._route_handler_active = False

    def start_window(self, label: str) -> None:
        if label not in _LABELS:
            raise ValueError("网络观测窗口名称无效")
        with self._lock:
            if self._context is None or self._active is not None or label in self._counts:
                raise ValueError("网络观测窗口不可启动")
            self._counts[label] = _Counts(
                monotonic(), routing_cache_affected=self._routing_cache_affected,
            )
            self._active = label

    def record_resource_policy(self, policy: str, *, routing_enabled: bool = False) -> None:
        """Local policy metadata; does not create a request or install a route."""
        if policy not in {"OBSERVE_ONLY", "TEXT_FIRST"}:
            raise ValueError("资源策略标签无效")
        with self._lock:
            if self._context is None:
                return
            if routing_enabled:
                self._routing_cache_affected = True
                self._route_handler_active = True
                self._counts["OUTSIDE_WINDOW"].routing_cache_affected = True
            for counts in self._targets(self._active or "OUTSIDE_WINDOW"):
                counts.resource_policies.add(policy)
                counts.routing_cache_affected |= self._routing_cache_affected

    def record_route_handler_removed(self) -> None:
        """After successful unroute only; leftover pass-through handlers stay known."""
        with self._lock:
            self._route_handler_active = False

    def record_route_event(
        self, resource: str, outcome: Literal["attempted", "blocked", "continued", "error"],
        *, window: str | None = None, request: Request | None = None,
    ) -> str | None:
        """Count route-handler outcomes separately; aborted requests remain events.

        Zero means this observer recorded no corresponding handler invocation,
        not that the browser emitted no requests or transferred zero bytes.
        """
        with self._lock:
            if self._context is None:
                return None
            association = None if request is None else (
                self._associations.get(request) or self._terminal.get(request)
            )
            label = association.window if association else window or self._active or "OUTSIDE_WINDOW"
            if label not in self._counts or label == "TOTAL":
                return None
            category = association.category if association else _resource_category(resource)
            if association is not None:
                if outcome == "attempted":
                    if association.route_seen:
                        return label
                    association.route_seen = True
                    if association.unblocked:
                        # Late attribution must not leave a blocked event allowed.
                        for counts in self._targets(label):
                            counts.unblocked[category] -= 1
                            _increment(counts.unresolved_policy, category)
                        association.unblocked = False
                        association.policy_unresolved = True
                    if association.completed_counted:
                        self._uncomplete(association)
                elif outcome in {"blocked", "continued"}:
                    if association.route_outcome is not None:
                        if association.route_outcome != outcome:
                            for counts in self._targets(label):
                                counts.outcome_conflicts += 1
                        return label
                    if association.unblocked:
                        for counts in self._targets(label):
                            counts.unblocked[category] -= 1
                        association.unblocked = False
                    association.route_outcome = outcome
                    if association.policy_unresolved:
                        for counts in self._targets(label):
                            counts.unresolved_policy[category] -= 1
                        association.policy_unresolved = False
                    if outcome == "blocked":
                        self._uncomplete(association)
                        if association.terminal == "finished":
                            for counts in self._targets(label):
                                counts.outcome_conflicts += 1
                    elif association.terminal == "finished":
                        self._complete(association)
            for counts in self._targets(label):
                if outcome == "attempted":
                    counts.route_attempts += 1
                elif outcome == "blocked":
                    _increment(counts.blocked, category)
                elif outcome == "continued":
                    _increment(counts.continued, category)
                elif outcome == "error":
                    counts.route_errors += 1
            return label

    def finish_window(self) -> LiveNetworkSnapshot:
        with self._lock:
            if self._active is None:
                raise ValueError("网络观测窗口未启动")
            label = self._active
            self._counts[label].ended = monotonic()
            self._active = None
            return self.snapshot(label)

    def snapshot(self, label: str | None = None) -> LiveNetworkSnapshot:
        key = label if label is not None else "TOTAL"
        if key not in _LABELS | {"TOTAL", "OUTSIDE_WINDOW"}:
            raise ValueError("网络观测窗口名称无效")
        with self._lock:
            counts = self._counts.get(key)
            if not self._measured or counts is None:
                return LiveNetworkSnapshot(window=key)
            return LiveNetworkSnapshot(
                measurement="OBSERVED", scope="context_events_since_attach", window=key,
                attachment_active=self._context is not None,
                browser_navigation=counts.navigation, navigation_unknown=counts.navigation_unknown,
                requests=dict(counts.requests), total_requests=sum(counts.requests.values()),
                response_status=dict(counts.response_status), failed_requests=counts.failed,
                finished_requests=counts.finished, hosts=dict(counts.hosts),
                methods=dict(counts.methods), purposes=dict(counts.purposes),
                association_losses=counts.association_losses, callback_errors=counts.callback_errors,
                elapsed_seconds=round(
                    (counts.ended if counts.ended is not None else monotonic()) - counts.started, 6
                ),
                window_finished=counts.ended is not None,
                resource_policy=(
                    "MIXED" if len(counts.resource_policies) > 1
                    else next(iter(counts.resource_policies), "OBSERVE_ONLY")
                ),
                routing_cache_affected=counts.routing_cache_affected,
                route_attempts=counts.route_attempts, route_errors=counts.route_errors,
                blocked_requests=sum(counts.blocked.values()),
                continued_requests=sum(counts.continued.values()),
                blocked_by_category=dict(counts.blocked),
                continued_by_category=dict(counts.continued),
                attempted_requests=sum(counts.requests.values()),
                attempted_by_category=dict(counts.requests),
                allowed_requests=sum(counts.unblocked.values()) + sum(counts.continued.values()),
                allowed_by_category={
                    category: counts.unblocked[category] + counts.continued[category]
                    for category in _CATEGORIES
                },
                unresolved_policy_requests=sum(counts.unresolved_policy.values()),
                unresolved_policy_by_category=dict(counts.unresolved_policy),
                unblocked_request_events=sum(counts.unblocked.values()),
                unblocked_by_category=dict(counts.unblocked),
                completed_requests=counts.finished,
                completed_by_category=dict(counts.completed),
                failed_by_category=dict(counts.failed_by_category),
                repeated_resource_events=sum(counts.repeated.values()),
                repeated_by_category=dict(counts.repeated),
                duplicate_request_events=counts.duplicate_request_events,
                repeat_tracking_evictions=counts.repeat_tracking_evictions,
                outcome_conflicts=counts.outcome_conflicts,
            )

    def _targets(self, window: str) -> tuple[_Counts, _Counts]:
        return self._counts["TOTAL"], self._counts[window]

    def _error(self, window: str | None = None) -> None:
        with self._lock:
            if self._context is not None:
                for counts in self._targets(window or self._active or "OUTSIDE_WINDOW"):
                    counts.callback_errors += 1

    def _record_repeat(self, request: Request, category: str, window: str) -> None:
        """A same-path event is only a possible repeat, never a confirmed retry.

        Ignore query, fragment and userinfo before keyed hashing. The per-observer
        random key and bounded digests stay in RAM for <= TTL and are cleared at
        detach. Neither the path nor the digest is logged or returned in a snapshot.
        Query-distinct calls and legitimate repeated loads can share a digest.
        """
        parts = _split_uncached(request.url)
        key_material = "\0".join((
            request.method, category, parts.scheme, parts.hostname or "", str(parts.port), parts.path,
        )).encode("utf-8", errors="replace")
        fingerprint = hmac.digest(self._fingerprint_key, key_material, hashlib.sha256)
        now = monotonic()
        evictions = 0
        while self._fingerprints:
            first = next(iter(self._fingerprints))
            if now - self._fingerprints[first] <= self._fingerprint_ttl_seconds:
                break
            self._fingerprints.popitem(last=False)
            evictions += 1
        repeated = fingerprint in self._fingerprints
        self._fingerprints[fingerprint] = now
        self._fingerprints.move_to_end(fingerprint)
        if len(self._fingerprints) > self._max_fingerprints:
            self._fingerprints.popitem(last=False)
            evictions += 1
        for counts in self._targets(window):
            counts.repeat_tracking_evictions += evictions
            if repeated:
                _increment(counts.repeated, category)

    def _complete(self, association: _Association) -> None:
        if association.completed_counted or association.route_outcome == "blocked":
            return
        for counts in self._targets(association.window):
            counts.finished += 1
            _increment(counts.completed, association.category)
        association.completed_counted = True

    def _uncomplete(self, association: _Association) -> None:
        if not association.completed_counted:
            return
        for counts in self._targets(association.window):
            counts.finished -= 1
            counts.completed[association.category] -= 1
        association.completed_counted = False

    def _on_request(self, request: Request) -> None:
        try:
            with self._lock:
                if self._context is None:
                    return
                window = self._active or "OUTSIDE_WINDOW"
                policy = self._counts[window].resource_policies or {"OBSERVE_ONLY"}
                if request in self._associations or request in self._terminal:
                    original = self._associations.get(request) or self._terminal[request]
                    for counts in self._targets(original.window):
                        counts.duplicate_request_events += 1
                    return
                try:
                    category, host, method, purpose = _request_metadata(request)
                except Exception:
                    category, host, method, purpose = "other", "UNKNOWN", "OTHER", "unknown"
                    self._error(window)
                try:
                    self._record_repeat(request, category, window)
                except Exception:
                    # Existing metadata failure has already been recorded once.
                    if host != "UNKNOWN":
                        self._error(window)
                navigation = False
                navigation_unknown = False
                try:
                    navigation = request.is_navigation_request() and request.frame.parent_frame is None
                except Exception:
                    navigation_unknown = True
                for counts in self._targets(window):
                    counts.resource_policies.update(policy)
                    _increment(counts.requests, category)
                    _increment(counts.hosts, host)
                    _increment(counts.methods, method)
                    _increment(counts.purposes, purpose)
                    counts.navigation += int(navigation)
                    counts.navigation_unknown += int(navigation_unknown)
                    if not self._route_handler_active:
                        _increment(counts.unblocked, category)
                    else:
                        _increment(counts.unresolved_policy, category)
                if len(self._associations) >= self._max_associations:
                    oldest = next(iter(self._associations))
                    dropped = self._associations.pop(oldest)
                    for counts in self._targets(dropped.window):
                        counts.association_losses += 1
                self._associations[request] = _Association(
                    window, category, unblocked=not self._route_handler_active,
                    policy_unresolved=self._route_handler_active,
                )
        except Exception:
            self._error()

    def _on_response(self, response: Response) -> None:
        window: str | None = None
        try:
            with self._lock:
                if self._context is None:
                    return
                request = response.request
                association = self._associations.get(request) or self._terminal.get(request)
                if association is not None:
                    window = association.window
                status = response.status
                # Independent of bounded request attribution: losing an association
                # must not hide an observed official access restriction.
                if self._stop_code is None and type(status) is int and status in {401, 403, 429}:
                    try:
                        host = _split_uncached(request.url).hostname
                        official = host is not None and (
                            host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com")
                        )
                        if official and request.resource_type in {"document", "xhr", "fetch"}:
                            self._stop_code = "RATE_LIMITED" if status == 429 else "ACCESS_RESTRICTED"
                    except Exception:
                        self._error(window)
                if association is None or association.response_seen:
                    return
                key = str(status) if type(status) is int and 100 <= status <= 599 else "UNKNOWN"
                for counts in self._targets(association.window):
                    _increment(counts.response_status, key)
                association.response_seen = True
        except Exception:
            self._error(window)

    def _end_request(self, request: Request, *, failed: bool) -> None:
        try:
            with self._lock:
                if self._context is None:
                    return
                association = self._associations.pop(request, None)
                if association is None:
                    return
                association.terminal = "failed" if failed else "finished"
                for counts in self._targets(association.window):
                    if failed:
                        counts.failed += 1
                        _increment(counts.failed_by_category, association.category)
                # Routed completion can arrive synchronously before continue_
                # returns. Wait for its outcome; blocked is never completed.
                if not failed and (not association.route_seen
                                   or association.route_outcome == "continued"):
                    self._complete(association)
                if len(self._terminal) >= self._max_associations:
                    oldest = next(iter(self._terminal))
                    dropped = self._terminal.pop(oldest)
                    if dropped.route_seen and dropped.route_outcome is None:
                        for counts in self._targets(dropped.window):
                            counts.association_losses += 1
                self._terminal[request] = association
        except Exception:
            self._error()

    def _on_failed(self, request: Request) -> None:
        self._end_request(request, failed=True)

    def _on_finished(self, request: Request) -> None:
        self._end_request(request, failed=False)
