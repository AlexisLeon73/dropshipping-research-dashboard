"""Full pipeline test through the real FastAPI app (routing, templates,
SQLite storage, scoring, CSV export, week-over-week deltas, multi-source
merging).

The only thing mocked is the network call each source makes — this
sandbox has no general internet egress, so each source's fetch_signals is
swapped for a fake that returns realistic-shaped series data and runs
through the *real* scoring function. Everything downstream of that call is
exercised for real.
"""
import datetime

from fastapi.testclient import TestClient

from app.main import ACTIVE_SOURCES, app, run_search
from app.scoring import combine_source_scores, score_google_trends_series
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
        competition_label="No Meta Ads Library data for this term",
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


def test_multi_source_merge_combines_scores_instead_of_dropping_one(monkeypatch):
    """Google Trends and Reddit both report a signal for the bare niche
    term ("cocina"). Before the merge fix, run_search kept only the first
    source's data for a colliding term and silently dropped the rest —
    this pins the correct behavior: every source's score for a term feeds
    combine_source_scores, and the term's `sources` field lists both.
    """
    trends_signal = _make_signal("cocina", list(range(5, 95)))  # source="google_trends"
    reddit_signal = TermSignal(
        term="cocina",
        source="reddit",
        score=90.0,
        growth_pct=50.0,
        momentum_pct=50.0,
        avg_interest=80.0,
        ad_library_url="https://www.facebook.com/ads/library/?q=cocina",
        series=_series([10] * 90),
    )

    monkeypatch.setattr(ACTIVE_SOURCES[0], "fetch_signals", lambda niche, max_terms: [trends_signal])
    monkeypatch.setattr(ACTIVE_SOURCES[1], "fetch_signals", lambda niche, max_terms: [reddit_signal])
    monkeypatch.setattr(ACTIVE_SOURCES[1], "is_configured", lambda: True)

    signals = run_search("cocina", max_terms=10)

    assert len(signals) == 1  # merged into one row, not two
    merged = signals[0]
    assert merged["sources"] == ["google_trends", "reddit"]
    expected_score = combine_source_scores(
        {"google_trends": trends_signal.score, "reddit": 90.0}
    )
    assert merged["score"] == expected_score
    # Google Trends outranks Reddit in PRIMARY_SOURCE_PRIORITY, so display
    # fields (series/growth/momentum) come from the Trends signal.
    assert merged["growth_pct"] == trends_signal.growth_pct


def test_multi_source_merge_end_to_end_via_http(monkeypatch):
    trends_signal = _make_signal("mascotas", list(range(5, 95)))
    reddit_signal = TermSignal(
        term="mascotas",
        source="reddit",
        score=90.0,
        growth_pct=50.0,
        momentum_pct=50.0,
        avg_interest=80.0,
        ad_library_url="https://www.facebook.com/ads/library/?q=mascotas",
        series=_series([10] * 90),
    )
    monkeypatch.setattr(ACTIVE_SOURCES[0], "fetch_signals", lambda niche, max_terms: [trends_signal])
    monkeypatch.setattr(ACTIVE_SOURCES[1], "fetch_signals", lambda niche, max_terms: [reddit_signal])
    monkeypatch.setattr(ACTIVE_SOURCES[1], "is_configured", lambda: True)

    with TestClient(app) as client:
        resp = client.post("/search", data={"niche": "mascotas"}, follow_redirects=False)
        results_page = client.get(resp.headers["location"])
        assert results_page.status_code == 200
        assert "google_trends + reddit" in results_page.text


def test_meta_ads_competition_data_wins_even_when_trends_is_primary(monkeypatch):
    """Google Trends outranks Meta Ads in PRIMARY_SOURCE_PRIORITY, so its
    series/growth/momentum win the display slot for a shared term — but
    Meta Ads is the only source that ever fills in real competition data,
    so that specific field must survive the merge regardless of who's
    primary. This is the whole point of adding Meta Ads Library.
    """
    trends_signal = _make_signal("fitness", list(range(5, 95)))
    meta_signal = TermSignal(
        term="fitness",
        source="meta_ads",
        score=70.0,
        growth_pct=10.0,
        momentum_pct=10.0,
        avg_interest=60.0,
        competition_estimate=42,
        competition_label="42 active ads matching this term (Meta Ad Library)",
        ad_library_url="https://www.facebook.com/ads/library/?q=fitness",
        series=_series([20] * 90),
    )

    monkeypatch.setattr(ACTIVE_SOURCES[0], "fetch_signals", lambda niche, max_terms: [trends_signal])
    monkeypatch.setattr(ACTIVE_SOURCES[2], "fetch_signals", lambda niche, max_terms: [meta_signal])
    monkeypatch.setattr(ACTIVE_SOURCES[2], "is_configured", lambda: True)

    signals = run_search("fitness", max_terms=10)

    assert len(signals) == 1
    merged = signals[0]
    assert merged["growth_pct"] == trends_signal.growth_pct  # Trends still primary
    assert merged["competition_estimate"] == 42
    assert merged["competition_label"] == "42 active ads matching this term (Meta Ad Library)"
    assert merged["sources"] == ["google_trends", "meta_ads"]
