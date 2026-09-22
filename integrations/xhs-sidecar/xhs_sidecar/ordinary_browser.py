"""Standard Playwright, with every driver call confined to one owned thread."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import os
import re
from threading import RLock
from typing import Literal, TypedDict, TypeVar
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from pydantic import SecretStr

from .browser import AccountIdentity, BrowserError, BrowserOptions, LoginObservation, SessionClosed
from .profile import ProfileStore


_T = TypeVar("_T")
_OPERATION_TIMEOUT = 20.0
LOGIN_URL = "https://www.xiaohongshu.com/explore"

# Only existing DOM/page state is read. No fetch, clicks, QR extraction, or navigation.
# Login selector and userInfo shape were reviewed at the fixed upstream commit.
LOGIN_OBSERVATION_SCRIPT = r"""() => {
  if (!['https://www.xiaohongshu.com', 'https://xiaohongshu.com'].includes(location.origin))
    return {state: 'UNKNOWN'};
  const visible = el => !!el && el.getClientRects().length > 0 &&
    getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
  const anyVisible = selector => Array.from(document.querySelectorAll(selector)).some(visible);
  const challenge = anyVisible('[id*="captcha" i], [class*="captcha" i], ' +
    '[id*="verification" i], [class*="verification" i], ' +
    'iframe[src*="captcha" i], iframe[src*="verify" i]');
  const alerts = Array.from(document.querySelectorAll('[role="dialog"], [role="alert"]'))
    .filter(visible).map(el => (el.textContent || '').slice(0, 2000)).join(' ');
  const blocked = /安全验证|请完成验证|访问受限|操作频繁|滑块验证/.test(alerts) ||
    /安全验证|访问受限/.test(document.title) || /\/(captcha|verification|verify)(\/|$)/i.test(location.pathname);
  if (challenge || blocked) return {state: 'VERIFICATION_REQUIRED'};
  if (anyVisible('.login-container, .login-btn, .qrcode-img')) return {state: 'LOGIN_REQUIRED'};
  if (!anyVisible('.main-container .user .link-wrapper .channel')) return {state: 'UNKNOWN'};
  const user = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.user;
  const raw = user && user.userInfo;
  const info = raw && raw.value !== undefined ? raw.value : raw;
  if (info && info.guest) return {state: 'LOGIN_REQUIRED'};
  const id = info && !info.guest && (info.userId || info.user_id);
  return {state: 'AUTHENTICATED', stable_id: typeof id === 'string' ? id : null};
}"""


class LaunchConfiguration(TypedDict):
    user_data_dir: str
    headless: Literal[False]
    channel: str | None
    no_viewport: Literal[True]
    chromium_sandbox: Literal[True]
    timeout: float
    args: list[str]


def launch_configuration(options: BrowserOptions, profile_path: str) -> LaunchConfiguration:
    """The exact application options; standard Playwright defaults remain enabled."""
    if options.headless:
        raise BrowserError()
    return {
        "user_data_dir": profile_path,
        "headless": False,
        "channel": "chrome" if options.engine == "chrome" else None,
        "no_viewport": True,
        "chromium_sandbox": True,
        "timeout": 15_000,
        "args": [],
    }


class OrdinaryBrowserBackend:
    kind = "playwright"

    def __init__(self, profile: ProfileStore) -> None:
        self.profile = profile
        self._pending: OrdinaryBrowserResource | None = None

    def start(self, options: BrowserOptions) -> "OrdinaryBrowserResource":
        # Driver debug output can include arguments, URLs and evaluated account data.
        forbidden = {
            "debug",
            "debug_file",
            "pwdebug",
            "pwdebugimpl",
            "node_options",
            "node_path",
            "playwright_nodejs_path",
            "playwright_legacy_screenshot",
            "playwright_chromium_debug_port",
            "pw_chromium_attach_to_other",
            "selenium_remote_url",
            "selenium_remote_capabilities",
            "selenium_remote_headers",
            "npm_config_pwdebug",
            "npm_package_config_pwdebug",
            "npm_config_pwdebugimpl",
            "npm_package_config_pwdebugimpl",
        }
        if any(name.casefold() in forbidden for name in os.environ):
            raise BrowserError()
        if self._pending is not None:
            raise BrowserError()
        launch_configuration(options, str(self.profile.get_profile_path()))
        resource = OrdinaryBrowserResource()
        self._pending = resource
        try:
            resource.start(self.profile, options)
        except Exception:
            try:
                self.close()
            except Exception:
                pass  # Retain ownership for an explicit cleanup retry.
            raise BrowserError() from None
        self._pending = None
        return resource

    def close(self) -> None:
        if self._pending is not None:
            self._pending.close()
            self._pending = None


class OrdinaryBrowserResource:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xhs-browser")
        self._lock = RLock()
        self._driver: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._opened = False
        self._revoked = False
        self._closed = False

    def start(self, profile: ProfileStore, options: BrowserOptions) -> None:
        self._run(lambda: self._start(profile, options))

    def _run(self, operation: Callable[[], _T]) -> _T:
        try:
            # Timeout does NOT cancel native work. The same executor retains ownership,
            # and a later close must finish behind it before deletion can be authorized.
            return self._executor.submit(operation).result(timeout=_OPERATION_TIMEOUT)
        except Exception:
            raise BrowserError() from None

    def _start(self, profile: ProfileStore, options: BrowserOptions) -> None:
        path = profile.prepare()
        self._driver = sync_playwright().start()
        self._context = self._driver.chromium.launch_persistent_context(
            **launch_configuration(options, str(path))
        )
        self._context.set_default_timeout(3_000)
        self._context.set_default_navigation_timeout(15_000)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def open_login(self) -> None:
        with self._lock:
            if self._revoked:
                raise SessionClosed()
            if not self._opened:
                # A failed navigation must not be silently replayed on the same resource.
                self._opened = True
                self._run(self._navigate)

    def _navigate(self) -> None:
        if self._page is None:
            raise BrowserError()
        self._page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15_000)

    def observe_login(self) -> LoginObservation:
        with self._lock:
            if self._revoked:
                raise SessionClosed()
            return self._run(self._observe)

    def _observe(self) -> LoginObservation:
        if self._page is None or not self._opened:
            raise BrowserError()
        # The visible window can be navigated manually; never trust another origin's DOM.
        try:
            current = urlsplit(self._page.url)
            official = (
                current.scheme == "https"
                and current.hostname in {"www.xiaohongshu.com", "xiaohongshu.com"}
                and current.port in {None, 443}
            )
        except ValueError:
            official = False
        if not official:
            return LoginObservation("UNKNOWN")
        raw: object = self._page.locator("body").evaluate(LOGIN_OBSERVATION_SCRIPT, timeout=3_000)
        if not isinstance(raw, dict):
            return LoginObservation("UNKNOWN")
        state = raw.get("state")
        if state == "AUTHENTICATED":
            account = raw.get("stable_id")
            identity = AccountIdentity()
            if isinstance(account, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", account):
                identity = AccountIdentity(SecretStr(account))
            return LoginObservation("AUTHENTICATED", identity)
        if state == "LOGIN_REQUIRED":
            return LoginObservation("LOGIN_REQUIRED")
        if state == "VERIFICATION_REQUIRED":
            return LoginObservation("VERIFICATION_REQUIRED")
        return LoginObservation("UNKNOWN")

    def close(self) -> None:
        with self._lock:
            self._revoked = True
            if not self._closed:
                self._run(self._close_owned)
                self._closed = True
                self._executor.shutdown(wait=True, cancel_futures=True)

    def _close_owned(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
            self._page = None
        if self._driver is not None:
            self._driver.stop()
            self._driver = None
