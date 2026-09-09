"""Meta Ads Library source — NOT IMPLEMENTED YET.

Plan:
  - Auth: official Meta Ad Library API (graph.facebook.com/.../ads_archive),
    requires an access token from an app at https://developers.facebook.com
    with Ad Library access. Set META_ACCESS_TOKEN (see .env.example).
    This is the official API — no scraping of the public ad library site.
  - Rate limit: ~200 calls/hour per Meta's documented limits — reuse the
    disk cache + backoff pattern from app/sources/google_trends.py.
  - Signal: search ads_archive for the term, count active ads as a
    competition_estimate, and use ad count growth over time as the demand
    signal (more advertisers actively running ads for a term is one of
    the strongest "this converts" signals available). This is also the
    module that should eventually fill in competition_estimate /
    competition_label for terms that currently only have Google Trends
    data.
"""
from __future__ import annotations

from app.config import settings
from app.sources.base import SignalSource, TermSignal


class MetaAdsSource(SignalSource):
    name = "meta_ads"

    def is_configured(self) -> bool:
        return bool(settings.meta_access_token)

    def fetch_signals(self, niche: str, max_terms: int) -> list[TermSignal]:
        raise NotImplementedError(
            "Meta Ads Library source is not implemented yet. Set "
            "META_ACCESS_TOKEN and implement fetch_signals() in "
            "app/sources/meta_ads.py."
        )
