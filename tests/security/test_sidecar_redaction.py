import logging

from fastapi.testclient import TestClient
from pydantic import SecretStr

from xhs_sidecar.app import SidecarConfig, create_app
from xhs_sidecar.backend import FakeXhsBackend
from xhs_sidecar.redaction import SafeAuditLog, SensitiveDataRedactor
from xhs_sidecar.service import SidecarService


def test_sensitive_structures_values_and_exceptions_are_removed_at_source(caplog):
    caplog.set_level(logging.INFO, logger="xhs_sidecar")
    sentinel = "SECRET_XSEC_TOKEN_SHOULD_NEVER_APPEAR"
    redactor = SensitiveDataRedactor()
    redactor.register(SecretStr(sentinel))
    payload = {
        "Cookie": sentinel,
        "nested": {"Authorization": sentinel, "xsecToken": sentinel},
        "qrcode": sentinel,
        "session_secret": sentinel,
        "arbitrary": f"value={sentinel}",
        "unknown_exception": RuntimeError(sentinel),
    }
    assert sentinel not in str(redactor.redact(payload))
    log = SafeAuditLog(redactor)
    log.emit(
        "search_finished",
        count=1,
        payload=payload,
        message=sentinel,
        outcome=sentinel,
        error=RuntimeError(sentinel),
    )
    assert caplog.text.count(sentinel) == 0
    assert "search_finished" in caplog.text


def test_backend_panic_does_not_leak_secrets_to_logs_or_response(caplog):
    sentinel = "SECRET_XSEC_TOKEN_SHOULD_NEVER_APPEAR"

    class BrokenBackend(FakeXhsBackend):
        def detail(self, session, locator):
            raise RuntimeError(f"https://synthetic.invalid/?xsec_token={sentinel}")

    caplog.set_level(logging.WARNING, logger="httpx")
    caplog.set_level(logging.INFO)
    secret = "SYNTHETIC_SESSION_SECRET_SHOULD_NEVER_APPEAR"
    backend = BrokenBackend()
    backend.token = SecretStr(sentinel)
    app = create_app(SidecarConfig(secret=SecretStr(secret)), SidecarService(backend=backend))
    with TestClient(
        app, base_url="http://127.0.0.1:18061", headers={"Authorization": "Bearer " + secret}
    ) as client:
        candidate = client.post("/v1/feeds/search", json={"keyword": "合成"}).json()["candidates"][
            0
        ]
        response = client.post("/v1/feeds/detail", json={"note_handle": candidate["note_handle"]})
        assert response.status_code == 500
        assert sentinel not in response.text
    assert caplog.text.count(sentinel) == 0
    assert caplog.text.count(secret) == 0
    assert "internal_error" in caplog.text
