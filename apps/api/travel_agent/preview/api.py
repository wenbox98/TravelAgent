"""Loopback ticket/cookie/CSRF boundary for the local cache preview."""
from dataclasses import dataclass, field
import hmac
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError

from travel_agent.persistence.database import Database
from .models import Mode, PreviewCreate, PreviewMutation, PreviewView, PreviewIndex
from .service import PreviewService


@dataclass(frozen=True)
class PreviewConfig:
    database: Path
    account_scope: str
    mode: Mode
    auth_key: bytes = field(repr=False)
    ticket: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    continuation: str | None = None
    live_ready: bool = False
    local_replay: bool = False
    static_dir: Path | None = None


def error(code: str, status: int) -> JSONResponse:
    messages = {"AUTH_REQUIRED": "请使用本次启动窗口中的本机入口打开页面。", "CSRF_DENIED": "本机会话校验失败，请刷新页面。",
                "STALE_REVISION": "选择已更新，请刷新后查看最新状态。", "RESEARCH_CHANGED": "缓存依据已变化，请重新选择已有研究；原选择记录保留。",
                "INVALID_INPUT": "输入格式不正确，请检查选择。", "CACHE_UNAVAILABLE": "本地操作暂不可用；请先读取已保存状态，勿重复派发。",
                'LIVE_RESEARCH_UNAVAILABLE':'本轮许可、门槛或额度不允许新研究；已有资料仍可浏览。',
                'DESTINATION_REQUIRED':'请先确认要研究的目的区域。','DESTINATION_CONFLICT':'已有研究的目的区域与输入不一致，请保留原研究或新建本地需求。',
                'NEW_MATERIAL_UNAVAILABLE':'本任务没有可采用的新合格材料；原选择保留。','JOB_UNAVAILABLE':'当前范围没有此研究任务。'}
    return JSONResponse({"error": {"code": code, "message": messages.get(code, "本次操作未提交，请检查当前选择或重新打开研究。"),
                        "request_id": secrets.token_hex(8), "retryable": False, "details": {}}}, status_code=status)


def install(app: FastAPI, config: PreviewConfig, port: int) -> None:
    origin = f"http://127.0.0.1:{port}"
    # Cookies ignore ports. An isolated preview must not replace the P01/P02 cookie.
    cookie_name = f"ta_preview_{port}" if config.local_replay else "ta_preview"
    cookie = hmac.digest(config.auth_key, b"preview-session", "sha256").hex()
    csrf = hmac.digest(config.auth_key, b"preview-csrf", "sha256").hex()
    expires, used = time.monotonic() + 300, False

    @app.middleware("http")
    async def authentication(request: Request, call_next: Any) -> Any:
        if request.url.path.startswith("/api/v1/preview"):
            if not secrets.compare_digest(request.cookies.get(cookie_name, ""), cookie):
                return error("AUTH_REQUIRED", 401)
            if request.method not in {"GET", "HEAD"}:
                if (request.headers.get("origin") != origin or
                    not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf)):
                    return error("CSRF_DENIED", 403)
            if request.query_params:
                return error("INVALID_INPUT", 422)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/bootstrap")
    async def bootstrap(request: Request) -> Any:
        nonlocal used
        if (request.headers.get("host") != f"127.0.0.1:{port}" or used or time.monotonic() > expires
            or not secrets.compare_digest(request.query_params.get("ticket", ""), config.ticket)):
            return error("AUTH_REQUIRED", 401)
        used = True
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(cookie_name, cookie, httponly=True, samesite="strict", secure=False, path="/")
        return response

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def invalid(request: Request, exc: Exception) -> JSONResponse:
        return error("INVALID_INPUT", 422)

    @app.exception_handler(ValueError)
    async def rejected(request: Request, exc: ValueError) -> JSONResponse:
        codes = {"STALE_REVISION", "RESEARCH_CHANGED", "OPTION_UNAVAILABLE", "PREVIEW_REQUIRED", "IDEMPOTENCY_CONFLICT",
                 "RESEARCH_UNAVAILABLE", "SESSION_UNAVAILABLE", "INVALID_IDEMPOTENCY_KEY", "PREFERENCES_REQUIRED",
                 'LIVE_RESEARCH_UNAVAILABLE','DESTINATION_REQUIRED','DESTINATION_CONFLICT','NEW_MATERIAL_UNAVAILABLE','JOB_UNAVAILABLE'}
        return error(str(exc), 409) if str(exc) in codes else error("CACHE_UNAVAILABLE", 503)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request: Request, exc: Exception) -> JSONResponse:
        return error("CACHE_UNAVAILABLE", 503)

    if config.local_replay and (config.continuation or config.live_ready):
        raise ValueError('LOCAL_REPLAY_CANNOT_ENABLE_EXTERNAL_WORK')
    if config.local_replay:
        from .replay_api import install_replay
        install_replay(app, config)
    if config.continuation:
        from .workbench_api import install_workbench
        install_workbench(app,config)

    def present(view: dict[str, Any]) -> dict[str, Any]:
        if config.continuation and not view['options']:
            view['cache_message']='当前没有匹配的已审核本地资料；请确认目的区域后主动开始有限研究。'
        return view

    @app.get("/api/v1/preview", response_model=PreviewIndex)
    def index() -> dict[str, Any]:
        with Database(config.database) as db, db.transaction():
            service = PreviewService(db, config.account_scope, config.mode)
            latest=service.latest()
            return {"mode": config.mode, "csrf_token": csrf, "researches": service.researches(), "session": present(latest) if latest else None,
                    'workbench_available':config.continuation is not None, 'replay_available':config.local_replay}

    @app.post("/api/v1/preview/sessions", response_model=PreviewView)
    def create(body: PreviewCreate, request: Request) -> dict[str, Any]:
        with Database(config.database) as db, db.transaction():
            return present(PreviewService(db, config.account_scope, config.mode).open(body.research_id, body.text, request.headers.get("idempotency-key", "")))

    @app.get("/api/v1/preview/sessions/{session_id}", response_model=PreviewView)
    def read(session_id: str) -> dict[str, Any]:
        with Database(config.database) as db, db.transaction():
            return present(PreviewService(db, config.account_scope, config.mode).get(session_id))

    @app.post("/api/v1/preview/sessions/{session_id}", response_model=PreviewView)
    def mutate(session_id: str, body: PreviewMutation, request: Request) -> dict[str, Any]:
        with Database(config.database) as db, db.transaction():
            return present(PreviewService(db, config.account_scope, config.mode).mutate(session_id, body.model_dump(exclude_unset=True), request.headers.get("idempotency-key", "")))
