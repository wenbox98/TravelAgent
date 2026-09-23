"""Fixed, non-content diagnostics for one normal detail page; no navigation."""

from collections.abc import Callable
from typing import Literal, cast
from urllib.parse import SplitResult, urlsplit

from pydantic import ValidationError

from .models import ContractModel

Route = Literal[
    "DETAIL_EXPLORE", "DETAIL_SEARCH_RESULT", "OTHER_DETAIL_ID", "LOGIN", "VERIFICATION",
    "OTHER_OFFICIAL_PAGE", "FOREIGN_ORIGIN", "UNEXPECTED_PAGE", "UNKNOWN",
]
PageClassification = Literal[
    "DETAIL_EXPECTED", "LOGIN_REQUIRED", "VERIFICATION_REQUIRED", "ACCESS_DENIED",
    "NOT_FOUND", "REDIRECTED_OTHER_VALID_XHS_PAGE", "ACCESS_LOCATOR_INVALID",
    "IDENTITY_MISMATCH", "UNEXPECTED_PAGE", "UNKNOWN",
]
_split = cast(Callable[[str], SplitResult], getattr(urlsplit, "__wrapped__"))


def detail_route(url: str, note_id: str) -> Route:
    try:
        parts = _split(url)
        if (parts.scheme != "https" or parts.hostname not in {
            "www.xiaohongshu.com", "xiaohongshu.com"
        } or parts.port not in (None, 443) or parts.username or parts.password):
            return "FOREIGN_ORIGIN"
        path = parts.path.removesuffix("/")
        if path == f"/explore/{note_id}":
            return "DETAIL_EXPLORE"
        if path == f"/search_result/{note_id}":
            return "DETAIL_SEARCH_RESULT"
        if path in {"/explore", "/search_result", ""} or path.startswith("/user/profile/"):
            return "OTHER_OFFICIAL_PAGE"
        if path.startswith(("/explore/", "/search_result/")) and len(path.split("/")) == 3:
            return "OTHER_DETAIL_ID"
        if path.split("/")[1] in {"login", "signin"}:
            return "LOGIN"
        if path.split("/")[1] in {"captcha", "verification", "verify"}:
            return "VERIFICATION"
    except (ValueError, IndexError):
        pass
    return "UNEXPECTED_PAGE"


class DetailPageEvidence(ContractModel):
    route: Route = "UNKNOWN"
    identity: Literal["IDENTITY_MATCH", "IDENTITY_MISMATCH", "UNKNOWN"] = "UNKNOWN"
    page_ready: bool = False
    document_title_present: bool = False
    login_present: bool | None = None
    verification_present: bool | None = None
    access_denied: bool = False
    not_found: bool = False
    locator_invalid: bool = False
    error_container_present: bool = False
    map_entry_present: bool = False
    root_note_container: bool = False
    root_note_detail: bool = False
    root_note_scroller: bool = False
    body_container: bool = False
    image_container: bool = False
    author_region: bool = False
    comment_region: bool = False
    title_present: bool = False
    body_present: bool = False
    author_present: bool = False
    images_present: bool = False


def parse_detail_evidence(raw: object) -> DetailPageEvidence:
    try:
        return DetailPageEvidence.model_validate(raw)
    except ValidationError:
        return DetailPageEvidence()  # Never stringify possibly sensitive validation input.


def classify_detail(e: DetailPageEvidence, status: int | None) -> PageClassification:
    if e.route == "FOREIGN_ORIGIN":
        return "UNEXPECTED_PAGE"
    if e.verification_present or e.route == "VERIFICATION":
        return "VERIFICATION_REQUIRED"
    if e.locator_invalid:
        return "ACCESS_LOCATOR_INVALID"
    if e.access_denied or status in {401, 403, 429}:
        return "ACCESS_DENIED"
    if e.not_found or status in {404, 410}:
        return "NOT_FOUND"
    if e.login_present or e.route == "LOGIN":
        return "LOGIN_REQUIRED"
    if status is not None and not 200 <= status < 300:
        return "UNEXPECTED_PAGE"  # Stale positive page state cannot validate a failed response.
    if e.identity == "IDENTITY_MISMATCH" or e.route == "OTHER_DETAIL_ID":
        return "IDENTITY_MISMATCH"
    if e.route == "OTHER_OFFICIAL_PAGE":
        return "REDIRECTED_OTHER_VALID_XHS_PAGE"
    if e.route == "UNEXPECTED_PAGE" or e.error_container_present:
        return "UNEXPECTED_PAGE"
    if (e.route in {"DETAIL_EXPLORE", "DETAIL_SEARCH_RESULT"}
        and e.identity == "IDENTITY_MATCH" and e.page_ready
        and e.login_present is False and e.verification_present is False
        and sum((e.title_present, e.body_present, e.author_present, e.images_present)) >= 2):
        return "DETAIL_EXPECTED"
    return "UNKNOWN"


