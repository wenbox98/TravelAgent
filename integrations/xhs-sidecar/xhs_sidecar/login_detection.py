"""Same-page evidence extraction and conservative, independently testable classification."""

import re
from typing import Literal

from pydantic import SecretStr, ValidationError

from .browser import AccountIdentity, LoginObservation
from .models import LoginEvidence


# T03.7 observed userInfo.value and userInfo._value with explicit guest=false.
# T03.8 observed a visible self-labelled link to the official /user/profile/<id>.
# The legacy entry is diagnostic only, never an authentication prerequisite.
# No fetch, navigation, QR extraction, cookie access or serialized page state.
LOGIN_OBSERVATION_SCRIPT = r"""() => {
  if (!['https://www.xiaohongshu.com', 'https://xiaohongshu.com'].includes(location.origin))
    return {evidence: {current_url_classification: 'FOREIGN_ORIGIN'}};
  const visible = el => !!el && el.getClientRects().length > 0 &&
    getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
  const anyVisible = selector => Array.from(document.querySelectorAll(selector)).some(visible);
  const verificationRoute = /\/(captcha|verification|verify)(\/|$)/i.test(location.pathname);
  const loginRoute = /\/(login|signin)(\/|$)/i.test(location.pathname);
  const route = verificationRoute ? 'VERIFICATION' : loginRoute ? 'LOGIN' :
    /^\/explore\/?$/.test(location.pathname) ? 'OFFICIAL_PAGE' : 'OTHER_OFFICIAL_PAGE';
  const challenge = anyVisible('[id*="captcha" i], [class*="captcha" i], ' +
    '[id*="verification" i], [class*="verification" i], ' +
    'iframe[src*="captcha" i], iframe[src*="verify" i]');
  const alerts = Array.from(document.querySelectorAll('[role="dialog"], [role="alert"]'))
    .filter(visible).map(el => (el.textContent || '').slice(0, 2000)).join(' ');
  const restricted = /访问受限|操作频繁|访问异常|异常访问|拒绝访问/.test(alerts) ||
    /访问受限|访问异常|异常访问|拒绝访问/.test(document.title);
  const verification = verificationRoute || challenge ||
    /安全验证|请完成验证|滑块验证/.test(alerts) || /安全验证/.test(document.title);
  const user = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.user;
  const raw = user && user.userInfo;
  const candidates = raw && typeof raw === 'object' ?
    [raw.value, raw._value, raw].filter(info => info && typeof info === 'object') : [];
  // A guest indication wins over stale/conflicting authenticated snapshots.
  const guest = candidates.some(info => info.guest === true);
  const authenticated = guest ? false : candidates.some(info => info.guest === false) ? true : null;
  const ids = [...new Set(candidates.map(info => info.userId || info.user_id)
    .filter(id => typeof id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(id)))];
  const stableId = !guest && ids.length === 1 ? ids[0] : null;
  // Read normal navigation links without opening them. Names/URLs stay in this page.
  const accountLinks = Array.from(document.querySelectorAll('a[href]')).filter(el => {
    if (!visible(el) || !['我','我的主页','个人中心'].includes((el.textContent || '').trim())) return false;
    try {
      const url = new URL(el.getAttribute('href'), location.origin);
      return url.origin === location.origin && /^\/user\/profile\/[A-Za-z0-9_-]{1,128}\/?$/.test(url.pathname);
    } catch { return false; }
  });
  const entryMatches = stableId !== null && accountLinks.some(el => {
    const path = new URL(el.getAttribute('href'), location.origin).pathname;
    return path.replace(/\/$/, '') === '/user/profile/' + stableId;
  });
  return {evidence: {
    current_url_classification: route,
    page_ready: document.readyState === 'complete',
    login_dialog_present: anyVisible('.login-container, .qrcode-img'),
    login_button_present: anyVisible('.login-btn'),
    authenticated_account_entry_present: accountLinks.length > 0,
    account_entry_identity_matches: entryMatches,
    legacy_account_entry_present: anyVisible('.main-container .user .link-wrapper .channel'),
    authenticated_user_state: authenticated,
    account_identity_available: stableId !== null,
    verification_present: verification,
    access_restriction_present: restricted
  }, stable_id: stableId};
}"""


def classify_login_evidence(
    evidence: LoginEvidence,
) -> Literal["AUTHENTICATED", "LOGIN_REQUIRED", "VERIFICATION_REQUIRED", "UNKNOWN"]:
    if evidence.current_url_classification in {"UNKNOWN", "FOREIGN_ORIGIN"}:
        return "UNKNOWN"
    if (
        evidence.verification_present is True
        or evidence.access_restriction_present is True
        or evidence.current_url_classification == "VERIFICATION"
    ):
        return "VERIFICATION_REQUIRED"
    if (
        evidence.login_dialog_present is True
        or evidence.login_button_present is True
        or evidence.authenticated_user_state is False
        or evidence.current_url_classification == "LOGIN"
    ):
        return "LOGIN_REQUIRED"
    if evidence.current_url_classification != "OFFICIAL_PAGE" or evidence.page_ready is not True:
        return "UNKNOWN"
    # Missing negative observations are not the same as observed absence.
    if any(signal is not False for signal in (
        evidence.verification_present, evidence.access_restriction_present,
        evidence.login_dialog_present, evidence.login_button_present,
    )):
        return "UNKNOWN"
    if evidence.authenticated_user_state is True or (
        evidence.authenticated_account_entry_present is True
        and evidence.account_identity_available
        and evidence.account_entry_identity_matches
    ):
        return "AUTHENTICATED"
    return "UNKNOWN"


def parse_login_observation(raw: object) -> LoginObservation:
    if not isinstance(raw, dict):
        return LoginObservation("UNKNOWN", evidence=LoginEvidence())
    try:
        evidence = LoginEvidence.model_validate(raw.get("evidence"))
    except ValidationError:
        # Never format validation errors: they may contain private page data.
        return LoginObservation("UNKNOWN", evidence=LoginEvidence())
    account = raw.get("stable_id")
    valid_id = isinstance(account, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", account)
    evidence = evidence.model_copy(update={
        "account_identity_available": bool(valid_id and evidence.account_identity_available)
    })
    state = classify_login_evidence(evidence)
    identity = AccountIdentity()
    if state == "AUTHENTICATED" and evidence.account_identity_available and isinstance(account, str):
        identity = AccountIdentity(SecretStr(account))
    return LoginObservation(state, identity, evidence)
