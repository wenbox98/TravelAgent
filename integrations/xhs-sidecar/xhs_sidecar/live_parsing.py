"""Private, memory-only parsing of already observed official page data.

These objects are not HTTP/Evidence contracts. Never serialize them with
``dataclasses.asdict``: only ``safe_summary`` is suitable for logs or reports.
No browser, network, image analysis or content inference is performed here.
"""

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Literal, cast
from urllib.parse import SplitResult, parse_qs, urlsplit

from pydantic import SecretStr

from .completeness import classify_completeness
from .models import AccessLocator, Classification, RawDetail, SourceIdentity

FieldStatus = Literal["OBSERVED", "DERIVED", "NOT_AVAILABLE"]
NoteType = Literal["normal", "video", "unknown"]
_NOTE_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_ORIGIN = "https://www.xiaohongshu.com"
_HOSTS = {"www.xiaohongshu.com", "xiaohongshu.com"}
_INTERACTION_KEYS = ("likedCount", "sharedCount", "commentCount", "collectedCount")
_split_uncached = cast(Callable[[str], SplitResult], getattr(urlsplit, "__wrapped__"))


class LiveParseError(RuntimeError):
    """Fixed safe error; never interpolate external data or validation errors."""

    def __init__(self) -> None:
        super().__init__("页面数据无法安全解析")


def _mapping(value: object) -> dict[str, object] | None:
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return cast(dict[str, object], value)
    return None


def _unwrapped(value: object) -> object:
    for _ in range(3):
        data = _mapping(value)
        if data is None:
            break
        if "value" in data:
            value = data["value"]
        elif "_value" in data:
            value = data["_value"]
        else:
            break
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _present(value: object) -> FieldStatus:
    return "OBSERVED" if value is not None else "NOT_AVAILABLE"


def _note_type(value: object) -> NoteType:
    return value if value in ("normal", "video") else "unknown"


def _time(value: object) -> int | None:
    # Keep the observed timestamp as-is; no invented conversion or travel date.
    return value if type(value) is int and value > 0 else None


def _first_text(
    data: dict[str, object], keys: tuple[str, ...], prefix: str,
) -> tuple[str | None, str | None]:
    for key in keys:
        value = _text(data.get(key))
        if value is not None:
            return value, f"{prefix}.{key}"
    return None, None


def _publication(
    data: dict[str, object], prefix: str,
) -> tuple[int | str | None, str | None]:
    # Explicitly named fields only. Preserve their observed representation, with
    # no conversion to a travel date or inference from card/body text.
    for key in ("time", "publishTime", "publishedAt"):
        value = _time(data.get(key))
        text = _text(data.get(key))
        if value is not None or text is not None:
            return value if value is not None else text, f"{prefix}.{key}"
    return None, None


def _anonymized(source: SourceIdentity) -> str:
    return "xhs-sha256:" + sha256(source.source_id.encode("utf-8")).hexdigest()[:24]


def _bool(value: object) -> bool | None:
    return value if type(value) is bool else None


def _source(value: object) -> SourceIdentity | None:
    if not isinstance(value, str) or _NOTE_ID.fullmatch(value) is None:
        return None
    return SourceIdentity(note_id=value)


def _interaction_fields(value: object) -> tuple[str, ...]:
    data = _mapping(value)
    if data is None:
        return ()
    return tuple(
        key for key in _INTERACTION_KEYS
        if _text(data.get(key)) is not None or type(data.get(key)) is int
    )


def _cover_present(value: object) -> bool:
    data = _mapping(value)
    if data is None:
        return False
    if any(_text(data.get(key)) for key in ("url", "urlPre", "urlDefault", "fileId")):
        return True
    infos = data.get("infoList")
    return isinstance(infos, list) and any(
        item is not None and _text(item.get("url")) is not None
        for item in (_mapping(info) for info in infos)
    )


@dataclass(frozen=True, repr=False)
class LiveCandidate:
    source: SourceIdentity
    locator: AccessLocator | None
    href: SecretStr | None
    title: str | None
    note_type: NoteType
    author_display: str | None
    published_at: int | str | None
    summary: str | None
    field_status: dict[str, FieldStatus]
    interaction_fields: tuple[str, ...]
    xsec_token_available: bool
    field_sources: dict[str, str]

    def __repr__(self) -> str:
        return "LiveCandidate(private)"

    def safe_summary(self) -> dict[str, object]:
        return {
            "anonymized_source_id": _anonymized(self.source),
            "note_type": self.note_type,
            "field_status": dict(self.field_status),
            "field_sources": dict(self.field_sources),
            "detail_access_available": self.locator is not None and self.href is not None,
            "xsec_token_available": self.xsec_token_available,
            "interaction_fields": list(self.interaction_fields),
        }


