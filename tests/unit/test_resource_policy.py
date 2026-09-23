"""Synthetic request routing only; no browser, server, or site access."""

from collections import defaultdict
from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest

from xhs_sidecar.live_observability import LiveNetworkObserver
from xhs_sidecar.resource_policy import (
    ResourcePolicy, ResourcePolicyController, ResourcePolicyError,
)


class FakeRequest:
    def __init__(self, resource, host="www.example.test"):
        self.resource_type = resource
        self.url = f"https://{host}/SECRET_ACCOUNT_ID_T05?xsec_token=SECRET_XSEC_T05"
        self.method = "GET"
        self.frame = SimpleNamespace(parent_frame=None)

    def is_navigation_request(self):
        return self.resource_type == "document"


class FakeRoute:
    def __init__(self, context, request, *, abort_error=False, continue_error=False):
        self.context, self.request = context, request
        self.abort_error, self.continue_error = abort_error, continue_error
        self.abort_calls = self.continue_calls = 0
        self.blocked = self.continued = False

    def abort(self, *, error_code):
        assert error_code == "blockedbyclient"
        self.abort_calls += 1
        if self.abort_error:
            raise RuntimeError("SECRET_XSEC_T05")
        self.blocked = True
        self.context.emit("requestfailed", self.request)

    def continue_(self):
        self.continue_calls += 1
        if self.continue_error:
            raise RuntimeError("SECRET_COOKIE_T05")
        self.continued = True
        self.context.emit("response", SimpleNamespace(request=self.request, status=200))
        self.context.emit("requestfinished", self.request)


class FakeContext:
    def __init__(self):
        self.handlers = defaultdict(list)
        self.routes = []
        self.route_calls = self.unroute_calls = self.dispatched = 0
        self.install_error = self.remove_error = False

    def on(self, event, handler):
        self.handlers[event].append(handler)

    def remove_listener(self, event, handler):
        self.handlers[event].remove(handler)

    def emit(self, event, value):
        for handler in tuple(self.handlers[event]):
            handler(value)

    def route(self, pattern, handler):
        assert pattern == "**/*"
        self.route_calls += 1
        self.routes.append((pattern, handler))
        if self.install_error:
            raise RuntimeError("SECRET_SESSION_T05")

    def unroute(self, pattern, handler):
        self.unroute_calls += 1
        if self.remove_error:
            raise RuntimeError("SECRET_SESSION_T05")
        self.routes.remove((pattern, handler))

    def dispatch(self, resource, **route_options):
        self.dispatched += 1
        request = FakeRequest(resource)
        route = FakeRoute(self, request, **route_options)
        self.emit("request", request)
        if self.routes:
            self.routes[-1][1](route, request)
        else:
            route.continue_()
        return route


def setup_policy(mode=ResourcePolicy.TEXT_FIRST):
    context = FakeContext()
    observer = LiveNetworkObserver()
    observer.attach(context)
    policy = ResourcePolicyController(observer, mode)
    return context, observer, policy


@pytest.mark.parametrize("resource", ["image", "media", "font"])
def test_r16_blocked_resource_still_counts_as_request_event(resource):
    context, observer, policy = setup_policy()
    observer.start_window("SEARCH")
    policy.begin(context, "SEARCH")
    route = context.dispatch(resource)
    policy.end(success=True)
    snapshot = observer.finish_window()
    assert route.blocked and not route.continued
    assert snapshot.total_requests == 1
    assert snapshot.requests[resource] == 1
    assert snapshot.route_attempts == 1
    assert snapshot.blocked_requests == 1 and snapshot.blocked_by_category[resource] == 1
    assert snapshot.continued_requests == 0
    assert snapshot.failed_requests == 1  # Observed requestfailed, not inferred from policy.
    assert snapshot.resource_policy == "TEXT_FIRST"
    assert snapshot.routing_cache_affected is True
    assert snapshot.total_bytes is None
    assert context.routes == []
    assert snapshot.attempted_requests == snapshot.attempted_by_category[resource] == 1
    assert snapshot.allowed_requests == snapshot.allowed_by_category[resource] == 0
    assert snapshot.completed_requests == snapshot.completed_by_category[resource] == 0
    assert snapshot.failed_by_category[resource] == 1
    assert snapshot.unresolved_policy_requests == 0
    assert snapshot.actual_sent_requests is None
    assert snapshot.actual_sent_by_category[resource] is None


