import socket
import pytest
from travel_agent.providers.mock.xhs import MockXhsReadonlyAdapter


def test_network_guard_blocks_dns_and_connect():
    with pytest.raises(AssertionError):
        socket.getaddrinfo("example.invalid", 443)
    with socket.socket() as connection, pytest.raises(AssertionError):
        connection.connect(("127.0.0.1", 9999))


def test_mock_ignores_live_environment(monkeypatch):
    monkeypatch.setenv("XHS_LIVE_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "SYNTHETIC_SENTINEL_NOT_A_CREDENTIAL")
    adapter = MockXhsReadonlyAdapter()
    assert adapter.search("测试")["status"] == "OK"
    assert adapter.detail("opaque-synthetic-N01")["evidence"][0]["is_synthetic"] is True
