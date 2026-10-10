"""Settle interrupted dispatches without replay, refunds or material mutation."""

from typing import Any


def interrupt_grant(db: Any, grant_id: str, reason: str) -> None:
    """Caller owns the transaction; completed extraction/review rows stay intact."""
    stamp = db.stamp()
    db.connection.execute(
        "UPDATE research_continuations SET finished_at=coalesce(finished_at,?) WHERE continuation_id=?",
        (stamp, grant_id),
    )
    db.connection.execute(
        "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1,finished_at=coalesce(finished_at,?),"
        "summary_json=json_set(coalesce(summary_json,'{}'),'$.reason',?) "
        "WHERE continuation_id=? AND (status IN ('QUEUED','RUNNING','WAITING_LOGIN') "
        "OR (status='CANCELED' AND ?='SERVER_STOPPED' AND json_extract(summary_json,'$.reason') IS NULL))",
        (stamp, reason, grant_id, reason),
    )
    for table, column in (("extraction_attempts", "batch_id"), ("context_review_runs", "continuation_id")):
        db.connection.execute(
            f"UPDATE {table} SET status='INTERRUPTED',finished_at=coalesce(finished_at,?) "
            f"WHERE {column}=? AND status IN ('PENDING','RUNNING')",
            (stamp, grant_id),
        )
