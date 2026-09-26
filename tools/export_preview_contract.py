"""Export only P01 DTOs/routes into existing contracts; no runtime database access."""
import json
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from travel_agent.preview.models import PreviewCreate, PreviewMutation, PreviewView, PreviewIndex, JobCreate, JobAction, JobView, WorkbenchIndex, ReplayIndex, ReplayAdopt  # noqa: E402
from travel_agent.planning.models import MapAction, MapView  # noqa: E402


def definitions():
    result = {}
    for model in (PreviewCreate, PreviewMutation, PreviewView, PreviewIndex, JobCreate, JobAction, JobView, WorkbenchIndex, ReplayIndex, ReplayAdopt, MapAction, MapView):
        schema = model.model_json_schema()
        result.update(schema.pop("$defs", {}))
        result[model.__name__] = schema
    return result


def main():
    path = ROOT / "contracts/domain.schema.json"
    domain = json.loads(path.read_text(encoding="utf-8"))
    domain["$defs"].update(definitions())
    from travel_agent.research.context_review import REVIEW_SCHEMA, REVIEW_SCHEMA_V1
    from travel_agent.research.grounding import CONTEXT_REASONS, REASONS
    domain['$defs']['ModelContextReviewResponse'] = REVIEW_SCHEMA
    domain['$defs']['ModelContextReviewResponseV1'] = REVIEW_SCHEMA_V1
    domain['$defs']['GroundingCandidateCheck']['properties']['context_reason']['enum'] = sorted(CONTEXT_REASONS | REASONS)
    path.write_text(json.dumps(domain, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path = ROOT / "contracts/openapi.yaml"
    api = yaml.safe_load(path.read_text(encoding="utf-8"))
    routes = [
        ('/api/v1/preview/routes/{session_id}', 'get', 'readRoutePreview', None, 'MapView'),
        ('/api/v1/preview/routes', 'post', 'changeRoutePreview', 'MapAction', 'MapView'),
        ("/api/v1/preview/reviews", "get", "readReviewExplanations", None, "ReplayIndex"),
        ("/api/v1/preview/review-update", "post", "adoptLocalRevalidation", "ReplayAdopt", "PreviewView"),
        ("/api/v1/preview", "get", "getCachedPreview", None, "PreviewIndex"),
        ("/api/v1/preview/sessions", "post", "createCachedPreview", "PreviewCreate", "PreviewView"),
        ("/api/v1/preview/sessions/{session_id}", "get", "readCachedPreview", None, "PreviewView"),
        ("/api/v1/preview/sessions/{session_id}", "post", "changeCachedPreview", "PreviewMutation", "PreviewView"),
        ('/api/v1/preview/workbench', 'get', 'readWorkbench', None, 'WorkbenchIndex'),
        ('/api/v1/preview/jobs', 'post', 'createBoundedResearch', 'JobCreate', 'JobView'),
        ('/api/v1/preview/jobs/{job_id}', 'get', 'readBoundedResearch', None, 'JobView'),
        ('/api/v1/preview/jobs/{job_id}', 'post', 'changeBoundedResearch', 'JobAction', 'JobView'),
    ]
    for route, verb, operation, body, response in routes:
        headers = [{"name": name, "in": "header", "required": True, "schema": {"type": "string"}}
                   for name in ("X-CSRF-Token", "Idempotency-Key")] if body else []
        if "{session_id}" in route:
            headers.append({"name": "session_id", "in": "path", "required": True, "schema": {"type": "string"}})
        if '{job_id}' in route:
            headers.append({'name':'job_id','in':'path','required':True,'schema':{'type':'string'}})
        value = {"operationId": operation, "summary": "P01 已实现：同源鉴权的缓存选择预览，零业务外部请求", "parameters": headers,
                 "security": [{"PreviewSession": []}], "responses": {"200": {"description": "本机已审核缓存和用户选择", "content": {"application/json": {"schema": {"$ref": f"./domain.schema.json#/$defs/{response}"}}}},
                 "default": {"description": "安全错误；不返回原始异常或正文", "content": {"application/json": {"schema": {"$ref": "./domain.schema.json#/$defs/ErrorResponse"}}}}}}
        if body:
            value["requestBody"] = {"required": True, "content": {"application/json": {"schema": {"$ref": f"./domain.schema.json#/$defs/{body}"}}}}
        if 'BoundedResearch' in operation or operation=='readWorkbench':
            value['summary']='P02 本机有限研究；GET 零外部调用，POST 受许可、门槛、额度和同源检查约束'
        if operation in {'readReviewExplanations','adoptLocalRevalidation'}:
            value['summary']='P02.1 本地审核说明/显式采用；不执行回放、不派发任何外部调用'
            value['security']=[{'PreviewReplaySession':[]}]
        elif operation in {'getCachedPreview','createCachedPreview','readCachedPreview','changeCachedPreview'}:
            value['security']=[{'PreviewSession':[]},{'PreviewReplaySession':[]}]
        if operation in {'readRoutePreview','changeRoutePreview'}:
            value['summary']='P03 高德分段参考；GET/保存条件零外部请求，地图动作需显式确认并先占耐久额度；结果只在内存'
            value['security']=[{'PreviewMapSession':[]}]
        if operation=='changeBoundedResearch':
            value['responses']['200']['content']['application/json']['schema']={'oneOf':[
                {'$ref':'./domain.schema.json#/$defs/JobView'},{'$ref':'./domain.schema.json#/$defs/PreviewView'}]}
        api["paths"].setdefault(route, {})[verb] = value
    api["components"]["securitySchemes"]["PreviewSession"] = {"type": "apiKey", "in": "cookie", "name": "ta_preview", "description": "P01 loopback-only HttpOnly SameSite=Strict session; bootstrap ticket is one-use and expires in 5 minutes."}
    api['components']['securitySchemes']['PreviewMapSession'] = {'type':'apiKey','in':'cookie','name':'ta_preview_8768','description':'P03 isolated loopback session; ta_preview_<configured port>, default 8768.'}
    for route in ['/api/v1/preview','/api/v1/preview/sessions','/api/v1/preview/sessions/{session_id}']:
        for value in api['paths'][route].values():
            if 'security' in value and {'PreviewMapSession':[]} not in value['security']:
                value['security'].append({'PreviewMapSession':[]})
    api['components']['securitySchemes']['PreviewReplaySession'] = {'type':'apiKey','in':'cookie','name':'ta_preview_8767',
        'description':'P02.1 isolated HttpOnly SameSite=Strict cookie: ta_preview_<configured port>; 8767 by default. Cookies do not isolate by port, so its name must differ from P01/P02.'}
    marker = " P01 /api/v1/preview routes are implemented; other business routes remain design contracts. SQLite v11 adds independent preview choices/receipts."
    if marker not in api["info"]["description"]:
        api["info"]["description"] += marker
    path.write_text(yaml.safe_dump(api, allow_unicode=True, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    main()
