"""Topic-specific reuse semantics, separate from source permission and travel dates."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

Category = Literal["STABLE_EXPERIENCE", "TIME_SENSITIVE", "HIGHLY_DYNAMIC"]


@dataclass(frozen=True)
class Freshness:
    category: Category
    status: str
    expires_at: str | None
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_freshness(claim: dict[str, Any], bundle: Any, *, now: datetime | None = None) -> Freshness:
    """Defaults are application review intervals, never guarantees of truth."""
    now = now or datetime.now(timezone.utc)
    topic, text = claim["topic"], claim["text"]
    category: Category = "STABLE_EXPERIENCE"
    if topic in {"PRICE", "OPENING", "RESERVATION"}:
        category = "HIGHLY_DYNAMIC"
    elif topic in {"SEASON", "TRADEOFF", "TRANSPORT"} or any(
        word in text for word in ("今年", "今天", "当前", "国庆", "堵车", "排队")
    ):
        category = "TIME_SENSITIVE"
    start, end = claim.get("valid_from"), claim.get("valid_until")
    if start and datetime.fromisoformat(start) > now:
        return Freshness(category, "CURRENT_UNVERIFIED", end, "VALIDITY_NOT_STARTED")
    if end and datetime.fromisoformat(end) <= now:
        return Freshness(category, "STALE", end, "EXPLICIT_VALIDITY_EXPIRED")
    if category == "HIGHLY_DYNAMIC":
        # An author's stated validity window is not a current supplier verification.
        return Freshness(category, "CURRENT_UNVERIFIED", end, "CURRENT_REVALIDATION_REQUIRED")
    if end:
        return Freshness(category, "USABLE_REFERENCE", end, "EXPLICIT_VALIDITY_WINDOW")
    if category == "TIME_SENSITIVE":
        # Publication and retrieval never invent the author's travel date.
        if bundle["travel_occurred_at"] and datetime.fromisoformat(bundle["travel_occurred_at"]) > now:
            return Freshness(category, "CURRENT_UNVERIFIED", None, "FUTURE_TRAVEL_NOT_HISTORICAL")
        return Freshness(category, "HISTORICAL" if bundle["travel_occurred_at"] else "CURRENT_UNVERIFIED",
                         None, "HISTORICAL_EXPERIENCE" if bundle["travel_occurred_at"]
                         else "TRAVEL_DATE_AND_CURRENT_APPLICABILITY_UNKNOWN")
    # Static scenery/route experiences remain references; review after 180 days.
    # The interval applies to the observation, not a claim that travel happened then.
    retrieved = datetime.fromisoformat(bundle["fetched_at"])
    expires = retrieved + timedelta(days=180)
    if retrieved > now:
        return Freshness(category, "CURRENT_UNVERIFIED", expires.isoformat(), "FUTURE_RETRIEVAL_REJECTED")
    return Freshness(category, "STALE" if now >= expires else "USABLE_REFERENCE",
                     expires.isoformat(), "STABLE_REFERENCE_REVIEW_180_DAYS")
