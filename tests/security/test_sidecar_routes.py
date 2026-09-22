import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from xhs_sidecar.app import SidecarConfig, create_app

SECRET = "SYNTHETIC_SESSION_SECRET_SHOULD_NEVER_APPEAR"


@pytest.fixture
def client():
    app = create_app(SidecarConfig(secret=SecretStr(SECRET)))
    with TestClient(
        app, base_url="http://127.0.0.1:18061", headers={"Authorization": f"Bearer {SECRET}"}
    ) as value:
        yield value


@pytest.mark.parametrize(
    "path",
    [
        "/publish",
        "/comment",
        "/like",
        "/follow",
        "/private-message",
        "/api/v1/publish",
        "/api/v1/feeds/comment",
        "/api/v1/feeds/like",
        "/api/v1/follow",
        "/v1/publish",
        "/v1/feeds/comment",
        "/v1/feeds/like",
        "/v1/follow",
        "/v1/private-message",
    ],
)
def test_T02_04_write_routes_do_not_exist(client, path):
    assert client.post(path).status_code in {404, 405}
    assert client.post(path, headers={"Authorization": ""}).status_code in {404, 405}


@pytest.mark.parametrize("path", ["/mcp", "/mcp/tools/call", "/sse", "/tools/call"])
def test_T02_05_mcp_does_not_exist(client, path):
    response = client.post(path, json={"method": "tools/call", "params": {"name": "publish"}})
    assert response.status_code in {404, 405}


def test_all_routes_and_local_boundary(client):
    routes = {(method, route.path) for route in client.app.routes for method in route.methods}
    assert routes == {
        ("GET", "/health"),
        ("GET", "/v1/browser/session"),
        ("POST", "/v1/browser/session"),
        ("DELETE", "/v1/browser/session"),
        ("GET", "/v1/login/status"),
        ("POST", "/v1/feeds/search"),
        ("POST", "/v1/feeds/detail"),
        ("GET", "/v1/metrics"),
    }
    assert client.get("/health", headers={"Authorization": ""}).status_code == 401
    assert client.get("/health", headers={"Host": "evil.invalid"}).status_code == 403
    assert client.get("/health", headers={"Origin": "https://evil.invalid"}).status_code == 403
    assert client.get("/health").json()["mode"] == "offline"
    assert client.get("/v1/login/status").json()["remote_checked"] is False
    assert client.get("/v1/browser/session").json()["state"] == "CLOSED"


def test_T02_06_sentinels_absent_from_logs_and_errors(client, caplog):
    # The test's HTTP client is not the sidecar; do not log its request URLs.
    caplog.set_level(logging.WARNING, logger="httpx")
    caplog.set_level(logging.INFO)
    sentinel = "SECRET_XSEC_TOKEN_SHOULD_NEVER_APPEAR"
    response = client.post("/v1/feeds/search", json={"keyword": "合成", "xsec_token": sentinel})
    assert response.status_code == 422
    assert sentinel not in response.text
    assert client.get(f"/health?xsec_token={sentinel}").status_code == 400
    # Source logger rejects unknown structured fields rather than logging a raw request.
    client.app.state.service.audit.emit(
        "request_failed", xsec_token=sentinel, cookie=sentinel, exception=RuntimeError(sentinel)
    )
    records = [record.getMessage() for record in caplog.records if record.name == "xhs_sidecar"]
    assert records
    assert caplog.text.count(sentinel) == 0
    assert SECRET not in caplog.text
