from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid
from travel_agent.settings import PROJECT_ROOT


def statements(sql):
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            yield buffer
            buffer = ""
    if buffer.strip() and any(not line.lstrip().startswith("--") for line in buffer.splitlines() if line.strip()):
        raise ValueError("迁移 SQL 未闭合")


class Database:
    LATEST_VERSION = 6

    def __init__(self, path: Path, *, clock=None, target_version=LATEST_VERSION):
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        try:
            self.migrate(target_version)
        except BaseException:
            self.connection.close()
            raise

    @property
    def version(self):
        exists = self.connection.execute("SELECT 1 FROM sqlite_master WHERE name='schema_version'").fetchone()
        return self.connection.execute("SELECT coalesce(max(version),0) FROM schema_version").fetchone()[0] if exists else 0

    def stamp(self):
        return self.clock().isoformat()

    def migrate(self, target):
        with self.transaction():
            current = self.version
            if target > self.LATEST_VERSION or current > target:
                raise ValueError("不支持未知版本或数据库降级")
            if current == 0 and self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError("拒绝初始化非空未知数据库")
            for version in range(current + 1, target + 1):
                path = PROJECT_ROOT / {
                    1: "contracts/database.sql",
                    2: "contracts/migrations/002_poc.sql",
                    3: "contracts/migrations/003_research.sql",
                    4: "contracts/migrations/004_research_quality.sql",
                    5: "contracts/migrations/005_private_source_content.sql",
                    6: "contracts/migrations/006_extraction_recovery.sql",
                }[version]
                for statement in statements(path.read_text(encoding="utf-8")):
                    self.connection.execute(statement)
                if version == 1:
                    self.connection.execute("UPDATE schema_version SET applied_at=? WHERE version=1", (self.stamp(),))
                else:
                    invalid = self.connection.execute("SELECT 1 FROM sources WHERE completeness NOT IN ('FULL_TEXT','PARTIAL_TEXT','SUMMARY_ONLY','METADATA_ONLY')").fetchone()
                    if invalid:
                        raise ValueError("存在无法转换的正文完整度，迁移已回滚")
                    self.connection.execute("INSERT INTO schema_version VALUES(?,?)", (version, self.stamp()))
            if self.connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("数据库外键校验失败")

    @contextmanager
    def transaction(self):
        nested = self.connection.in_transaction
        name = "sp_" + uuid.uuid4().hex
        self.connection.execute(f"SAVEPOINT {name}" if nested else "BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.execute(f"ROLLBACK TO {name}" if nested else "ROLLBACK")
            if nested:
                self.connection.execute(f"RELEASE {name}")
            raise
        else:
            self.connection.execute(f"RELEASE {name}" if nested else "COMMIT")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()
