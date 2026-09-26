"""Official v5 GET adapter. One attempt; projected ephemeral values, never raw responses."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import json
import math
import os
import re
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from pydantic import SecretStr
from .llm import _NoRedirect
from .network_fence import amap_transport

HOST = "https://restapi.amap.com"
PATHS = {
    "PLACE": "/v5/place/text",
    "DRIVING": "/v5/direction/driving",
    "TRANSIT": "/v5/direction/transit/integrated",
    "WALKING": "/v5/direction/walking",
}
SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


def coordinate(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"-?\d+(?:\.\d{1,6})?,-?\d+(?:\.\d{1,6})?", value
    ):
        raise ValueError("INVALID_COORDINATE")
    lng, lat = map(float, value.split(","))
    if not -180 <= lng <= 180 or not -90 <= lat <= 90:
        raise ValueError("INVALID_COORDINATE")
    return value


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except ValueError:
        return None


def route_parameters(
    start: dict[str, Any], end: dict[str, Any], mode: str, at: str | None
) -> dict[str, str]:
    if mode not in {"DRIVING", "TRANSIT", "WALKING"}:
        raise ValueError("INVALID_MODE")
    params = {
        "origin": coordinate(start.get("location")),
        "destination": coordinate(end.get("location")),
        "show_fields": "cost",
    }
    if mode == "TRANSIT":
        for name, poi in [("city1", start), ("city2", end)]:
            city = poi.get("citycode")
            if not isinstance(city, str) or not re.fullmatch(r"\d{3,4}", city):
                raise ValueError("CITYCODE_REQUIRED")
            params[name] = city
        params.update(strategy="0", AlternativeRoute="1")
        if at:
            dt = datetime.fromisoformat(at)
            if dt.tzinfo is None:
                raise ValueError("TIMEZONE_REQUIRED")
            dt = dt.astimezone(SHANGHAI)
            params.update(date=dt.strftime("%Y-%m-%d"), time=dt.strftime("%H-%M"), nightflag="1")
    elif mode == "DRIVING":
        params["strategy"] = "0"
    else:
        params["alternative_route"] = "1"
    return params


class AmapAdapter:
    def __init__(self, key: SecretStr):
        self._key = key
        self.configured = bool(key.get_secret_value().strip())

    def __repr__(self) -> str:
        return "AmapAdapter(server-only)"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AmapAdapter":
        return cls(SecretStr((os.environ if env is None else env).get("AMAP_WEB_SERVICE_KEY", "")))

    def _request(self, kind: str, params: dict[str, str]) -> dict[str, Any]:
        if not self.configured:
            return {"status": "NOT_CONFIGURED"}
        if kind not in PATHS or "key" in params:
            return {"status": "UPSTREAM_ERROR", "error_code": "INVALID_REQUEST"}
        # No environment proxy, redirects, retry, custom host or response/URL logging.
        opener = build_opener(
            ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=ssl.create_default_context())
        )
        url = (
            HOST
            + PATHS[kind]
            + "?"
            + urlencode(params | {"key": self._key.get_secret_value(), "output": "json"})
        )
        try:
            with amap_transport(), opener.open(Request(url, method="GET"), timeout=25) as response:
                if response.status != 200:
                    return {"status": "UPSTREAM_ERROR", "error_code": "HTTP_ERROR"}
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    return {"status": "UPSTREAM_ERROR", "error_code": "RESPONSE_TOO_LARGE"}
                result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError
            if result.get("status") != "1" or result.get("infocode") != "10000":
                code = result.get("infocode")
                auth = isinstance(code, str) and code.startswith("100") and code != "10000"
                return {
                    "status": "AUTH_OR_QUOTA_ERROR" if auth else "UPSTREAM_ERROR",
                    "error_code": "BUSINESS_ERROR",
                }
            return result
        except HTTPError as exc:
            return {
                "status": "AUTH_OR_QUOTA_ERROR"
                if exc.code in {401, 403, 429}
                else "UPSTREAM_ERROR",
                "error_code": "HTTP_ERROR",
            }
        except URLError, OSError, ValueError, TimeoutError:
            return {"status": "UPSTREAM_ERROR", "error_code": "NETWORK_OR_INVALID_RESPONSE"}

    def _text(self, value: Any) -> str:
        if (
            not isinstance(value, str)
            or self._key.get_secret_value()
            and self._key.get_secret_value() in value
        ):
            return ""
        return value[:200]

    def resolve_place(self, name: str, region: str) -> dict[str, Any]:
        if not 1 <= len(name) <= 80 or len(region) > 80:
            raise ValueError("INVALID_PLACE")
        params = {"keywords": name, "page_size": "3", "page_num": "1"}
        if region:
            params.update(region=region, city_limit="true")
        data = self._request("PLACE", params)
        if data.get("status") != "1":
            return data
        pois = data.get("pois")
        if number(data.get("count")) == 0 and not pois:
            return {"status": "NO_PLACE_RETURNED", "candidates": []}
        if (
            not isinstance(pois, list)
            or number(data.get("count")) is None
            or number(data.get("count")) == 0
        ):
            return {"status": "UPSTREAM_ERROR", "error_code": "INVALID_RESPONSE"}
        results = []
        for item in pois[:3]:
            if not isinstance(item, dict):
                continue
            try:
                location = coordinate(item.get("location"))
            except ValueError:
                continue
            row = {
                k: self._text(item.get(k))
                for k in [
                    "name",
                    "type",
                    "address",
                    "pname",
                    "cityname",
                    "adname",
                    "citycode",
                    "adcode",
                ]
            }
            if row["name"]:
                results.append(row | {"location": location, "coordinate_system": "GCJ02"})
        return {"status": "OK" if results else "PARTIAL", "candidates": results}

    def route(
        self, start: dict[str, Any], end: dict[str, Any], mode: str, at: str | None
    ) -> dict[str, Any]:
        params = route_parameters(start, end, mode, at)
        data = self._request(mode, params)
        if data.get("status") != "1":
            return data
        route = data.get("route")
        paths = (
            route.get("transits" if mode == "TRANSIT" else "paths")
            if isinstance(route, dict)
            else None
        )
        count = number(data.get("count"))
        if count == 0 and not paths:
            return {"status": "NO_ROUTE_RETURNED"}
        if (
            count is None
            or count == 0
            or not isinstance(paths, list)
            or not paths
            or not isinstance(paths[0], dict)
        ):
            return {"status": "UPSTREAM_ERROR", "error_code": "INVALID_RESPONSE"}
        # Exactly one returned alternative. Total already includes component durations/wait;
        # never add step times, taxi time, fares, or a driving fallback to transit.
        first = paths[0]
        cost = first.get("cost")
        duration = number(cost.get("duration")) if isinstance(cost, dict) else None
        distance = number(first.get("distance"))
        return {
            "status": "OK" if duration is not None and distance is not None else "PARTIAL",
            "duration_seconds": duration,
            "distance_meters": distance,
            "includes_waiting": mode == "TRANSIT",
            "date_applicability": "REQUESTED_TRANSIT_TIME_NOT_GUARANTEED"
            if mode == "TRANSIT" and at
            else "GENERAL_REFERENCE_ONLY",
        }
