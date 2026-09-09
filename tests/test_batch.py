"""Batch scan tests: parsing the niche list, the db-level batch functions,
and the full HTTP pipeline (/batch-search -> /batch/{id} -> CSV export)
through the real FastAPI app with each source's network call mocked.
"""
import datetime

from fastapi.testclient import TestClient

from app import db
from app.main import ACTIVE_SOURCES, _parse_batch_niches, app
from app.scoring import score_google_trends_series
from app.sources.base import TermSignal


def _series(values: list[float]) -> list[dict]:
    base = datetime.date(2026, 6, 1)
    return [
        {"date": str(base + datetime.timedelta(days=i)), "value": v}
        for i, v in enumerate(values)
    ]


def _make_signal(niche: str, values: list[float]) -> TermSignal:
    scored = score_google_trends_series(values)
    return TermSignal(
        term=niche,
        source="google_trends",
        score=scored["score"],
        growth_pct=scored["growth_pct"],
        momentum_pct=scored["momentum_pct"],
        avg_interest=scored["avg_interest"],
        ad_library_url=f"https://www.facebook.com/ads/library/?q={niche}",
        series=_series(values),
    )


def test_parse_batch_niches_splits_dedupes_and_caps(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "max_niches_per_batch", 3)

    result = _parse_batch_niches("cocina, Mascotas\nfitness, cocina, tecnologia, hogar")

    assert result == ["cocina", "Mascotas", "fitness"]  # deduped (case-insensitive) and capped at 3


def test_parse_batch_niches_ignores_blank_entries():
    assert _parse_batch_niches("cocina,, \n \nmascotas") == ["cocina", "mascotas"]


def test_batch_db_functions_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(db.settings, "db_path", str(tmp_path / "test.db"))
    db.init_db()

    batch_id = db.create_batch()
    run_a = db.create_search_run("cocina", batch_id=batch_id)
    run_b = db.create_search_run("mascotas", batch_id=batch_id)
    other_run = db.create_search_run("fitness")  # not part of the batch

    runs = db.get_runs_for_batch(batch_id)
    assert {r["id"] for r in runs} == {run_a, run_b}
    assert other_run not in {r["id"] for r in runs}

    batches = db.get_recent_batches()
    assert batches[0]["id"] == batch_id


def test_batch_search_runs_every_niche_and_ranks_combined(monkeypatch):
    """The actual point of the feature: one form submission with several
    niches produces one combined, score-ranked list spanning all of them —
    not separate silos you'd have to check one by one.
    """
    def fake_fetch(niche, max_terms):
        # A flat series scores ~0 regardless of its level (score reflects
        # change over time, not the absolute level) — so give "mascotas" a
        # genuinely rising series and "cocina" a flat one to get a real,
        # predictable score difference to assert the ranking on.
        values = list(range(5, 95)) if niche == "mascotas" else [50] * 90
        return [_make_signal(niche, values)]

    monkeypatch.setattr(ACTIVE_SOURCES[0], "fetch_signals", fake_fetch)

    with TestClient(app) as client:
        resp = client.post(
            "/batch-search", data={"niches": "cocina, mascotas"}, follow_redirects=False
        )
        assert resp.status_code == 303
        batch_url = resp.headers["location"]
        assert batch_url.startswith("/batch/")

        batch_page = client.get(batch_url)
        assert batch_page.status_code == 200
        assert "cocina" in batch_page.text
        assert "mascotas" in batch_page.text

        # mascotas' higher score should rank first in the combined table —
        # check within <tbody> specifically, since the header's "niches in
        # this batch" list mentions them in submission order (cocina first).
        table_text = batch_page.text[batch_page.text.index("<tbody>"):]
        assert table_text.index("mascotas") < table_text.index("cocina")

        batch_id = batch_url.rstrip("/").split("/")[-1]
        csv_resp = client.get(f"/batch/{batch_id}/export.csv")
        assert csv_resp.status_code == 200
        assert "text/csv" in csv_resp.headers["content-type"]
        assert "cocina" in csv_resp.text
        assert "mascotas" in csv_resp.text

        # Each niche's own results page still works independently.
        runs = db.get_runs_for_batch(int(batch_id))
        for run in runs:
            individual_page = client.get(f"/results/{run['id']}")
            assert individual_page.status_code == 200

        home = client.get("/")
        assert f"#{batch_id}" in home.text


def test_batch_search_with_no_valid_niches_redirects_home():
    with TestClient(app) as client:
        resp = client.post("/batch-search", data={"niches": "   ,  \n "}, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
