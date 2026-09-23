"""Single local login flow. Only explicit connect navigates; status reads cached state."""

from math import isfinite
from threading import Event, RLock, Thread
from time import monotonic
from uuid import uuid4

from .browser import AccountIdentity, BrowserManager, LoginObservation
from .models import LoginError, LoginState, LoginStatus, LoginStopReason
from .profile import ProfileStore
from .redaction import SafeAuditLog


class LoginLifecycle:
    def __init__(
        self,
        browser: BrowserManager,
        profile: ProfileStore,
        *,
        audit: SafeAuditLog | None = None,
        poll_interval: float = 0.5,
        timeout: float = 240,
        observation_timeout: float = 30,
        max_observations: int = 480,
        stop_timeout: float = 35,
    ) -> None:
        if any(not isfinite(value) or value <= 0 for value in (
            poll_interval, timeout, observation_timeout, stop_timeout
        )) or type(max_observations) is not int or not 1 <= max_observations <= 10_000:
            raise ValueError("登录等待配置无效")
        self.browser, self.profile = browser, profile
        self.audit = audit or SafeAuditLog()
        self._poll_interval, self._timeout, self._stop_timeout = (
            poll_interval,
            timeout,
            stop_timeout,
        )
        self._observation_timeout = observation_timeout
        self._max_observations = max_observations
        self._lock = RLock()
        self._operations = RLock()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._identity = AccountIdentity()
        self._had_profile = profile.exists()  # Filesystem only; no browser/cookie verification.
        self._state = LoginState(
            mode="login",
            status="SESSION_PRESENT_UNVERIFIED" if self._had_profile else "DISCONNECTED",
        )

    def status(self) -> LoginState:
        with self._lock:
            return self._state

    def _update(self, **changes: object) -> None:
        self._state = LoginState.model_validate({**self._state.model_dump(), **changes})

    def _current(self, generation: int) -> bool:
        return generation == self._state.generation and not self._cancel.is_set()

    def connect(self) -> LoginState:
        with self._operations:
            with self._lock:
                recheck = self._state.status == "AUTHENTICATED"
                if self._state.status not in {
                    "DISCONNECTED",
                    "SESSION_PRESENT_UNVERIFIED",
                    "CANCELLED",
                    "AUTHENTICATED",
                }:
                    # ERROR also requires explicit cleanup before a new attempt.
                    return self._state
            if recheck and not self._finish_worker():
                return self.status()
            with self._lock:
                self._cancel = Event()
                self._identity = AccountIdentity()
                self._had_profile = self.profile.exists()
                self._update(
                    status="CHECKING" if recheck else "STARTING_BROWSER",
                    generation=self._state.generation + 1,
                    flow_id=uuid4().hex,
                    remote_checked=False,
                    error_code=None,
                    account_identity="UNKNOWN",
                    evidence=None,
                    observation_attempts=0,
                    stop_reason=None,
                )
                self._start_worker(navigate=not recheck)
                return self._state

    def _start_worker(self, *, navigate: bool) -> None:
        self._thread = Thread(
            target=self._run,
            args=(self._state.generation, self._cancel, navigate),
            name="xhs-login",
            daemon=True,
        )
        self._thread.start()

    def resume(self) -> LoginState:
        with self._operations:
            with self._lock:
                if self._state.status != "VERIFICATION_REQUIRED":
                    return self._state
            # A terminal state may be visible just before its worker returns. Join outside
            # the state lock so an immediate explicit resume is not silently discarded.
            if not self._finish_worker():
                return self.status()
            with self._lock:
                self._update(
                    status="CHECKING", evidence=None, observation_attempts=0, stop_reason=None
                )
                self._start_worker(navigate=False)
                return self._state

    def _finish_worker(self) -> bool:
        if self._thread is not None:
            self._thread.join(self._stop_timeout)
            if self._thread.is_alive():
                with self._lock:
                    self._update(
                        status="ERROR", error_code="FLOW_STOP_TIMEOUT", stop_reason="FLOW_STOP_TIMEOUT"
                    )
                return False
        return True

    def _apply_observation(self, generation: int, observation: LoginObservation) -> bool:
        with self._lock:
            if not self._current(generation):
                return False
            state: LoginStatus
            if observation.state == "AUTHENTICATED":
                self._identity = observation.identity
                if self._identity.stable_id is not None:
                    self.audit.redactor.register(self._identity.stable_id)
                state = "AUTHENTICATED"
            elif observation.state == "LOGIN_REQUIRED":
                state = "LOGIN_REQUIRED" if self._had_profile else "WAITING_USER"
                self._identity = AccountIdentity()
            elif observation.state == "VERIFICATION_REQUIRED":
                state = "VERIFICATION_REQUIRED"
                self._identity = AccountIdentity()
            else:
                state = "CHECKING"
            self._update(
                status=state,
                remote_checked=True,
                account_identity="KNOWN" if self._identity.stable_id is not None else "UNKNOWN",
                evidence=observation.evidence,
                observation_attempts=self._state.observation_attempts + 1,
                stop_reason=state if state in {"AUTHENTICATED", "VERIFICATION_REQUIRED"} else None,
            )
            self.audit.emit("login_observed")
            return True

    def _fail(
        self, generation: int, code: LoginError, reason: LoginStopReason | None = None
    ) -> None:
        with self._lock:
            if self._current(generation):
                self._identity = AccountIdentity()
                self._update(
                    status="ERROR", error_code=code, account_identity="UNKNOWN",
                    stop_reason=reason or (
                        "OBSERVATION_TIMEOUT" if code == "LOGIN_STATE_UNCERTAIN" else code
                    ),
                )
                self.audit.emit("request_failed", outcome="internal_error")

    def _run(self, generation: int, cancelled: Event, navigate: bool) -> None:
        try:
            if cancelled.is_set():
                return
            if navigate:
                self.profile.prepare()
                session = self.browser.start()
                if cancelled.is_set():
                    return
                session.open_login()
            else:
                session = self.browser.get_session()
            with self._lock:
                if not self._current(generation):
                    return
                self._update(status="CHECKING")
            deadline = monotonic() + self._timeout
            unknown_since: float | None = None
            attempts = 0
            while not cancelled.is_set():
                started = monotonic()
                if started >= deadline:
                    self._fail(generation, "LOGIN_TIMEOUT")
                    return
                if unknown_since is not None and started - unknown_since >= self._observation_timeout:
                    self._fail(generation, "LOGIN_STATE_UNCERTAIN", "OBSERVATION_TIMEOUT")
                    return
                if attempts >= self._max_observations:
                    self._fail(generation, "LOGIN_STATE_UNCERTAIN", "OBSERVATION_LIMIT")
                    return
                observation = session.observe_login()
                attempts += 1
                now = monotonic()
                expired_unknown = (
                    unknown_since is not None and now - unknown_since >= self._observation_timeout
                )
                if (now >= deadline or expired_unknown) and observation.state != "VERIFICATION_REQUIRED":
                    # A late positive result must not briefly publish AUTHENTICATED.
                    with self._lock:
                        if self._current(generation):
                            self._update(
                                evidence=observation.evidence,
                                observation_attempts=attempts,
                                remote_checked=True,
                            )
                    if now >= deadline:
                        self._fail(generation, "LOGIN_TIMEOUT")
                    else:
                        self._fail(generation, "LOGIN_STATE_UNCERTAIN", "OBSERVATION_TIMEOUT")
                    return
                if not self._apply_observation(generation, observation):
                    return
                if observation.state in {"AUTHENTICATED", "VERIFICATION_REQUIRED"}:
                    return
                unknown_since = (
                    (unknown_since if unknown_since is not None else started)
                    if observation.state == "UNKNOWN" else None
                )
                if unknown_since is not None and now - unknown_since >= self._observation_timeout:
                    self._fail(generation, "LOGIN_STATE_UNCERTAIN", "OBSERVATION_TIMEOUT")
                    return
                remaining = deadline - now
                if unknown_since is not None:
                    remaining = min(remaining, self._observation_timeout - (now - unknown_since))
                if cancelled.wait(min(self._poll_interval, max(0, remaining))):
                    return
        except Exception:
            # Browser exceptions can contain DOM, URLs and credentials; never log/chain them.
            self._fail(generation, "BROWSER_ERROR")

    def _stop(self, *, delete: bool, shutdown: bool = False) -> LoginState:
        with self._operations:
            with self._lock:
                # Revoke FIRST. No late worker can publish while close/deletion is in flight.
                self._update(
                    generation=self._state.generation + 1,
                    status="CANCELLED",
                    flow_id=None,
                    account_identity="UNKNOWN",
                    error_code=None,
                    remote_checked=False,
                    evidence=None,
                    stop_reason="SHUTDOWN" if shutdown else "DISCONNECTED" if delete else "CANCELLED",
                )
                self._identity = AccountIdentity()
                self._cancel.set()
                thread = self._thread
            if thread is not None:
                thread.join(self._stop_timeout)
                if thread.is_alive():
                    with self._lock:
                        self._update(
                            status="ERROR", error_code="FLOW_STOP_TIMEOUT",
                            stop_reason="FLOW_STOP_TIMEOUT",
                        )
                        self.audit.emit("request_failed", outcome="internal_error")
                        return self._state
            try:
                self.browser.close()
                if delete:
                    self.profile.clear_profile()
                with self._lock:
                    state: LoginStatus = "DISCONNECTED" if delete else "CANCELLED"
                    if shutdown:
                        state = (
                            "SESSION_PRESENT_UNVERIFIED"
                            if self.profile.exists()
                            else "DISCONNECTED"
                        )
                    self._update(status=state)
                    self.audit.emit("session_closed")
            except Exception:
                with self._lock:
                    self._update(
                        status="ERROR", error_code="CLEANUP_FAILED", stop_reason="CLEANUP_FAILED"
                    )
                    self.audit.emit("request_failed", outcome="internal_error")
            return self.status()

    def cancel(self) -> LoginState:
        """Invalidate and close the owned window, retaining the dedicated profile."""
        return self._stop(delete=False)

    def disconnect(self) -> LoginState:
        """Invalidate, close, then remove only the owned profile; report any cleanup failure."""
        return self._stop(delete=True)

    def shutdown(self) -> LoginState:
        return self._stop(delete=False, shutdown=True)
