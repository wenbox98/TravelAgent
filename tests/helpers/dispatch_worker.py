"""Tests-only subprocess adapter boundary. Never imported by product commands."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/api"), str(ROOT / "tests/helpers")]


def install(database):
    from automatic_fakes import config
    import travel_agent.preview.worker as worker
    import travel_agent.planning.suggestions as suggestions

    worker.configured_provider = suggestions.configured_provider = config
    original = subprocess.Popen

    def launch(command, *args, **kwargs):
        if isinstance(command, list) and len(command) > 2 and Path(command[1]) == ROOT / "scripts/product_preview.py":
            command = [command[0], str(Path(__file__).resolve()), *command[2:]]
        return original(command, *args, **kwargs)

    subprocess.Popen = launch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind")
    parser.add_argument("--job", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    database = args.workspace / "preview.sqlite3"
    from automatic_fakes import Model, Reader, config
    from travel_agent.providers.llm import OpenAICompatibleProvider
    from travel_agent.persistence.database import Database
    from travel_agent.research.store import EvidenceStore
    from travel_agent.preview import worker
    from travel_agent.planning.automatic import run_task
    from travel_agent.planning.suggestions import run_worker
    from travel_agent.research.context_review import run_review

    install(database)
    blocked = []

    def audit(event, values):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            blocked.append(event)
            raise AssertionError("SYNTHETIC_WORKER_OUTBOUND_DENIED")
        if event == "import" and str(values[0]).startswith("xhs_sidecar"):
            raise AssertionError("SYNTHETIC_WORKER_LIVE_IMPORT_DENIED")

    sys.addaudithook(audit)
    model = Model()
    OpenAICompatibleProvider.structured = lambda self, *a, **kw: model.structured(*a, **kw)
    calls_file = args.workspace / "dispatch.jsonl"

    def record(kind, **extra):
        with calls_file.open("a", encoding="utf8") as f:
            f.write(json.dumps(dict(kind=kind, time=time.monotonic(), **extra), ensure_ascii=False) + "\n")

    @dataclass
    class Snapshot:
        requests: int = 0

    class AuthoredReader(Reader):
        def __init__(self, *a, **kw):
            super().__init__()
            record("READER_CONSTRUCTOR")
            if (args.workspace / "fail-startup").exists():
                class ProfileError(RuntimeError):
                    pass
                raise ProfileError("SECRET_SENTINEL")
            self.browser = SimpleNamespace(sessions_created=0)
            self.observer = SimpleNamespace(snapshot=lambda *a: Snapshot())
            self.profile = SimpleNamespace(exists=lambda: False)

        def connect(self):
            record("CONNECT")
            super().connect()

        def search(self, query):
            record("SEARCH", query=query)
            return super().search(query)

        def detail(self, candidate, number):
            record("DETAIL")
            return super().detail(candidate, number)

        def close(self):
            record("CLOSE")

    sys.modules["travel_agent.research.live"] = SimpleNamespace(LiveResearchReader=AuthoredReader)
    record(args.kind)
    try:
        if args.kind == "task-worker":
            # Real production launch/await path; no injected research/planning runner.
            run_task(database, args.job)
        elif args.kind == "job-worker":
            # Real constructor/startup path; no injected reader/provider/dispatch.
            worker.run_job(database, args.job, product=True)
        elif args.kind == "worker":
            run_worker(database, args.job)
        else:
            with Database(database) as db:
                (worker.extract_worker if args.kind == "extract-worker" else run_review)(EvidenceStore(db), config(), args.job)
    finally:
        (args.workspace / (args.kind + "-" + args.job + ".metrics.json")).write_text(json.dumps(dict(blocked=blocked)), encoding="utf8")


if __name__ == "__main__":
    main()
