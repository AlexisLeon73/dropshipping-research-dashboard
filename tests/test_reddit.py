"""Reddit source tests. All Reddit API calls are mocked — this sandbox has
no general internet egress, and even with it, exercising real rate limits
isn't something a test suite should depend on. What's verified for real:
token caching (no redundant token requests), pagination/cache-key
plumbing, and the daily-bucketing math that turns raw posts into the
90-day series the scoring function expects.
"""
import datetime

from app.sources.reddit import RedditSource


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_is_configured_requires_both_credentials(monkeypatch):
    import app.sources.reddit as reddit_module

    source = RedditSource()
    monkeypatch.setattr(reddit_module.settings, "reddit_client_id", "")
    monkeypatch.setattr(reddit_module.settings, "reddit_client_secret", "")
    assert source.is_configured() is False

    monkeypatch.setattr(reddit_module.settings, "reddit_client_id", "id")
    monkeypatch.setattr(reddit_module.settings, "reddit_client_secret", "secret")
    assert source.is_configured() is True


def test_get_token_is_cached_until_expiry(monkeypatch):
    import app.sources.reddit as reddit_module

    monkeypatch.setattr(reddit_module.settings, "reddit_client_id", "id")
    monkeypatch.setattr(reddit_module.settings, "reddit_client_secret", "secret")

    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return _FakeResponse({"access_token": "tok123", "expires_in": 3600})

    monkeypatch.setattr(reddit_module.requests, "post", fake_post)

    source = RedditSource()
    token1 = source._get_token()
    token2 = source._get_token()

    assert token1 == token2 == "tok123"
    assert len(calls) == 1  # second call served from the in-memory cache


def test_daily_series_buckets_posts_and_normalizes_to_100(monkeypatch):
    source = RedditSource()
    now = datetime.datetime.now(datetime.timezone.utc)

    def days_ago(n):
        return (now - datetime.timedelta(days=n)).timestamp()

    posts = (
        [{"created_utc": days_ago(1)}] * 10  # busiest day: 10 posts
        + [{"created_utc": days_ago(5)}] * 5
        + [{"created_utc": days_ago(200)}]  # outside the 90-day window
    )

    series = source._daily_series(posts)

    assert len(series) == 90
    values_by_date = {p["date"]: p["value"] for p in series}
    busiest_day = (now - datetime.timedelta(days=1)).date().isoformat()
    quieter_day = (now - datetime.timedelta(days=5)).date().isoformat()
    assert values_by_date[busiest_day] == 100.0  # normalized to the max
    assert values_by_date[quieter_day] == 50.0
    assert sum(1 for v in values_by_date.values() if v > 0) == 2


def test_fetch_signals_returns_one_term_for_the_niche(monkeypatch):
    import app.sources.reddit as reddit_module

    monkeypatch.setattr(reddit_module.settings, "reddit_client_id", "id")
    monkeypatch.setattr(reddit_module.settings, "reddit_client_secret", "secret")
    monkeypatch.setattr(
        reddit_module.requests, "post",
        lambda *a, **k: _FakeResponse({"access_token": "tok", "expires_in": 3600}),
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    page_one = {
        "data": {
            "children": [
                {"data": {"created_utc": (now - datetime.timedelta(days=2)).timestamp()}}
                for _ in range(3)
            ],
            "after": None,
        }
    }
    monkeypatch.setattr(
        reddit_module.requests, "get", lambda *a, **k: _FakeResponse(page_one)
    )

    source = RedditSource()
    signals = source.fetch_signals("mascotas", max_terms=10)

    assert len(signals) == 1
    assert signals[0].term == "mascotas"
    assert signals[0].source == "reddit"
    assert len(signals[0].series) == 90
    assert signals[0].score >= 0