@dataclass(frozen=True, repr=False)
class LiveSearch:
    candidates: tuple[LiveCandidate, ...]
    raw_count: int
    dropped_count: int
    duplicate_count: int
    observed_raw_count: int | None = None
    batch_capped: bool | None = None

    def __repr__(self) -> str:
        return "LiveSearch(private)"

    def safe_summary(self) -> dict[str, object]:
        return {
            "candidate_count": len(self.candidates),
            "raw_count": self.raw_count,
            "observed_raw_count": self.observed_raw_count,
            "batch_capped": self.batch_capped,
            "dropped_count": self.dropped_count,
            "duplicate_count": self.duplicate_count,
            "candidates": [candidate.safe_summary() for candidate in self.candidates],
        }


def _observed_links(value: object, session_id: str) -> dict[str, tuple[AccessLocator, SecretStr]]:
    """Validate observed URLs, preserving their actual source and token parameters."""
    result: dict[str, tuple[AccessLocator, SecretStr]] = {}
    if not isinstance(value, list):
        return result
    for item in value:
        data = _mapping(item)
        if data is None:
            continue
        source = _source(data.get("note_id"))
        href = _text(data.get("href"))
        if source is None or href is None or len(href) > 16_384:
            continue
        if "\\" in href or any(char.isspace() or ord(char) < 32 for char in href):
            continue
        try:
            # Avoid urljoin/urlsplit caches retaining credential-bearing hrefs.
            # Only root-relative and absolute HTTPS links are supported.
            if href.startswith("/") and not href.startswith("//"):
                absolute = _ORIGIN + href
            elif href.startswith("https://"):
                absolute = href
            else:
                continue
            parsed = _split_uncached(absolute)
            if (
                parsed.scheme != "https" or parsed.hostname not in _HOSTS
                or parsed.port not in (None, 443) or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in (
                    f"/explore/{source.note_id}", f"/search_result/{source.note_id}"
                )
            ):
                continue
            query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=50)
            tokens = query.get("xsec_token", [])
            if len(tokens) != 1 or not tokens[0] or len(tokens[0]) > 4096:
                continue
            if len(query.get("xsec_source", [])) > 1:
                continue
        except ValueError:
            continue
        result.setdefault(
            source.note_id,
            (AccessLocator(source, session_id, SecretStr(tokens[0])), SecretStr(absolute)),
        )
    return result


def parse_search(payload: object, session_id: str) -> LiveSearch:
    """Parse one finite page observation; missing state differs from an empty list."""
    data = _mapping(payload)
    if data is None or not isinstance(session_id, str) or not session_id:
        raise LiveParseError()
    feeds = _unwrapped(data.get("feeds"))
    if not isinstance(feeds, list):
        raise LiveParseError()
    count_value = data.get("observed_raw_count")
    observed_raw_count = count_value if type(count_value) is int else None
    batch_capped = _bool(data.get("batch_capped"))
    if (
        ("observed_raw_count" in data and observed_raw_count is None)
        or ("batch_capped" in data and batch_capped is None)
        or (observed_raw_count is not None and observed_raw_count < len(feeds))
        or (observed_raw_count is not None and batch_capped is not None
            and batch_capped != (observed_raw_count > len(feeds)))
    ):
        raise LiveParseError()
    links = _observed_links(data.get("links"), session_id)
    candidates: list[LiveCandidate] = []
    seen: set[str] = set()
    dropped = duplicates = 0
    for value in feeds:
        feed = _mapping(_unwrapped(value))
        card = _mapping(_unwrapped(feed.get("noteCard"))) if feed is not None else None
        source = _source(feed.get("id")) if feed is not None else None
        if feed is None or feed.get("modelType") != "note" or not card or source is None:
            dropped += 1
            continue
        if source.note_id in seen:
            duplicates += 1
            continue
        seen.add(source.note_id)
        title, title_source = _first_text(card, ("displayTitle", "title"), "noteCard")
        note_type = _note_type(card.get("type"))
        user = _mapping(card.get("user")) or {}
        author, author_source = _first_text(user, ("nickname", "nickName"), "noteCard.user")
        published_at, publication_source = _publication(card, "noteCard")
        summary, summary_source = _first_text(card, ("summary", "snippet"), "noteCard")
        interactions = _interaction_fields(card.get("interactInfo"))
        locator, href = links.get(source.note_id, (None, None))
        token_available = locator is not None or _text(feed.get("xsecToken")) is not None
        statuses: dict[str, FieldStatus] = {
            "note_id": "OBSERVED",
            "source_id": "DERIVED",
            "title": _present(title),
            "author_display": _present(author),
            "note_type": "OBSERVED" if note_type != "unknown" else "NOT_AVAILABLE",
            "cover": "OBSERVED" if _cover_present(card.get("cover")) else "NOT_AVAILABLE",
            "interaction_metadata": "OBSERVED" if interactions else "NOT_AVAILABLE",
            "access_locator": "OBSERVED" if locator is not None else "NOT_AVAILABLE",
            "publish_time": _present(published_at),
            "summary": _present(summary),
            "destination": "NOT_AVAILABLE",
            "location": "NOT_AVAILABLE",
            "travel_time": "NOT_AVAILABLE",
        }
        field_sources = {"note_id": "feed.id"}
        for key, path in (
            ("title", title_source), ("author_display", author_source),
            ("publish_time", publication_source), ("summary", summary_source),
            ("note_type", "noteCard.type"), ("cover", "noteCard.cover"),
            ("interaction_metadata", "noteCard.interactInfo"),
            ("access_locator", "links.href"),
        ):
            if path is not None and statuses[key] == "OBSERVED":
                field_sources[key] = path
        candidates.append(LiveCandidate(
            source, locator, href, title, note_type, author, published_at, summary,
            statuses, interactions, token_available, field_sources,
        ))
    return LiveSearch(
        tuple(candidates), len(feeds), dropped, duplicates, observed_raw_count, batch_capped,
    )


