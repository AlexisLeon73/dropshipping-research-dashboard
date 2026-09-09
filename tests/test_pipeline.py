"""Full pipeline test through the real FastAPI app (routing, templates,
SQLite storage, scoring, CSV export, week-over-week deltas).

The only thing mocked is the network call to Google Trends itself — this
sandbox has no general internet egress, so GoogleTrendsSource.fetch_signals
is swapped for a fake that returns realistic-shaped series data and runs
through the *real* scoring function. Everything downstream of that call is
exercised for real.
"""
import datetime

from fastapi.testclient import TestClient

from app.main import ACTIVE_SOURCES, app
from app.scoring import score_google_trends_series
from app.sources.base import TermSignal


def _series(values: list[float]) -> list[dict]:
    base = datetime.date(2026, 6, 1)
    return [
        {"date": str(base + datetime.timedelta(days=i)), "value": v}
        for i, v in enumerate(values)
    ]


def _make_signal(term: str, values: list[float]) -> TermSignal:
    scored = score_google_trends_series(values)
    return TermSignal(
        term=term,
        source="google_trends",
        score=scored["score"],
        growth_pct=scored["growth_pct"],
        momentum_pct=scored["momentum_pct"],
        avg_interest=scored["avg_interest"],
        competition_estimate=None,
        competition_label="Requires Meta Ads Library (not wired up yet)",
        ad_library_url=f"https://www.facebook.com/ads/library/?q={term}",
        series=_series(values),
    )


def _fake_fetch_signals(niche: str, max_terms: int):
    rising = list(range(5, 95))
    flat = [50] * 90
    return [
        _make_signal(niche, rising),
        _make_signal(f"{niche} organizer", flat),
    ][:max_terms]


def test_full_search_pipeline(monkeypatch):
    monkeypatch.setattr(ACTIVE_SOURCES[0], "fetch_signals", _fake_fetch_signals)

    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200

        first = client.post("/search", data={"niche": "cocina"}, follow_redirects=False)
        assert first.status_code == 303
        first_results_url = first.headers["location"]

        results_page = client.get(first_results_url)
        assert results_page.status_code == 200
        assert "cocina" in results_page.text
        assert "cocina organizer" in results_page.text
        assert "No previous run" in results_page.text

        run_id = first_results_url.rstrip("/").split("/")[-1]
        csv_resp = client.get(f"/export/{run_id}.csv")
        assert csv_resp.status_code == 200
        assert "text/csv" in csv_resp.headers["content-type"]
        assert "cocina" in csv_resp.text
        assert "score" in csv_resp.text

        # Second run for the same niche should show week-over-week deltas.
        second = client.post("/search", data={"niche": "cocina"}, follow_redirects=False)
        second_results_url = second.headers["location"]
        second_page = client.get(second_results_url)
        assert second_page.status_code == 200
        assert "Compared against previous run" in second_page.text
        # Scores are identical between runs (same fake data), so delta is 0.0.
        assert "0.0" in second_page.text

        home_after = client.get("/")
        assert home_after.text.count("cocina") >= 2


def test_index_renders():
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Research a niche" in resp.text
