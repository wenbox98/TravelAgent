"""Process-role allowlist; no keys, URLs, map values or article text in metrics."""

import json
from pathlib import Path
import socket
import sys
from threading import RLock, local
from typing import Any
from urllib.parse import urlsplit

from travel_agent.providers.network_fence import in_amap_transport


def install(role: str, metrics_file: Path) -> None:
    metrics = dict(model_http=0, amap_http=0, external_dns=0, external_socket=0, blocked_external=0)
    lock, context = RLock(), local()
    resolved: dict[str, set[str]] = {}
    model_role = role in {"worker", "extract-worker", "review-worker"}
    amap_paths = {
        "/v5/place/text",
        "/v5/direction/transit/integrated",
        "/v5/direction/walking",
        "/v5/direction/driving",
    }

    def save() -> None:
        metrics_file.write_text(json.dumps({"role": role, **metrics}), encoding="utf-8")

    def denied() -> None:
        metrics["blocked_external"] += 1
        save()
        raise PermissionError("PRODUCT_EXTERNAL_DENIED")

    def guard(event: str, values: tuple[Any, ...]) -> None:
        with lock:
            if (
                event == "import"
                and role != "job-worker"
                and (
                    str(values[0]).startswith("xhs_sidecar")
                    or values[0] == "travel_agent.research.live"
                )
            ):
                denied()
            if event == "urllib.Request":
                url = urlsplit(values[0])
                host = url.netloc
                if (
                    model_role
                    and host == "api.deepseek.com"
                    and url.scheme == "https"
                    and url.path in {"/chat/completions", "/v1/chat/completions"}
                    and metrics["model_http"] == 0
                ):
                    metrics["model_http"] += 1
                elif (
                    role == "serve"
                    and in_amap_transport()
                    and host == "restapi.amap.com"
                    and url.scheme == "https"
                    and url.path in amap_paths
                ):
                    metrics["amap_http"] += 1
                else:
                    denied()
                context.host = host
                save()
            if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
                address = (
                    values[1]
                    if event == "socket.connect"
                    else values[0]
                    if event == "socket.getaddrinfo"
                    else values[-1]
                )
                host = address[0] if isinstance(address, tuple) else address
                if host in {"127.0.0.1", "::1", "localhost"}:
                    return
                allowed = getattr(context, "host", None)
                if (
                    event == "socket.sendto"
                    or not allowed
                    or (role == "serve" and not in_amap_transport())
                ):
                    denied()
                if event == "socket.getaddrinfo":
                    if host != allowed:
                        denied()
                    metrics["external_dns"] += 1
                else:
                    if (
                        not isinstance(address, tuple)
                        or address[1] != 443
                        or host not in resolved.get(str(allowed), set())
                    ):
                        denied()
                    metrics["external_socket"] += 1
                save()

    original = socket.getaddrinfo

    def resolve(*a: Any, **kw: Any) -> Any:
        result = original(*a, **kw)
        if a and a[0] in {"api.deepseek.com", "restapi.amap.com"}:
            with lock:
                resolved.setdefault(a[0], set()).update(str(r[4][0]) for r in result)
        return result

    socket.getaddrinfo = resolve
    save()
    sys.addaudithook(guard)
