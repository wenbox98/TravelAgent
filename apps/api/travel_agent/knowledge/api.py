"""Same-origin local library. No external operation dispatches in this API."""

from typing import Any, Literal
from fastapi import FastAPI
from pydantic import Field
from travel_agent.preview.api import PreviewConfig, error
from travel_agent.preview.models import StrictModel
from travel_agent.planning.flow_models import KnowledgeBinding
from travel_agent.persistence.database import Database
from .store import Library, no_raw
from . import organize, cleanup, planning


class LibraryAction(StrictModel):
    action: Literal[
        "search",
        "options",
        "preview_organize",
        "organize",
        "preview_pattern",
        "save_pattern",
        "attach",
        "preview_cleanup",
        "cleanup",
        "delete",
        "withdraw",
        "rebuild",
        "retention",
    ]
    query: str = Field(default="", max_length=160)
    destination: str = Field(default="", max_length=80)
    kind: Literal["", "SOURCE_REFERENCE", "PLACE_LEAD", "PLAN_PATTERN"] = ""
    include_test: bool = False
    since: str = Field(default="", max_length=30)
    session_id: str = Field(default="", max_length=100)
    expected_revision: int = Field(default=0, ge=0)
    refs: list[KnowledgeBinding] = Field(default_factory=list, max_length=12)
    preview_hash: str = Field(default="", max_length=64)
    retention_policy: Literal["PERSISTENT", "READY_AFTER_ORGANIZED", "SESSION"] = "PERSISTENT"
    confirm: bool = False


class LibraryResponse(StrictModel):
    result: dict[str, Any]


def install_library(app: FastAPI, config: PreviewConfig) -> None:
    @app.post("/api/v1/preview/knowledge", response_model=LibraryResponse)
    def action(body: LibraryAction) -> Any:
        try:
            with Database(config.database) as db:
                lib = Library(db, config.account_scope)
                refs = [r.model_dump() for r in body.refs]
                a = body.action
                if a == "search":
                    with no_raw(db):
                        result = lib.search(
                            body.query, body.destination, body.kind, body.include_test, body.since
                        )
                elif a == "options":
                    result = dict(options=organize.options(db, config.account_scope))
                elif a in {"preview_organize", "preview_pattern"}:
                    result = organize.prepare(
                        db, config.account_scope, body.session_id, a == "preview_pattern"
                    )
                elif a in {"organize", "save_pattern"} and body.confirm:
                    result = organize.commit(
                        db,
                        config.account_scope,
                        body.session_id,
                        body.preview_hash,
                        a == "save_pattern",
                    )
                elif a == "attach":
                    result = planning.attach(
                        db,
                        config.account_scope,
                        body.session_id,
                        refs,
                        body.expected_revision,
                        body.include_test,
                    )
                elif a == "preview_cleanup":
                    result = cleanup.preview(db, config.account_scope, refs)
                elif a == "cleanup" and body.confirm:
                    result = cleanup.clear(db, config.account_scope, refs, body.preview_hash)
                elif a in {"delete", "withdraw"} and body.confirm:
                    result = lib.remove(refs, withdraw_sources=a == "withdraw")
                elif a == "retention" and body.confirm:
                    result = lib.retention(refs, body.retention_policy)
                elif a == "rebuild" and body.confirm:
                    lib.rebuild()
                    result = dict(rebuilt=True)
                else:
                    raise ValueError("INVALID_INPUT")
                return dict(result=result)
        except ValueError as exc:
            code = str(exc)
            return error(
                code
                if code.startswith("KNOWLEDGE_")
                or code in {"STALE_REVISION", "REUSE_REQUIRES_EMPTY_DRAFT"}
                else "INVALID_INPUT",
                409,
            )
