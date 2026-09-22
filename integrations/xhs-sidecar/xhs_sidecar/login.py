"""Single local login flow. Only explicit connect navigates; status reads cached state."""

from threading import Event, RLock, Thread
from time import monotonic
from uuid import uuid4

from .browser import AccountIdentity, BrowserManager, LoginObservation
from .models import LoginError, LoginState, LoginStatus
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
        stop_timeout: float = 35,
    ) -> None:
        if min(poll_interval, timeout, stop_timeout) <= 0:
            raise ValueError("登录等待配置无效")
        self.browser, self.profile = browser, profile
        self.audit = audit or SafeAuditLog()
        self._poll_interval, self._timeout, self._stop_timeout = (
            poll_interval,
            timeout,
            stop_timeout,
        )
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
                self._update(status="CHECKING")
                self._start_worker(navigate=False)
                return self._state

    def _finish_worker(self) -> bool:
        if self._thread is not None:
            self._thread.join(self._stop_timeout)
            if self._thread.is_alive():
                with self._lock:
                    self._update(status="ERROR", error_code="FLOW_STOP_TIMEOUT")
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
            )
            self.audit.emit("login_observed")
            return True

    def _fail(self, generation: int, code: LoginError) -> None:
        with self._lock:
            if self._current(generation):
                self._identity = AccountIdentity()
                self._update(status="ERROR", error_code=code, account_identity="UNKNOWN")
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
            while not cancelled.is_set():
                observation = session.observe_login()
                if not self._apply_observation(generation, observation):
                    return
                if observation.state in {"AUTHENTICATED", "VERIFICATION_REQUIRED"}:
                    return
                if monotonic() >= deadline:
                    self._fail(generation, "LOGIN_TIMEOUT")
                    return
                if cancelled.wait(self._poll_interval):
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
                )
                self._identity = AccountIdentity()
                self._cancel.set()
                thread = self._thread
            if thread is not None:
                thread.join(self._stop_timeout)
                if thread.is_alive():
                    with self._lock:
                        self._update(status="ERROR", error_code="FLOW_STOP_TIMEOUT")
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
                    self._update(status="ERROR", error_code="CLEANUP_FAILED")
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
