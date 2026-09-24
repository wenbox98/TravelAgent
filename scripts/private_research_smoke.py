"""Explicit T06.1 live entry; profile and private research SQLite remain separate."""

from _bootstrap import enter

enter()

from travel_agent.research.private_smoke import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
