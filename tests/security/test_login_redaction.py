"""Capture all Python logs from synthetic success and failure paths; never launch a browser."""

import logging
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from xhs_sidecar.app import SidecarConfig, create_app
from xhs_sidecar.browser import AccountIdentity, BrowserManager, LoginObservation
from xhs_sidecar.login import LoginLifecycle
from xhs_sidecar.profile import ProfileStore
from xhs_sidecar.redaction import SafeAuditLog, SensitiveDataRedactor
from xhs_sidecar.service import SidecarService

ROOT = Path(__file__).resolve().parents[2]
SENTINELS = (
    "SECRET_COOKIE_T03",
    "SECRET_XSEC_T03",
    "SECRET_SESSION_T03",
    "SECRET_AUTHORIZATION_T03",
    "SECRET_QR_CONTENT_T03",
    "SECRET_ACCOUNT_ID_T03",
)


def assert_no_secrets(caplog, response_text=""):
    # Record arguments and exception metadata must already be safe, not merely the formatter.
    captured = caplog.text + "\n".join(repr(vars(record)) for record in caplog.records)
    assert caplog.records, "必须实际捕获日志，不能凭空判定敏感值未泄漏"
    for sentinel in SENTINELS:
        assert captured.count(sentinel) == 0
        assert response_text.count(sentinel) == 0


def test_T03_16_sensitive_fields_and_raw_exception_are_redacted_before_logging(caplog):
    caplog.set_level(logging.INFO)
    redactor = SensitiveDataRedactor()
    fields = dict(
        zip(
            [
                "cookie",
                "xsec_token",
                "session_data",
                "authorization",
                "qr_content",
                "account_stable_id",
            ],
            SENTINELS,
            strict=True,
        )
    )
    redacted = redactor.redact(fields)
    for sentinel in SENTINELS:
        assert sentinel not in str(redacted)
        redactor.register(SecretStr(sentinel))
    assert all(sentinel not in str(redactor.redact(" ".join(SENTINELS))) for sentinel in SENTINELS)
    audit = SafeAuditLog(redactor)
    audit.emit(
        "request_failed",
        operation="login_status",
        outcome="internal_error",
        payload=fields,
        exception=RuntimeError(" ".join(SENTINELS)),
        trace=" ".join(SENTINELS),
    )
    assert_no_secrets(caplog)


@pytest.mark.parametrize("phase", ["start", "navigation", "observe", "close", "clear", "success"])
def test_T03_16_login_failures_and_identity_do_not_leak_in_any_log(
    tmp_path, monkeypatch, caplog, phase
):
    caplog.set_level(logging.WARNING, logger="httpx")
    caplog.set_level(logging.INFO)

    def fail_at(stage):
        if phase == stage:
            raise RuntimeError(" ".join(SENTINELS))

    class PrivateResource:
        def open_login(self):
            fail_at("navigation")

        def observe_login(self):
            fail_at("observe")
            return LoginObservation(
                "AUTHENTICATED", AccountIdentity(stable_id=SecretStr(SENTINELS[-1]))
            )

        def close(self):
            fail_at("close")

    class PrivateBackend:
        kind = "fake"

        def start(self, options):
            fail_at("start")
            return PrivateResource()

    profile = ProfileStore(project_root=ROOT, root=tmp_path / "owned-xhs")
    browser = BrowserManager(PrivateBackend())
    lifecycle = LoginLifecycle(browser, profile, poll_interval=0.005, timeout=2)
    service = SidecarService(browser=browser)
    secret = "LOCAL_BEARER_" + SENTINELS[3] + "_SYNTHETIC_ONLY"
    app = create_app(SidecarConfig(secret=SecretStr(secret)), service=service, login=lifecycle)
    if phase == "clear":
        monkeypatch.setattr(profile, "clear_profile", lambda: fail_at("clear"))
    captured_responses = []
    with TestClient(
        app,
        base_url="http://127.0.0.1:18061",
        headers={"Authorization": "Bearer " + secret},
    ) as client:
        captured_responses.append(client.post("/v1/login/connect").text)
        deadline = monotonic() + 3
        settled = {"ERROR", "AUTHENTICATED"}
        pulse = Event()
        while monotonic() < deadline and lifecycle.status().status not in settled:
            pulse.wait(0.002)
        assert lifecycle.status().status in settled
        captured_responses.append(client.get("/v1/login/status").text)
        if phase in {"close", "clear"}:
            client.post("/v1/login/disconnect")
            assert lifecycle.status().status == "ERROR"
        captured_responses.append(lifecycle.status().model_dump_json())
    assert_no_secrets(caplog, "\n".join(captured_responses))
