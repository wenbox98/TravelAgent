"""Private usage decisions are separate from third-party rights assertions."""

from datetime import datetime, timezone
import re

from .models import SourcePolicy

PRIVATE_LOCAL_RESEARCH = "PRIVATE_LOCAL_RESEARCH"
RETENTIONS = {"7_DAYS", "30_DAYS", "PERSISTENT", "EPHEMERAL"}
SENSITIVE_RESEARCH_TEXT = re.compile(
    r"(?i)xsec[_-]?token|access[_-]?token|authorization|bearer\s+|"
    r"(?:cookie|session(?:[_-]?(?:id|secret))?|api[_-]?key|qr[_-]?(?:code|content))\s*[\"']?\s*[:=]|"
    r"[?&](?:token|sid)=|SECRET_(?:COOKIE|XSEC|SESSION|AUTHORIZATION|QR|API)|"
    r"data:image/|<\s*(?:script|img)\b"
)


def private_policy(account_scope: str, *, retention: str = "PERSISTENT",
                   now: datetime | None = None) -> SourcePolicy:
    return SourcePolicy({
        "policy_id": "private-local-research-" + account_scope, "version": 1,
        "basis": "UNKNOWN", "basis_note": "用户指定私人本机旅行研究用途；作者及平台授权未建立",
        "usage_mode": PRIVATE_LOCAL_RESEARCH, "local_account_scope": account_scope,
        "source_content_retention": retention,
        "allow_read": True, "allow_inference": True, "allow_external_model": True,
        "allow_persist_metadata": True, "allow_persist_derived": True,
        "allow_persist_raw": retention != "EPHEMERAL", "allow_embed": False,
        "allow_export": False, "reviewed_at": (now or datetime.now(timezone.utc)).isoformat(),
        "expires_at": None,
    })


def is_private(policy: SourcePolicy) -> bool:
    return bool(policy.get("usage_mode") == PRIVATE_LOCAL_RESEARCH)


def has_usage_basis(policy: SourcePolicy) -> bool:
    return bool(policy["basis"] != "UNKNOWN" or is_private(policy))


def scope_allowed(policy: SourcePolicy, account_scope: str) -> bool:
    return not is_private(policy) or policy.get("local_account_scope") == account_scope
