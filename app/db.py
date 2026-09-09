"""Thin SQLite wrapper. No ORM: this is a personal, single-user, local app
and the schema is small enough that raw SQL stays readable.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    niche TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS term_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_run_id INTEGER NOT NULL REFERENCES search_runs(id),
    term TEXT NOT NULL,
    source TEXT NOT NULL,
    sources TEXT NOT NULL,
    score REAL NOT NULL,
    growth_pct REAL,
    momentum_pct REAL,
    avg_interest REAL,
    competition_estimate INTEGER,
    competition_label TEXT,
    ad_library_url TEXT,
    series_json TEXT NOT NULL,
    top_advertisers_json TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_search_runs_niche ON search_runs(niche);
CREATE INDEX IF NOT EXISTS idx_term_signals_run ON term_signals(search_run_id);
CREATE INDEX IF NOT EXISTS idx_term_signals_term ON term_signals(term);
"""


def _connect() -> sqlite3.Connection:
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# Columns added to term_signals after its first release. CREATE TABLE IF
# NOT EXISTS (in SCHEMA above) only helps a brand-new database — an
# existing local data/dashboard.db from before a schema change needs
# these added explicitly, or every insert into a missing column breaks.
_TERM_SIGNALS_MIGRATIONS = {
    "sources": "ALTER TABLE term_signals ADD COLUMN sources TEXT NOT NULL DEFAULT ''",
    "top_advertisers_json": "ALTER TABLE term_signals ADD COLUMN top_advertisers_json TEXT NOT NULL DEFAULT '[]'",
}


def _migrate_term_signals(conn: sqlite3.Connection) -> None:
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(term_signals)")}
    for column, statement in _TERM_SIGNALS_MIGRATIONS.items():
        if column in existing_columns:
            continue
        conn.execute(statement)
        if column == "sources":
            # Backfill from the older single-source column so existing
            # rows still show something in the Sources column/CSV.
            conn.execute("UPDATE term_signals SET sources = source WHERE sources = ''")


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)
        _migrate_term_signals(conn)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_search_run(niche: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO search_runs (niche, created_at) VALUES (?, ?)",
            (niche, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def save_term_signal(search_run_id: int, signal: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO term_signals (
                search_run_id, term, source, sources, score, growth_pct,
                momentum_pct, avg_interest, competition_estimate,
                competition_label, ad_library_url, series_json,
                top_advertisers_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                search_run_id,
                signal["term"],
                signal["source"],
                ",".join(signal.get("sources", [signal["source"]])),
                signal["score"],
                signal.get("growth_pct"),
                signal.get("momentum_pct"),
                signal.get("avg_interest"),
                signal.get("competition_estimate"),
                signal.get("competition_label"),
                signal.get("ad_library_url"),
                json.dumps(signal.get("series", [])),
                json.dumps(signal.get("top_advertisers", [])),
            ),
        )


def get_search_run(run_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM search_runs WHERE id = ?", (run_id,)
        ).fetchone()


def get_term_signals(run_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM term_signals WHERE search_run_id = ? ORDER BY score DESC",
            (run_id,),
        ).fetchall()


def get_previous_run(niche: str, before_run_id: int) -> sqlite3.Row | None:
    """Most recent earlier run for the same niche, for week-over-week deltas."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT * FROM search_runs
            WHERE niche = ? AND id < ?
            ORDER BY id DESC LIMIT 1
            """,
            (niche, before_run_id),
        ).fetchone()


def get_runs_for_niche(niche: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM search_runs WHERE niche = ? ORDER BY id DESC",
            (niche,),
        ).fetchall()


def get_recent_runs(limit: int = 20) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM search_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
