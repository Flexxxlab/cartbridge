"""Idempotent schema migration (no Alembic). Safe to run any number of times.

  python -m app.migrate                       migrate the database in DATABASE_URL
  python -m app.migrate --url sqlite:///x.db  migrate another database (e.g. a copy)

Take a backup first (see deploy/backup-sqlite.sh). The app also runs this on startup.
"""
import argparse

from sqlalchemy import Engine, create_engine, inspect, text

from .db import Base, engine as default_engine
from . import models  # noqa: F401  (registers all tables on Base)

# (table, column, DDL type/default) added after the table was first created.
COLUMNS = [
    ("platform_access", "limits", "VARCHAR(200)"),
    ("users", "plan", "VARCHAR(20) NOT NULL DEFAULT 'free'"),
    ("users", "session_version", "INTEGER NOT NULL DEFAULT 0"),
]


def migrate(engine: Engine = default_engine) -> list[str]:
    """Creates missing tables and adds missing columns. Returns what it did."""
    done: list[str] = []
    before = set(inspect(engine).get_table_names())
    Base.metadata.create_all(engine)  # only creates tables that don't exist yet
    done += [f"created table {t}" for t in sorted(set(inspect(engine).get_table_names()) - before)]
    insp = inspect(engine)
    for table, column, ddl in COLUMNS:
        if table not in insp.get_table_names():
            continue
        if column not in {c["name"] for c in insp.get_columns(table)}:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            done.append(f"added {table}.{column}")
    with engine.begin() as conn:  # every existing self-serve account starts on Free
        conn.execute(text("UPDATE users SET plan = 'free' WHERE plan IS NULL OR plan = ''"))
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.migrate")
    ap.add_argument("--url", help="database URL (default: DATABASE_URL)")
    a = ap.parse_args(argv)
    eng = create_engine(a.url) if a.url else default_engine
    done = migrate(eng)
    print("\n".join(done) if done else "Nothing to do: schema is up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
