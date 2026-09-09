"""CSV export for a search run's prioritized term list."""
from __future__ import annotations

import csv
import io
import sqlite3


def term_signals_to_csv(niche: str, rows: list[sqlite3.Row]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "niche", "term", "source", "score", "growth_pct", "momentum_pct",
        "avg_interest", "competition_estimate", "competition_label",
        "ad_library_url",
    ])
    for row in rows:
        writer.writerow([
            niche,
            row["term"],
            row["source"],
            row["score"],
            row["growth_pct"],
            row["momentum_pct"],
            row["avg_interest"],
            row["competition_estimate"],
            row["competition_label"],
            row["ad_library_url"],
        ])
    return buffer.getvalue()
