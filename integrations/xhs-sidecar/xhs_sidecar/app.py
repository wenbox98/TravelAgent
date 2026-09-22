from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from secrets import compare_digest
from typing import Literal, Self

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPBearer
from pydantic import Field, SecretStr, model_validator
from starlette.responses import Response

from .browser import SessionClosed
from .models import (
    BrowserState,
    ContractModel,
    DetailRequest,
    DetailResult,
    ErrorResponse,
    Health,
    LoginState,
    NetworkSnapshot,
    SearchRequest,
    SearchResult,
)
from .service import BackendContractError, InvalidHandle, SidecarService


class SidecarConfig(ContractModel):
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=18061, ge=1024, le=65535)
    secret: SecretStr = Field(repr=False, exclude=True)

    @model_validator(mode="after")
    def nonempty_auth(self) -> Self:
        if len(self.secret.get_secret_value()) < 32:
            raise ValueError("sidecar凭证必须至少32字符")
        return self


def error_response(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": "本地只读服务请求未完成"}}, status_code=status
    )


def create_app(config: SidecarConfig, service: SidecarService | None = None) -> FastAPI:
    owned = service or SidecarService()
    owned.audit.redactor.register(config.secret)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            owned.close()

    app = FastAPI(
        title="TravelAgent XHS Readonly Sidecar (offline)",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        redirect_slashes=False,
        dependencies=[Depends(HTTPBearer(auto_error=False, scheme_name="SidecarBearer"))],
        responses={
            code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 405, 409, 422, 500, 502)
        },
    )
    app.state.service = owned

    @app.middleware("http")
    async def boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        authority = f"{config.host}:{config.port}"
        if request.headers.get("host") not in {config.host, authority} or request.headers.get(
            "origin"
        ) not in {None, f"http://{authority}"}:
            owned.audit.emit("request_rejected", outcome="forbidden")
            return error_response(403, "LOCAL_ONLY")
        methods = route_methods.get(request.scope["path"])
        if methods is None:
            return error_response(404, "NOT_FOUND")
        if request.method not in methods:
            return error_response(405, "METHOD_NOT_ALLOWED")
        credential = request.headers.get("authorization", "")
        expected = "Bearer " + config.secret.get_secret_value()
        if not compare_digest(credential.encode(), expected.encode()):
            owned.audit.emit("request_rejected", outcome="unauthorized")
            return error_response(401, "UNAUTHORIZED")
        if request.url.query:
            owned.audit.emit("request_rejected", outcome="invalid")
            return error_response(400, "QUERY_NOT_ALLOWED")
        try:
            response = await call_next(request)
        except Exception:
            # Never stringify exceptions, request bodies, URLs, or raw framework tracebacks.
            owned.audit.emit("request_failed", outcome="internal_error", status_code=500)
            response = error_response(500, "INTERNAL_ERROR")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        owned.audit.emit("request_rejected", outcome="invalid", status_code=422)
        return error_response(422, "INVALID_REQUEST")

    @app.exception_handler(InvalidHandle)
    async def invalid_handle(request: Request, exc: InvalidHandle) -> JSONResponse:
        return error_response(404, "INVALID_HANDLE")

    @app.exception_handler(SessionClosed)
    async def closed_session(request: Request, exc: SessionClosed) -> JSONResponse:
        return error_response(409, "SESSION_CLOSED")

    @app.exception_handler(BackendContractError)
    async def backend_error(request: Request, exc: BackendContractError) -> JSONResponse:
        owned.audit.emit("request_failed", outcome="invalid", status_code=502)
        return error_response(502, "BACKEND_CONTRACT_ERROR")

    @app.get("/health", response_model=Health)
    def health() -> Health:
        return Health()

    @app.get("/v1/browser/session", response_model=BrowserState)
    def browser_state() -> BrowserState:
        return owned.browser_state()

    @app.post("/v1/browser/session", response_model=BrowserState)
    def start_browser() -> BrowserState:
        return owned.start()

    @app.delete("/v1/browser/session", response_model=BrowserState)
    def close_browser() -> BrowserState:
        return owned.close()

    @app.get("/v1/login/status", response_model=LoginState)
    def login_state() -> LoginState:
        return LoginState()

    @app.post("/v1/feeds/search", response_model=SearchResult)
    def search(request: SearchRequest) -> SearchResult:
        return owned.search(request)

    @app.post("/v1/feeds/detail", response_model=DetailResult)
    def detail(request: DetailRequest) -> DetailResult:
        return owned.detail(request)

    @app.get("/v1/metrics", response_model=NetworkSnapshot)
    def metrics() -> NetworkSnapshot:
        return owned.observer.snapshot()

    route_methods: dict[str, set[str]] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            route_methods.setdefault(route.path, set()).update(route.methods or set())
    return app
