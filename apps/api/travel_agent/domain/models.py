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


def _claim_assessments(bundle):
    claims = {claim["claim_id"]: claim for claim in bundle["claims"]}
    if len(claims) != len(bundle["claims"]):
        raise ValueError("证据标识重复")
    for claim_id, assessment in bundle["claim_metadata"].items():
        if claim_id not in claims:
            raise ValueError("质量记录引用未知证据")
        claim = claims[claim_id]
        level = assessment["confidence_level"]
        if claim["confidence"] != {"LOW": 0.25, "MEDIUM": 0.6, "HIGH": 0.8}[level]:
            raise ValueError("证据等级与兼容数值不一致")
        method = assessment["extraction_method"]
        if method == "MOCK" and not bundle["is_synthetic"]:
            raise ValueError("真实来源不能引用模拟抽取")
        if ((method == "LOCAL_EXTRACTIVE" or assessment["canonical_relation"] == "CONFLICT") and level != "LOW"
            or level == "HIGH" and (bundle["completeness"] != "FULL_TEXT" or assessment["truncation_risk"]
                                    or not assessment["applicable_conditions"])):
            raise ValueError("证据等级超过可核验范围")
        locators = assessment["block_locators"]
        if len(locators) != len(assessment["source_block_ids"]):
            raise ValueError("正文块引用与定位数量不一致")
        ranges = []
        versions = set()
        for locator in locators:
            version, span = locator.rsplit(":chars:", 1)
            start, end = map(int, span.split("-"))
            if start >= end or (":v2:" in version and version.split(":")[2] != assessment["body_origin"]):
                raise ValueError("正文块定位与来源不一致")
            versions.add(version)
            ranges.append((start, end))
        matched = re.fullmatch(r"(.+):chars:([0-9]+)-([0-9]+)", claim["locator"] or "")
        if not matched or versions != {matched[1]}:
            raise ValueError("证据未绑定同一正文版本")
        start, end = int(matched[2]), int(matched[3])
        if end - start != len(claim["text"]) or not any(low <= start < end <= high for low, high in ranges):
            raise ValueError("证据定位不在引用正文块内")
        association = assessment.get("route_association")
        if association:
            index = association["object_block_id"]
            if (assessment.get("context_review_status") not in {"WORK_REVIEWED", "MODEL_CONTEXT_REVIEWED", "LOCAL_REVALIDATION"}
                or association["source_id"] != bundle["source_id"]
                or index not in assessment["source_block_ids"]
                or association["object_quote"] not in assessment["applicable_conditions"]):
                raise ValueError("路线关联缺少同源审核锚点")
            anchor_prefix, anchor_span = association["object_locator"].rsplit(":chars:", 1)
            low, high = map(int, anchor_span.split("-"))
            block_span = locators[assessment["source_block_ids"].index(index)].rsplit(":chars:", 1)[1]
            block_low, block_high = map(int, block_span.split("-"))
            if (anchor_prefix != matched[1] or high - low != len(association["object_quote"])
                or not block_low <= low < high <= block_high):
                raise ValueError("路线对象定位不在引用块内")
        if assessment.get("context_review_status") == "MODEL_CONTEXT_REVIEWED" and not assessment.get("context_review_id"):
            raise ValueError("模型审核缺少独立审核记录")
        if assessment.get("context_review_status") == "LOCAL_REVALIDATION" and not (assessment.get("local_revalidation_id") and assessment.get("context_review_id")):
            raise ValueError("本地校验缺少原审核和版本记录")
        if assessment.get("reference_scope") and (assessment.get("context_review_status") not in {"WORK_REVIEWED", "MODEL_CONTEXT_REVIEWED", "LOCAL_REVALIDATION"}
            or not assessment["applicable_conditions"] or claim["topic"] in {"PRICE", "OPENING", "RESERVATION"}):
            raise ValueError("当次经历缺少审核条件或涉及动态规则")
        private = json.dumps(assessment, ensure_ascii=False)
        if re.search(r"(?i)https?://|xsec[_-]?token|access[_-]?token|authorization|cookie\s*[:=]|"
                     r"session\s*[:=]|bearer\s+|[?&]token=|SECRET_(?:COOKIE|XSEC|SESSION|AUTHORIZATION|QR)", private):
            raise ValueError("质量记录含敏感访问材料")


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
        if "claim_metadata" in value:
            _claim_assessments(value)
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
