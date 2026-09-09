"""Regression test for the schema migrations in app/db.py.

The schema has changed several times since the first release (adding
`sources` and `top_advertisers_json` to term_signals, then a whole new
`batches` table plus `search_runs.batch_id` for batch scans), and `CREATE
TABLE IF NOT EXISTS` alone does nothing for a database that already
exists on disk from before those changes — every insert into a missing
column would break. This simulates exactly that: a pre-existing DB with
the original schema, then verifies init_db() adds the missing columns
(backfilling `sources` from the old single `source` column) without
losing data.
"""
import sqlite3

from app import db


def _create_old_schema_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE search_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            niche TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE term_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_run_id INTEGER NOT NULL,
            term TEXT NOT NULL,
            source TEXT NOT NULL,
            score REAL NOT NULL,
            growth_pct REAL,
            momentum_pct REAL,
            avg_interest REAL,
            competition_estimate INTEGER,
            competition_label TEXT,
            ad_library_url TEXT,
            series_json TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO search_runs (niche, created_at) VALUES ('cocina', '2026-01-01')")
    conn.execute(
        "INSERT INTO term_signals (search_run_id, term, source, score, series_json) "
        "VALUES (1, 'cocina', 'google_trends', 50.0, '[]')"
    )
    conn.commit()
    conn.close()


def test_init_db_migrates_old_schema_without_losing_data(monkeypatch, tmp_path):
    db_path = tmp_path / "old.db"
    monkeypatch.setattr(db.settings, "db_path", str(db_path))
    _create_old_schema_db(db_path)

    db.init_db()

    rows = db.get_term_signals(1)
    assert len(rows) == 1
    row = rows[0]
    assert set(row.keys()) >= {"sources", "top_advertisers_json"}
    assert row["sources"] == "google_trends"  # backfilled from the old `source` column
    assert row["top_advertisers_json"] == "[]"
    assert row["term"] == "cocina"  # original data preserved

    # The old DB also predates batch scans entirely — no `batches` table,
    # no `batch_id` column on search_runs. Both should now exist, and the
    # pre-existing run should have a NULL batch_id (it was never batched).
    run = db.get_search_run(1)
    assert "batch_id" in run.keys()
    assert run["batch_id"] is None
    assert db.get_recent_batches() == []  # batches table exists but is empty


def test_init_db_is_idempotent_on_already_migrated_db(monkeypatch, tmp_path):
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(db.settings, "db_path", str(db_path))

    db.init_db()
    db.init_db()  # should not raise on a second call

    run_id = db.create_search_run("mascotas")
    db.save_term_signal(
        run_id,
        {"term": "mascotas", "source": "reddit", "sources": ["reddit"], "score": 10.0, "series": []},
    )
    assert db.get_term_signals(run_id)[0]["sources"] == "reddit"