@dataclass(frozen=True, repr=False)
class LiveDetail:
    raw: RawDetail
    classification: Classification
    source_locator: str | None
    note_type: NoteType
    field_status: dict[str, FieldStatus]
    image_count: int
    http_status: int | None
    dom_body_found: bool
    dom_body_matches: bool
    expandable: bool | None
    truncated: bool | None

    def __repr__(self) -> str:
        return "LiveDetail(private)"

    def safe_summary(self) -> dict[str, object]:
        return {
            "anonymized_source_id": _anonymized(self.raw.source),
            "note_type": self.note_type,
            "field_status": dict(self.field_status),
            "body_chars": len(self.raw.body or ""),
            "image_count": self.image_count,
            "image_analysis": "IMAGE_NOT_ANALYZED" if self.image_count else "NOT_AVAILABLE",
            "completeness": self.classification.completeness,
            "completeness_reason": self.classification.reason,
            "source_locator": self.source_locator,
            "http_status": self.http_status,
            "dom_body_found": self.dom_body_found,
            "dom_body_matches": self.dom_body_matches,
            "expandable": self.expandable,
            "truncated": self.truncated,
            "comments_expanded": False,
            "evidence_generated": False,
        }


def parse_detail(payload: object, expected: SourceIdentity) -> LiveDetail:
    """Read only the expected note; never import comments, video or credential fields."""
    data = _mapping(payload)
    note = _mapping(_unwrapped(data.get("note"))) if data is not None else None
    if data is None or note is None or note.get("noteId") != expected.note_id:
        raise LiveParseError()
    body = _text(note.get("desc"))
    title = _text(note.get("title"))
    summary = _text(note.get("summary"))
    status_value = data.get("http_status")
    http_status = status_value if type(status_value) is int and 100 <= status_value <= 599 else None
    dom_body_found = data.get("dom_body_found") is True
    dom_body_matches = body is not None and dom_body_found and data.get("dom_body") == body
    expandable = _bool(data.get("expandable"))
    truncated = _bool(data.get("truncated"))
    verified = (
        dom_body_matches and expandable is False and truncated is False
        and http_status is not None and 200 <= http_status < 300
    )
    raw = RawDetail(
        expected, title or "", body, summary, text_scope_verified=verified,
        truncated=truncated is True, http_status=http_status if http_status is not None else 0,
    )
    images = note.get("imageList")
    image_count = sum(_mapping(item) is not None for item in images) if isinstance(images, list) else 0
    user = _mapping(note.get("user")) or {}
    author = _text(user.get("nickname")) or _text(user.get("nickName"))
    note_type = _note_type(note.get("type"))
    statuses: dict[str, FieldStatus] = {
        "note_id": "OBSERVED",
        "source_id": "DERIVED",
        "title": _present(title),
        "body": _present(body),
        "summary": _present(summary),
        "note_type": "OBSERVED" if note_type != "unknown" else "NOT_AVAILABLE",
        "author_display": _present(author),
        "publish_time": _present(_time(note.get("time"))),
        "ip_location": _present(_text(note.get("ipLocation"))),
        "interaction_metadata": "OBSERVED" if _interaction_fields(note.get("interactInfo"))
        else "NOT_AVAILABLE",
        "images": "OBSERVED" if image_count else "NOT_AVAILABLE",
        "destination": "NOT_AVAILABLE",
        "travel_time": "NOT_AVAILABLE",
    }
    source_locator = None
    if body is not None:
        # Half-open Unicode character range, tied to the exact body version.
        body_hash = sha256(body.encode("utf-8", errors="surrogatepass")).hexdigest()
        source_locator = f"note-body:v1:{body_hash}:chars:0-{len(body)}"
    return LiveDetail(
        raw, classify_completeness(raw), source_locator, note_type, statuses, image_count,
        http_status, dom_body_found, dom_body_matches, expandable, truncated,
    )
