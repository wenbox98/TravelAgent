"""Start the same-origin preview from a private SQLite workspace copy. No live imports."""
import argparse
from pathlib import Path
import secrets
import sqlite3
import webbrowser
from _bootstrap import enter


def prepare_workspace(source: Path, workspace: Path) -> Path:
    from travel_agent.persistence.database import Database
    from travel_agent.settings import RuntimePaths
    paths = RuntimePaths(workspace)
    target = paths.child("preview.sqlite3")
    if not source.is_file() or source.resolve() == target:
        raise ValueError("必须指定存在的原缓存；工作副本不能覆盖原库")
    paths.root.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        # SQLite online backup includes committed WAL data; the source is read-only.
        with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
            with sqlite3.connect(target) as copied:
                original.backup(copied)
    # Before any version upgrade, retain a byte-independent SQLite backup.
    with sqlite3.connect(target) as cached:
        version = cached.execute("SELECT max(version) FROM schema_version").fetchone()[0]
        backup = paths.child(f"before-v{Database.LATEST_VERSION}-from-v{version}.sqlite3")
        if version < Database.LATEST_VERSION and not backup.exists():
            with sqlite3.connect(backup) as saved:
                cached.backup(saved)
    with Database(target):
        pass
    return target


def main() -> None:
    enter()
    import uvicorn
    from travel_agent.main import create_app
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.settings import Settings
    parser = argparse.ArgumentParser(description="缓存选择预览；不会启动小红书或调用模型")
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--account-scope", required=True)
    parser.add_argument("--mode", choices=["CACHED_PRIVATE_PREVIEW", "SYNTHETIC_DEMO"], default="CACHED_PRIVATE_PREVIEW")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="仅打开本机预览页")
    args = parser.parse_args()
    settings = Settings.load(preferred_port=args.port)
    database = prepare_workspace(args.source_database, args.workspace)
    key_file = database.parent / "preview-auth.key"
    if not key_file.exists():
        try:
            with key_file.open("xb") as file:
                file.write(secrets.token_bytes(32))
        except FileExistsError:
            pass
    key = key_file.read_bytes()
    if len(key) != 32:
        raise ValueError("本机会话密钥格式无效")
    config = PreviewConfig(database, args.account_scope, args.mode, key)
    url = f"http://127.0.0.1:{args.port}/bootstrap?ticket={config.ticket}"
    print("缓存驱动开发预览；当前行程可行性未核实。业务外部能力未接入。", flush=True)
    print("本机入口（5 分钟内一次有效，请勿分享）：" + url, flush=True)
    if args.open:
        # Open after the listener is ready; thread never connects to a business service.
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(settings, preview=config), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