@pytest.mark.parametrize("resource", ["document", "xhr", "fetch", "script", "stylesheet", "other"])
def test_r17_text_first_keeps_text_page_dependencies_allowed(resource):
    context, observer, policy = setup_policy()
    observer.start_window("DETAIL_1")
    policy.begin(context, "DETAIL")
    route = context.dispatch(resource)
    policy.end(success=True)
    snapshot = observer.finish_window()
    assert route.continued and not route.blocked
    assert snapshot.total_requests == snapshot.route_attempts == snapshot.continued_requests == 1
    assert snapshot.blocked_requests == 0
    category = "xhr_fetch" if resource in {"xhr", "fetch"} else resource
    assert snapshot.continued_by_category[category] == 1
    assert snapshot.allowed_requests == snapshot.allowed_by_category[category] == 1
    assert snapshot.completed_requests == snapshot.completed_by_category[category] == 1
    assert snapshot.unblocked_request_events == snapshot.unresolved_policy_requests == 0
    assert snapshot.actual_sent_requests is None


def test_r18_failed_phase_disables_optimization_without_dispatching_fallback():
    context, observer, policy = setup_policy()
    observer.start_window("DETAIL_1")
    policy.begin(context, "DETAIL")
    context.dispatch("image")
    policy.end(success=False)
    observer.finish_window()
    assert context.dispatched == 1  # No hidden navigation, reload, or re-issued request.
    assert policy.snapshot()["optimization_disabled"] is True
    assert policy.snapshot()["active"] == "OBSERVE_ONLY"
    assert context.routes == []
    # Only the caller's later explicit operation creates this second window/request.
    observer.start_window("DETAIL_2")
    policy.begin(context, "DETAIL")
    assert context.dispatch("image").continued
    policy.end(success=True)
    fallback = observer.finish_window()
    assert fallback.resource_policy == "OBSERVE_ONLY"
    assert fallback.blocked_requests == fallback.route_attempts == 0
    assert fallback.total_requests == 1
    assert fallback.routing_cache_affected is True  # Not an untouched baseline context.
    assert context.route_calls == context.unroute_calls == 1


def test_r19_unknown_measurement_is_not_zero():
    observer = LiveNetworkObserver()
    ResourcePolicyController(observer).disable()
    missing = observer.snapshot()
    assert missing.measurement == "NOT_MEASURED"
    assert missing.total_requests is missing.total_bytes is None
    assert missing.blocked_requests is missing.continued_requests is missing.route_attempts is None
    assert missing.routing_cache_affected is None


def test_observe_only_default_never_installs_routing_or_changes_cache():
    context, observer, policy = setup_policy(ResourcePolicy.OBSERVE_ONLY)
    observer.start_window("SEARCH")
    policy.begin(context, "SEARCH")
    assert context.dispatch("image").continued
    policy.end(success=True)
    snapshot = observer.finish_window()
    assert context.route_calls == context.unroute_calls == 0
    assert snapshot.total_requests == 1
    assert snapshot.route_attempts == snapshot.continued_requests == 0
    assert snapshot.resource_policy == "OBSERVE_ONLY"
    assert snapshot.routing_cache_affected is False
    assert snapshot.unblocked_request_events == snapshot.allowed_requests == 1
    assert snapshot.completed_requests == snapshot.completed_by_category["image"] == 1
    assert snapshot.actual_sent_measurement == "NOT_MEASURED"


@pytest.mark.parametrize("phase", ["LOGIN", "IDLE"])
def test_login_and_idle_cannot_enable_text_first(phase):
    context, observer, policy = setup_policy()
    observer.start_window("LOGIN")
    with pytest.raises(ResourcePolicyError):
        policy.begin(context, phase)
    assert context.dispatch("image").continued
    assert context.routes == []
    assert observer.snapshot("LOGIN").blocked_requests == 0
    assert policy.snapshot()["active"] == "OBSERVE_ONLY"


def test_successful_exit_restores_idle_and_removes_only_owned_handler():
    context, observer, policy = setup_policy()
    def foreign_handler(route, request):
        route.continue_()
    context.routes.append(("**/*", foreign_handler))
    observer.start_window("SEARCH")
    policy.begin(context, "SEARCH")
    assert context.dispatch("font").blocked
    policy.end(success=True)
    observer.finish_window()
    assert context.routes == [("**/*", foreign_handler)]
    assert context.dispatch("image").continued
    assert observer.snapshot("OUTSIDE_WINDOW").total_requests == 1
    assert observer.snapshot("OUTSIDE_WINDOW").blocked_requests == 0
    assert policy.snapshot()["active"] == "OBSERVE_ONLY"


