from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .settings import PROJECT_ROOT, Settings
from .preview.api import PreviewConfig, install


def create_app(settings: Settings | None = None, *, preview: PreviewConfig | None = None) -> FastAPI:
    settings = settings or Settings.load()
    app = FastAPI(title="TravelAgent 本机预览", docs_url=None, redoc_url=None, openapi_url=None)
    if preview is not None:
        install(app, preview, settings.preferred_port)

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        allowed = {"127.0.0.1", f"127.0.0.1:{settings.preferred_port}"}
        origin = request.headers.get("origin")
        if request.headers.get("host") not in allowed or (origin and origin != f"http://127.0.0.1:{settings.preferred_port}"):
            return JSONResponse({"error": {"code": "LOCAL_ONLY", "message": "仅允许本机同源访问", "request_id": "local-boundary", "retryable": False, "details": {}}}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    dist = PROJECT_ROOT / "apps/web/dist"

    @app.get("/")
    def index():
        if not (dist / "index.html").is_file():
            return JSONResponse({"message": "请先在 apps/web 执行 pnpm build"}, status_code=503)
        return FileResponse(dist / "index.html")

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    return app