DETAIL_EVIDENCE_SCRIPT = r"""id => {
  if (!['https://www.xiaohongshu.com','https://xiaohongshu.com'].includes(location.origin))
    return {route:'FOREIGN_ORIGIN'};
  const path = location.pathname.replace(/\/$/,'');
  const route = path === '/explore/'+id ? 'DETAIL_EXPLORE' :
    path === '/search_result/'+id ? 'DETAIL_SEARCH_RESULT' :
    /^\/(captcha|verification|verify)(\/|$)/.test(path) ? 'VERIFICATION' :
    /^\/(login|signin)(\/|$)/.test(path) ? 'LOGIN' :
    /^\/(explore|search_result)\/[^/]+$/.test(path) ? 'OTHER_DETAIL_ID' :
    ['', '/explore', '/search_result'].includes(path) || path.startsWith('/user/profile/') ?
    'OTHER_OFFICIAL_PAGE' : 'UNEXPECTED_PAGE';
  const visible = el => !!el && el.getClientRects().length > 0 &&
    getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
  const any = s => Array.from(document.querySelectorAll(s)).some(visible);
  const errorSelector = '.access-wrapper, .error-wrapper, .not-found-wrapper, .blocked-wrapper';
  const errors = Array.from(document.querySelectorAll(errorSelector)).filter(visible)
    .map(e => (e.textContent || '').slice(0,2000)).join(' ');
  const alerts = Array.from(document.querySelectorAll('[role="dialog"], [role="alert"]'))
    .filter(visible).map(e => (e.textContent || '').slice(0,2000)).join(' ');
  const signals = errors + ' ' + alerts + ' ' + document.title;
  const unwrap = x => x && typeof x === 'object' ?
    (x.value !== undefined ? x.value : x._value !== undefined ? x._value : x) : x;
  const entry = unwrap(unwrap(window.__INITIAL_STATE__?.note?.noteDetailMap)?.[id]);
  const n = unwrap(entry?.note);
  const text = x => typeof x === 'string' && x.trim().length > 0;
  return {
    route, identity: text(n?.noteId) ?
      (n.noteId === id ? 'IDENTITY_MATCH' : 'IDENTITY_MISMATCH') : 'UNKNOWN',
    page_ready:document.readyState === 'complete', document_title_present:text(document.title),
    login_present:route === 'LOGIN' || any('.login-container, .qrcode-img, .login-btn'),
    verification_present:route === 'VERIFICATION' || any('[id*="captcha" i], [class*="captcha" i], ' +
      '[id*="verification" i], [class*="verification" i], iframe[src*="captcha" i], iframe[src*="verify" i]') ||
      /安全验证|请完成验证|滑块验证/.test(signals),
    access_denied:/访问受限|操作频繁|访问异常|异常访问|拒绝访问|私密笔记|仅作者可见|因用户设置|因违规无法查看/.test(signals),
    not_found:/该笔记已被删除|内容因违规已被删除|内容不存在|笔记不存在/.test(errors),
    locator_invalid:/链接.{0,8}(失效|无效|过期)|(签名|xsec_token).{0,8}(无效|失效|过期)/i.test(errors),
    error_container_present:any(errorSelector), map_entry_present:!!n,
    root_note_container:any('#noteContainer'), root_note_detail:any('.note-detail-mask'),
    root_note_scroller:any('.note-scroller'),
    body_container:any('#detail-desc, .note-content .desc, .note-scroller .desc'),
    image_container:any('.note-slider, .media-container, .swiper'),
    author_region:any('.author-container, .note-author'),
    comment_region:any('.comments-container, .comment-list'),
    title_present:text(n?.title), body_present:text(n?.desc),
    author_present:text(n?.user?.nickname) || text(n?.user?.nickName),
    images_present:Array.isArray(n?.imageList) && n.imageList.length > 0
  };
}"""