def test_route_abort_error_disables_optimization_and_releases_original_request():
    context, observer, policy = setup_policy()
    observer.start_window("SEARCH")
    policy.begin(context, "SEARCH")
    failed = context.dispatch("image", abort_error=True)
    assert failed.abort_calls == failed.continue_calls == 1
    assert failed.continued
    assert context.dispatch("media").continued
    policy.end(success=True)
    snapshot = observer.finish_window()
    assert snapshot.route_attempts == snapshot.total_requests == 2
    assert snapshot.blocked_requests == 0 and snapshot.continued_requests == 2
    assert snapshot.route_errors == 1
    assert policy.snapshot()["optimization_disabled"] is True


def test_continue_error_is_not_automatically_repeated():
    context, observer, policy = setup_policy()
    observer.start_window("SEARCH")
    policy.begin(context, "SEARCH")
    route = context.dispatch("fetch", continue_error=True)
    policy.end(success=False)
    assert route.continue_calls == 1
    assert observer.finish_window().route_errors == 1


def test_partial_route_install_failure_retains_cleanup_ownership():
    context, observer, policy = setup_policy()
    observer.start_window("SEARCH")
    context.install_error = True
    with pytest.raises(ResourcePolicyError):
        policy.begin(context, "SEARCH")
    assert policy.snapshot()["route_handler_installed"] is True
    policy.end(success=False)
    assert context.routes == []
    assert policy.snapshot()["optimization_disabled"] is True
    assert context.dispatched == 0


def test_unroute_failure_reports_failure_but_leftover_handler_cannot_block():
    context, observer, policy = setup_policy()
    observer.start_window("DETAIL_1")
    policy.begin(context, "DETAIL")
    context.remove_error = True
    with pytest.raises(ResourcePolicyError):
        policy.end(success=True)
    assert policy.snapshot()["active"] == "OBSERVE_ONLY"
    assert policy.snapshot()["route_handler_installed"] is True
    assert context.dispatch("image").continued
    with pytest.raises(ResourcePolicyError):
        policy.begin(context, "DETAIL")
    context.remove_error = False
    policy.end(success=False)
    assert context.routes == []


def test_resource_policy_never_filters_xhr_by_analytics_domain():
    context, observer, policy = setup_policy()
    observer.start_window("SEARCH")
    policy.begin(context, "SEARCH")
    request = FakeRequest("fetch", host="analytics.example.test")
    route = FakeRoute(context, request)
    context.emit("request", request)
    context.routes[-1][1](route, request)
    policy.end(success=True)
    assert route.continued and not route.blocked
    assert observer.finish_window().purposes["analytics"] == 1


def test_r20_policy_stats_and_errors_never_expose_credentials(capsys, caplog):
    context, observer, policy = setup_policy()
    observer.start_window("SEARCH")
    policy.begin(context, "SEARCH")
    context.dispatch("image", abort_error=True)
    policy.end(success=False)
    output = json.dumps(asdict(observer.finish_window())) + json.dumps(policy.snapshot())
    captured = capsys.readouterr()
    assert "SECRET_" not in output + captured.out + captured.err + caplog.text
    assert "xsec_token" not in output
    assert "service_worker_settings_modified" in output


def test_synthetic_repeated_blocked_resource_is_not_claimed_as_confirmed_site_retry():
    context, observer, policy = setup_policy()
    observer.start_window("SEARCH")
    policy.begin(context, "SEARCH")
    routes = [context.dispatch("image"), context.dispatch("image")]
    policy.end(success=True)
    snapshot = observer.finish_window()
    assert all(route.blocked for route in routes)
    assert snapshot.attempted_requests == snapshot.blocked_requests == 2
    assert snapshot.allowed_requests == snapshot.completed_requests == 0
    assert snapshot.repeated_resource_events == 1
    assert snapshot.resource_retry_assessment == snapshot.lazy_load_assessment == "UNKNOWN"
    assert snapshot.actual_sent_requests is snapshot.transferred_bytes is None
