from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
import json
import re

from jsonschema import Draft202012Validator, FormatChecker
from travel_agent.settings import PROJECT_ROOT


@lru_cache
def validator(name):
    schema = json.loads((PROJECT_ROOT / "contracts/domain.schema.json").read_text(encoding="utf-8"))
    if name not in schema["$defs"]:
        raise ValueError("未知领域模型")
    return Draft202012Validator(schema | {"$ref": f"#/$defs/{name}"}, format_checker=FormatChecker())


def semantics(value):
    if isinstance(value, list):
        for item in value:
            semantics(item)
    if not isinstance(value, dict):
        return
    for lower, upper in (("min", "max"), ("min_fen", "max_fen"), ("start_at", "end_at"), ("valid_from", "valid_until")):
        if value.get(lower) is not None and value.get(upper) is not None:
            low, high = value[lower], value[upper]
            if lower in ("start_at", "valid_from"):
                from datetime import datetime
                low, high = datetime.fromisoformat(low), datetime.fromisoformat(high)
            if low > high:
                raise ValueError("范围起点大于终点")
    if value.get("status") == "UNKNOWN" and "unit_amount" in value:
        if any(value["unit_amount"][key] is not None for key in ("min_fen", "max_fen")):
            raise ValueError("未知价格不能成为已知金额")
    if "claims" in value:
        if any(claim["source_id"] != value["source_id"] for claim in value["claims"]):
            raise ValueError("证据来源不一致")
        if value["completeness"] == "METADATA_ONLY" and value["claims"]:
            raise ValueError("仅元信息不能生成正文结论")
        if value["is_synthetic"] != (value["source_type"] == "SYNTHETIC"):
            raise ValueError("合成来源标志不一致")
    if "network_measurement" in value and value["network_measurement"] == "UNAVAILABLE" and value.get("site_http_requests") is not None:
        raise ValueError("不可观测 HTTP 请求数必须为 null")
    if "spent" in value and "budget" in value:
        if any(value["spent"][key] > value["budget"][key] for key in value["budget"]):
            raise ValueError("已用预算超过上限")
    for key, child in value.items():
        if key in ("canonical_url", "locator") and isinstance(child, str):
            if re.search(r"(?i)(xsec_token|cookie|access_token|authorization|[?&]token=)", child):
                raise ValueError("来源定位含敏感访问材料")
        semantics(child)


@dataclass(frozen=True, init=False, repr=False)
class DomainModel(Mapping):
    _json: str
    schema_name = ""

    def __init__(self, data, *, schema_name=None):
        name = schema_name or self.schema_name
        try:
            payload = json.dumps(data, ensure_ascii=False, allow_nan=False)
            copied = json.loads(payload)
            errors = list(validator(name).iter_errors(copied))
        except (TypeError, OverflowError) as exc:
            raise ValueError("领域数据必须为严格 JSON") from exc
        if errors:
            # Do not leak failed input values or raw validator exceptions.
            raise ValueError(f"{name} 不符合领域契约")
        semantics(copied)
        object.__setattr__(self, "_json", payload)

    @classmethod
    def parse(cls, name, data):
        return cls(data, schema_name=name)

    def to_dict(self):
        return json.loads(self._json)

    def __getitem__(self, key):
        return self.to_dict()[key]

    def __iter__(self):
        return iter(self.to_dict())

    def __len__(self):
        return len(self.to_dict())

    def __repr__(self):
        return f"{type(self).__name__}(validated)"


class SourcePolicy(DomainModel):
    schema_name = "SourcePolicy"


class FetchResult(DomainModel):
    schema_name = "FetchResult"


class Trip(DomainModel):
    schema_name = "Trip"


class AuthSession(DomainModel):
    schema_name = "AuthSession"


class ResearchSession(DomainModel):
    schema_name = "ResearchSession"


class EvidenceBundle(DomainModel):
    schema_name = "EvidenceBundle"
