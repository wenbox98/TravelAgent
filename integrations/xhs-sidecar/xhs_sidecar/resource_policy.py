"""Explicit, stage-scoped text resource policy; never retries an operation."""

from enum import Enum
from threading import RLock
from typing import Literal

from playwright.sync_api import BrowserContext, Request, Route

from .live_observability import LiveNetworkObserver


class ResourcePolicy(str, Enum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    TEXT_FIRST = "TEXT_FIRST"


class ResourcePolicyError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("资源策略未能安全启用或恢复")


class ResourcePolicyController:
    """Own exactly one route handler on the existing Playwright owner thread.

    OBSERVE_ONLY installs no handler. LOGIN and idle always remain observe-only.
    Playwright routing disables HTTP cache and does not cover Service Worker
    intercepted traffic. Neither cache nor Service Worker settings are modified
    to hide this limitation; comparisons must disclose routing's cache effect.
    """

    def __init__(
        self, observer: LiveNetworkObserver,
        policy: ResourcePolicy = ResourcePolicy.OBSERVE_ONLY,
    ) -> None:
        self._requested = ResourcePolicy(policy)
        self._observer = observer
        self._lock = RLock()
        self._context: BrowserContext | None = None
        self._installed = False
        self._phase: Literal["SEARCH", "DETAIL"] | None = None
        self._active = ResourcePolicy.OBSERVE_ONLY
        self._disabled = False
        self._cache_affected = False
        self._failure: str | None = None
        # Preserve the exact handler identity for unroute; never remove other handlers.
        self._handler = self._handle

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "requested": self._requested.value, "active": self._active.value,
                "phase": self._phase, "optimization_disabled": self._disabled,
                "route_handler_installed": self._installed,
                "routing_cache_affected": self._cache_affected,
                "service_worker_settings_modified": False,
                "last_failure": self._failure,
            }

    def disable(self) -> None:
        """Latch observe-only for later explicitly budgeted calls; no navigation."""
        with self._lock:
            self._disabled = True
            self._active = ResourcePolicy.OBSERVE_ONLY
            self._failure = self._failure or "READ_OR_EXTRACTION_FAILED"

    def begin(self, context: BrowserContext | None, phase: Literal["SEARCH", "DETAIL"]) -> None:
        with self._lock:
            if phase not in {"SEARCH", "DETAIL"} or self._phase is not None or self._installed:
                raise ResourcePolicyError()
            self._phase = phase
            self._active = ResourcePolicy.OBSERVE_ONLY if self._disabled else self._requested
            enabled = self._active is ResourcePolicy.TEXT_FIRST
            if not enabled:
                self._observer.record_resource_policy(self._active.value)
                return
            if context is None:
                self._failure = "NO_OWNED_CONTEXT"
                self.disable()
                raise ResourcePolicyError()
            self._observer.record_resource_policy(self._active.value, routing_enabled=True)
            self._context = context
            # Conservatively retain ownership even when route installation raises.
            self._installed = self._cache_affected = True
            try:
                context.route("**/*", self._handler)
            except Exception:
                self._failure = "ROUTE_INSTALL_FAILED"
                self.disable()
                raise ResourcePolicyError() from None

    def end(self, *, success: bool) -> None:
        """Restore pass-through before removing the owned handler on every exit."""
        with self._lock:
            if not success and self._active is ResourcePolicy.TEXT_FIRST:
                self.disable()
            self._active = ResourcePolicy.OBSERVE_ONLY
            self._phase = None
            if self._installed:
                assert self._context is not None
                try:
                    self._context.unroute("**/*", self._handler)
                except Exception:
                    self._failure = "ROUTE_REMOVE_FAILED"
                    self.disable()
                    # A leftover handler can only continue requests. Keep ownership
                    # so an explicit cleanup retry cannot mistakenly remove others.
                    raise ResourcePolicyError() from None
                self._installed = False
                self._context = None
                self._observer.record_route_handler_removed()

    def _handle(self, route: Route, request: Request) -> None:
        category = "other"
        window: str | None = None
        continuation_attempted = False
        try:
            resource_type = request.resource_type
            category = resource_type if isinstance(resource_type, str) else "other"
            window = self._observer.record_route_event(category, "attempted", request=request)
            with self._lock:
                block = self._phase in {"SEARCH", "DETAIL"} and (
                    self._active is ResourcePolicy.TEXT_FIRST
                    and category in {"image", "media", "font"}
                )
            if block:
                route.abort(error_code="blockedbyclient")
                self._observer.record_route_event(category, "blocked", window=window, request=request)
            else:
                continuation_attempted = True
                route.continue_()
                self._observer.record_route_event(category, "continued", window=window,
                                                  request=request)
        except Exception:
            self._failure = "ROUTE_CALLBACK_FAILED"
            self.disable()
            self._observer.record_route_event(category, "error", window=window, request=request)
            if continuation_attempted:
                return
            try:
                # Release this original stalled request only; not a new request/retry.
                route.continue_()
                self._observer.record_route_event(category, "continued", window=window,
                                                  request=request)
            except Exception:
                pass  # Sanitized failure stays visible; browser cleanup owns the rest.
