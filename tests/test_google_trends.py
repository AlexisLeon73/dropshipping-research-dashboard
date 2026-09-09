"""Google Trends source tests. The pytrends client is mocked — this
sandbox has no general internet egress. What's verified for real: that
GOOGLE_TRENDS_CATEGORY is actually passed through to every build_payload
call (the fix for related-terms noise like "mascotas" pulling in World
Cup mascots instead of pet products), and that the disk cache key changes
when the category changes so switching it doesn't serve stale results
from a different category.
"""
import pandas as pd

import app.sources.google_trends as gt_module
from app.sources.google_trends import GoogleTrendsSource


class _FakeClient:
    def __init__(self):
        self.build_payload_calls = []

    def build_payload(self, kw_list, timeframe=None, geo=None, cat=None):
        self.build_payload_calls.append(
            {"kw_list": kw_list, "timeframe": timeframe, "geo": geo, "cat": cat}
        )

    def related_queries(self):
        return {}

    def interest_over_time(self):
        return pd.DataFrame()


def test_related_terms_passes_category_to_build_payload(monkeypatch):
    monkeypatch.setattr(gt_module.settings, "google_trends_category", 18)
    source = GoogleTrendsSource()
    fake_client = _FakeClient()
    monkeypatch.setattr(source, "_client", lambda: fake_client)

    source._related_terms("mascotas", max_terms=10)

    assert fake_client.build_payload_calls[0]["cat"] == 18


def test_interest_over_time_batch_passes_category_to_build_payload(monkeypatch):
    monkeypatch.setattr(gt_module.settings, "google_trends_category", 18)
    source = GoogleTrendsSource()
    fake_client = _FakeClient()
    monkeypatch.setattr(source, "_client", lambda: fake_client)

    source._interest_over_time_batch(["mascotas"])

    assert fake_client.build_payload_calls[0]["cat"] == 18


def test_cache_key_changes_when_category_changes(monkeypatch):
    """Without this, flipping GOOGLE_TRENDS_CATEGORY between runs would
    silently serve results cached under a different category.
    """
    source = GoogleTrendsSource()
    fake_client = _FakeClient()
    monkeypatch.setattr(source, "_client", lambda: fake_client)

    monkeypatch.setattr(gt_module.settings, "google_trends_category", 18)
    source._related_terms("mascotas", max_terms=10)

    monkeypatch.setattr(gt_module.settings, "google_trends_category", 0)
    source._related_terms("mascotas", max_terms=10)

    assert len(fake_client.build_payload_calls) == 2
