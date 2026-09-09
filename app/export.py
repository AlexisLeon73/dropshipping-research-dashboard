"""CSV export for a search run's prioritized term list."""
from __future__ import annotations

import csv
import io
import json
import sqlite3


def _top_advertisers_summary(row: sqlite3.Row) -> str:
    advertisers = json.loads(row["top_advertisers_json"] or "[]")
    return "; ".join(f"{a['page_name']} ({a['ad_count']})" for a in advertisers)


def term_signals_to_csv(niche: str, rows: list[sqlite3.Row]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "niche", "term", "sources", "score", "growth_pct", "momentum_pct",
        "avg_interest", "competition_estimate", "competition_label",
        "top_advertisers", "ad_library_url",
    ])
    for row in rows:
        writer.writerow([
            niche,
            row["term"],
            row["sources"],
            row["score"],
            row["growth_pct"],
            row["momentum_pct"],
            row["avg_interest"],
            row["competition_estimate"],
            row["competition_label"],
            _top_advertisers_summary(row),
            row["ad_library_url"],
        ])
    return buffer.getvalue()


def batch_term_signals_to_csv(rows: list[dict]) -> str:
    """Like term_signals_to_csv, but for a batch scan's combined rows —
    each row already carries its own `niche` (since a batch mixes several)
    and a pre-parsed `top_advertisers` list rather than raw JSON.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "niche", "term", "sources", "score", "growth_pct", "momentum_pct",
        "avg_interest", "competition_estimate", "competition_label",
        "top_advertisers", "ad_library_url",
    ])
    for row in rows:
        summary = "; ".join(
            f"{a['page_name']} ({a['ad_count']})" for a in row.get("top_advertisers") or []
        )
        writer.writerow([
            row["niche"],
            row["term"],
            row["sources"],
            row["score"],
            row["growth_pct"],
            row["momentum_pct"],
            row["avg_interest"],
            row["competition_estimate"],
            row["competition_label"],
            summary,
            row["ad_library_url"],
        ])
    return buffer.getvalue()
