"""Typed allow-list diagnostics; never serialize exception messages or response data."""

from dataclasses import asdict, dataclass, field
import re
from typing import Any

STAGES = frozenset({"CONFIG", "POLICY", "TRANSPORT", "HTTP", "ENVELOPE", "COMPLETION",
                    "CONTENT_JSON", "SCHEMA", "GROUNDING", "STORAGE", "INTERNAL", "COMPLETE"})
CATEGORIES = frozenset({"NOT_CONFIGURED", "POLICY_BLOCKED", "TIMEOUT", "TLS_ERROR", "NETWORK_ERROR",
    "BAD_REQUEST", "UNAUTHORIZED", "FORBIDDEN", "RATE_LIMITED", "SERVER_ERROR", "HTTP_OTHER",
    "INVALID_ENVELOPE", "OVERSIZED_RESPONSE", "MISSING_CONTENT", "EMPTY_CONTENT", "TRUNCATED",
    "REFUSED", "ABORTED", "UNEXPECTED_FINISH", "INVALID_JSON", "SCHEMA_INVALID",
    "UNGROUNDED", "NO_CLAIMS", "SOURCE_SAVE_FAILED", "UNEXPECTED_ERROR", "SUCCESS", "TOTAL_DEADLINE"})
TRANSPORT_PHASES = frozenset({"NOT_STARTED", "OPENING", "BODY_READ", "COMPLETE"})
FINISH_REASONS = frozenset({"stop", "length", "content_filter", "tool_calls",
                           "insufficient_system_resource", "aborted"})
VALIDATORS = frozenset({"type", "required", "additionalProperties", "enum", "const", "minLength",
    "maxLength", "minItems", "maxItems", "uniqueItems", "minimum", "maximum", "pattern",
    "format", "oneOf", "anyOf", "allOf", "not"})


def safe_model(value: object, secret: str = "") -> str | None:
    if (isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9._:/-]{0,100}", value)
        and not (secret and secret in value) and not re.search(r"(?i)secret|token|cookie|sk-", value)):
        return value
    return None


def safe_request_id(value: object, secret: str = "") -> str | None:
    if (isinstance(value, str) and not (secret and secret in value)
        and re.fullmatch(r"(?:[a-f0-9]{16,64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|"
                         r"chatcmpl-[A-Za-z0-9]{8,64})", value)):
        return value
    return None


def schema_issue(error: Any, schema: dict[str, Any]) -> dict[str, Any]:
    # Only trusted schema property names and numeric indexes, never instance keys/values.
    keys: set[str] = set()
    def visit(node: object) -> None:
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict):
                keys.update(props)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(schema)
    path = [item if type(item) is int and 0 <= item <= 10000 or isinstance(item, str)
            and item in keys else "UNKNOWN_FIELD" for item in list(error.absolute_path)[:12]]
    return {"path": path, "validator": error.validator if error.validator in VALIDATORS else "UNKNOWN"}


@dataclass
class Diagnostic:
    stage: str = "INTERNAL"
    category: str = "UNEXPECTED_ERROR"
    http_status: int | None = None
    request_id: str | None = None
    requested_model: str | None = None
    response_model: str | None = None
    elapsed_seconds: float | None = None
    response_bytes: int | None = None
    finish_reason: str | None = None
    content_present: bool | None = None
    content_chars: int | None = None
    http_attempts: int = 0
    retry_count: int = 0
    schema_errors: list[dict[str, Any]] = field(default_factory=list)
    generated_claims: int | None = None
    reviewed_claims: int | None = None
    rejected_claims: int | None = None
    accepted_claims: int | None = None
    transport_phase: str = "NOT_STARTED"
    timeout_seconds: float | None = None
    headers_elapsed_seconds: float | None = None
    body_complete_elapsed_seconds: float | None = None

    def safe_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["stage"] = self.stage if self.stage in STAGES else "INTERNAL"
        result["category"] = self.category if self.category in CATEGORIES else "UNEXPECTED_ERROR"
        result["requested_model"] = safe_model(self.requested_model)
        result["response_model"] = safe_model(self.response_model)
        result["request_id"] = safe_request_id(self.request_id)
        result["finish_reason"] = self.finish_reason if self.finish_reason in FINISH_REASONS else None
        result["transport_phase"] = self.transport_phase if self.transport_phase in TRANSPORT_PHASES else "NOT_STARTED"
        return result
