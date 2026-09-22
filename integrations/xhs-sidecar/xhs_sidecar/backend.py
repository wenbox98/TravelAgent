"""Synthetic reader only. There is no live endpoint, HTTP client, or fallback."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import SecretStr

from .browser import BrowserSession
from .models import (
    AccessLocator,
    FilterStatus,
    RawDetail,
    SearchFilters,
    SearchRequest,
    SourceIdentity,
)


@dataclass(frozen=True, repr=False)
class RawCandidate:
    source: SourceIdentity
    title: str
    token: SecretStr


@dataclass(frozen=True, repr=False)
class RawSearch:
    candidates: tuple[RawCandidate, ...]
    applied: SearchFilters
    status: FilterStatus


class ReadonlyBackend(Protocol):
    def search(self, session: BrowserSession, request: SearchRequest) -> RawSearch: ...
    def detail(self, session: BrowserSession, locator: AccessLocator) -> RawDetail: ...


class FakeXhsBackend:
    def __init__(self, *, filter_status: FilterStatus = "APPLIED") -> None:
        self.filter_status = filter_status
        self.token = SecretStr("SYNTHETIC_XSEC_TOKEN_NOT_A_CREDENTIAL")
        self.source = SourceIdentity(note_id="synthetic-note-1")

    def search(self, session: BrowserSession, request: SearchRequest) -> RawSearch:
        session.require_open()
        status = self.filter_status if request.filters.specified() else "NOT_REQUESTED"
        applied = request.filters if status == "APPLIED" else SearchFilters()
        return RawSearch(
            (RawCandidate(self.source, "合成候选：不是真实攻略", self.token),), applied, status
        )

    def detail(self, session: BrowserSession, locator: AccessLocator) -> RawDetail:
        session.require_open()
        return RawDetail(
            source=locator.source,
            title="合成笔记",
            body="仅用于离线测试的合成文字，不含真实旅行建议。",
        )
