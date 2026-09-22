import json
from pathlib import Path
import yaml
from travel_agent.domain.models import DomainModel

ROOT = Path(__file__).resolve().parents[2]


def test_openapi_references_and_security():
    api = yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "contracts/domain.schema.json").read_text(encoding="utf-8"))
    assert api["security"] == [{"LocalSession": []}]
    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                name = value["$ref"].removeprefix("./domain.schema.json#/$defs/")
                assert name in schema["$defs"]
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(api)
    for path in api["paths"].values():
        for method, operation in path.items():
            if method in {"post", "delete", "put", "patch"}:
                assert {"X-CSRF-Token", "Idempotency-Key"} <= {p["name"] for p in operation["parameters"] if p["required"]}


def test_error_envelope_separate_from_fetch_result():
    data = {"error": {"code": "LOCAL_ONLY", "message": "仅限本地", "request_id": "test", "retryable": False, "details": {}}}
    assert DomainModel.parse("ErrorResponse", data).to_dict() == data
    import pytest
    with pytest.raises(ValueError):
        DomainModel.parse("FetchResult", data)
