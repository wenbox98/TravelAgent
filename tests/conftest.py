import json
import socket
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    local = threading.local()
    original_connect = socket.socket.connect
    original_pair = socket.socketpair
    def denied(*args, **kwargs):
        raise AssertionError("测试禁止网络访问")
    def connect(sock, address):
        if getattr(local, "socketpair", False) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        return denied()
    def pair(*args, **kwargs):
        # Windows asyncio creates a private loopback socket pair for wakeups.
        local.socketpair = True
        try:
            return original_pair(*args, **kwargs)
        finally:
            local.socketpair = False
    monkeypatch.setattr(socket, "socketpair", pair)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "sendto", denied)


@pytest.fixture
def clock():
    return lambda: datetime(2026, 9, 22, tzinfo=timezone.utc)


@pytest.fixture
def fixture_data():
    return lambda name: json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))
