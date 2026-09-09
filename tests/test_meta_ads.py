"""Meta Ads Library source tests. The Graph API call is mocked — this
sandbox has no general internet egress. What's verified for real: the
daily-bucketing math (ad_delivery_start_time -> 90-day series), pagination
via the "next" URL, that the active-ad count becomes competition_estimate,
and that ads are grouped by page_name into a ranked top_advertisers list
with a direct link to a sample ad per advertiser.
"""
import datetime

from app.sources.meta_ads import MetaAdsSource


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_is_configured_requires_access_token(monkeypatch):
    import app.sources.meta_ads as meta_ads_module

    source = MetaAdsSource()
    monkeypatch.setattr(meta_ads_module.settings, "meta_access_token", "")
    assert source.is_configured() is False

    monkeypatch.setattr(meta_ads_module.settings, "meta_access_token", "tok")
    assert source.is_configured() is True


def test_daily_series_buckets_by_delivery_start(monkeypatch):
    source = MetaAdsSource()
    now = datetime.datetime.now(datetime.timezone.utc)

    def iso(days_ago):
        return (now - datetime.timedelta(days=days_ago)).isoformat().replace("+00:00", "+0000")

    ads = (
        [{"ad_delivery_start_time": iso(1)}] * 8
        + [{"ad_delivery_start_time": iso(10)}] * 4
        + [{"ad_delivery_start_time": iso(200)}]  # outside the 90-day window
        + [{"id": "no-start-time"}]  # missing field, should be skipped safely
    )

    series = source._daily_series(ads)

    assert len(series) == 90
    values_by_date = {p["date"]: p["value"] for p in series}
    busiest_day = (now - datetime.timedelta(days=1)).date().isoformat()
    quieter_day = (now - datetime.timedelta(days=10)).date().isoformat()
    assert values_by_date[busiest_day] == 100.0
    assert values_by_date[quieter_day] == 50.0


def test_search_ads_paginates_via_next_url(monkeypatch):
    import app.sources.meta_ads as meta_ads_module

    monkeypatch.setattr(meta_ads_module.settings, "meta_access_token", "tok")

    page_one = {
        "data": [{"id": "1"}, {"id": "2"}],
        "paging": {"next": "https://graph.facebook.com/next-page"},
    }
    page_two = {"data": [{"id": "3"}], "paging": {}}
    responses = [page_one, page_two]

    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return _FakeResponse(responses.pop(0))

    monkeypatch.setattr(meta_ads_module.requests, "get", fake_get)

    source = MetaAdsSource()
    ads = source._search_ads("mascotas")

    assert len(ads) == 3
    assert len(calls) == 2
    assert calls[1] == "https://graph.facebook.com/next-page"


def test_top_advertisers_groups_by_page_and_ranks_by_ad_count():
    source = MetaAdsSource()
    ads = (
        [{"page_name": "PageA", "ad_snapshot_url": "https://fb.com/a1"}] * 5
        + [{"page_name": "PageB", "ad_snapshot_url": "https://fb.com/b1"}] * 2
        + [{"page_name": "PageA", "ad_snapshot_url": "https://fb.com/a2"}]  # 2nd PageA ad
        + [{"ad_snapshot_url": "https://fb.com/no-page"}]  # missing page_name, skipped
    )

    top = source._top_advertisers(ads)

    assert [a["page_name"] for a in top] == ["PageA", "PageB"]
    assert top[0]["ad_count"] == 6
    assert top[0]["sample_ad_url"] == "https://fb.com/a1"  # first one seen
    assert top[1]["ad_count"] == 2


def test_top_advertisers_respects_limit():
    source = MetaAdsSource()
    ads = [{"page_name": f"Page{i}", "ad_snapshot_url": f"https://fb.com/{i}"} for i in range(10)]

    top = source._top_advertisers(ads, limit=3)

    assert len(top) == 3


def test_fetch_signals_sets_competition_estimate_and_top_advertisers(monkeypatch):
    import app.sources.meta_ads as meta_ads_module

    monkeypatch.setattr(meta_ads_module.settings, "meta_access_token", "tok")
    now = datetime.datetime.now(datetime.timezone.utc)
    ads_payload = {
        "data": [
            {
                "id": str(i),
                "page_name": "WinnerPage" if i < 5 else "OtherPage",
                "ad_snapshot_url": f"https://fb.com/ad{i}",
                "ad_delivery_start_time": (now - datetime.timedelta(days=2)).isoformat(),
            }
            for i in range(7)
        ],
        "paging": {},
    }
    monkeypatch.setattr(
        meta_ads_module.requests, "get", lambda *a, **k: _FakeResponse(ads_payload)
    )

    source = MetaAdsSource()
    signals = source.fetch_signals("mascotas", max_terms=10)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.term == "mascotas"
    assert signal.source == "meta_ads"
    assert signal.competition_estimate == 7
    assert "7 active ads" in signal.competition_label
    assert signal.top_advertisers[0]["page_name"] == "WinnerPage"
    assert signal.top_advertisers[0]["ad_count"] == 5
    assert signal.top_advertisers[0]["sample_ad_url"] == "https://fb.com/ad0"
