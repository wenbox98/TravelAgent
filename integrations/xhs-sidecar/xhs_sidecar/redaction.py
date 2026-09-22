"""Source logging accepts only bounded, non-content fields before creating a LogRecord."""

import logging
import re
from collections.abc import Mapping
from threading import RLock

from pydantic import SecretStr


class SensitiveDataRedactor:
    _sensitive = {
        "cookie",
        "cookies",
        "authorization",
        "token",
        "xsectoken",
        "qrcode",
        "qrcontent",
        "img",
        "sessionsecret",
        "secret",
        "password",
        "accesstoken",
    }

    def __init__(self) -> None:
        self._values: set[str] = set()
        self._lock = RLock()

    def register(self, secret: SecretStr) -> None:
        with self._lock:
            if secret.get_secret_value():
                self._values.add(secret.get_secret_value())

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def redact(self, value: object) -> object:
        with self._lock:
            if isinstance(value, SecretStr):
                return "[REDACTED]"
            if isinstance(value, Mapping):
                return {
                    str(key): (
                        "[REDACTED]"
                        if re.sub(r"[^a-z]", "", str(key).lower()) in self._sensitive
                        else self.redact(child)
                    )
                    for key, child in value.items()
                }
            if isinstance(value, (list, tuple)):
                return [self.redact(child) for child in value]
            if isinstance(value, str):
                for secret in sorted(self._values, key=len, reverse=True):
                    value = value.replace(secret, "[REDACTED]")
                value = re.sub(r"https?://[^\s]+", "[URL OMITTED]", value)
                return re.sub(r"data:image/[^\s]+", "[QR/IMAGE OMITTED]", value)
            if value is None or type(value) in (int, bool):
                return value
            return "[OBJECT OMITTED]"  # No str(exception), repr(request), or tracebacks.


class SafeAuditLog:
    _events = {
        "session_started",
        "session_closed",
        "search_finished",
        "detail_finished",
        "request_failed",
        "request_rejected",
    }
    _labels = {
        "operation": {"health", "session", "login_status", "search", "detail", "metrics"},
        "outcome": {"ok", "invalid", "internal_error", "unauthorized", "forbidden"},
    }

    def __init__(self, redactor: SensitiveDataRedactor | None = None) -> None:
        self.redactor = redactor or SensitiveDataRedactor()
        self.logger = logging.getLogger("xhs_sidecar")

    def emit(self, event: str, **fields: object) -> None:
        safe: dict[str, object] = {"event": event if event in self._events else "request_failed"}
        for key, value in fields.items():
            if key in self._labels and isinstance(value, str) and value in self._labels[key]:
                safe[key] = value
            elif key in {"count", "status_code"} and type(value) is int and 0 <= value <= 1_000_000:
                safe[key] = value
        self.logger.info("%s", self.redactor.redact(safe))
