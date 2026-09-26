"""Only explicit same-origin POST creates work. Polling is a local DB read."""

from typing import Any
from fastapi import FastAPI, Request
from travel_agent.persistence.database import Database
from .api import PreviewConfig
from .jobs import JobService
from .models import WorkbenchIndex, JobCreate, JobView, JobAction, PreviewView


def install_workbench(app: FastAPI, config: PreviewConfig) -> None:
    def service(db: Database) -> JobService:
        assert config.continuation is not None
        return JobService(db, config.account_scope, config.mode, config.continuation)

    @app.get("/api/v1/preview/workbench", response_model=WorkbenchIndex)
    def index() -> dict[str, Any]:
        with Database(config.database) as db:
            return service(db).index(config.live_ready)

    @app.post("/api/v1/preview/jobs", response_model=JobView)
    def create(body: JobCreate, request: Request) -> dict[str, Any]:
        with Database(config.database) as db:
            current = service(db)
            job = current.create(
                body.session_id,
                body.expected_revision,
                body.destination,
                request.headers.get("idempotency-key", ""),
                ready=config.live_ready,
            )
        if current.created:
            from .worker import launch_job

            launch_job(config.database, job["job_id"])
        return job

    @app.get("/api/v1/preview/jobs/{job_id}", response_model=JobView)
    def read(job_id: str) -> dict[str, Any]:
        with Database(config.database) as db:
            return service(db).get(job_id)

    @app.post("/api/v1/preview/jobs/{job_id}", response_model=JobView | PreviewView)
    def action(job_id: str, body: JobAction, request: Request) -> dict[str, Any]:
        with Database(config.database) as db:
            s = service(db)
            if body.action == "cancel":
                return s.cancel(job_id)
            return s.adopt(
                job_id, body.expected_revision, request.headers.get("idempotency-key", "")
            )
