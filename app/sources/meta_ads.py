"""Meta Ads Library source: the official Ad Library API
(graph.facebook.com/.../ads_archive) — not a scrape of the public ad
library website. Needs an access token from an app at
https://developers.facebook.com with Ad Library API access
(META_ACCESS_TOKEN in .env).

Rate limit: ~200 calls/hour per Meta's documented limits. Handled with the
same disk-cache + exponential-backoff pattern as the other sources (cache
TTL: META_CACHE_TTL_HOURS, default 6h).

Signal: search ads_archive for the niche term with ad_active_status=ACTIVE,
bucket the matching ads' ad_delivery_start_time into a 90-day daily count
(more ads *starting* to run for a term recently is a stronger "this
converts" signal than a flat, old count), and score it with the same
growth/momentum formula as the other sources. The raw active-ad count also
becomes `competition_estimate` — this is the one source that fills that
field in; see the override in `app.main.run_search` that keeps a term's
Meta Ads competition numbers even when another source wins the "primary
display" slot for that term.

v1 scope: like Reddit, this only searches the niche term itself, not each
of Google Trends' individual related terms — ads_archive has no "related
terms" endpoint, so covering every Trends-discovered term would mean one
ads_archive call per term (fine against the 200/hour limit for a handful
of terms, but that's cross-source wiring `run_search` doesn't do today —
each source only ever receives the niche and max_terms).
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

from app import cache
from app.config import settings
from app.scoring import score_google_trends_series
from app.sources.base import SignalSource, TermSignal, ads_library_url

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
ADS_ARCHIVE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}/ads_archive"
WINDOW_DAYS = 90
MAX_RETRIES = 4
INITIAL_BACKOFF_SECONDS = 2
MAX_PAGES = 5  # up to 5 * 100 = 500 ads considered per search


def _with_retry(fn, *args, **kwargs):
    delay = INITIAL_BACKOFF_SECONDS
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            is_last = attempt == MAX_RETRIES
            logger.warning(
                "Meta Ad Library call failed (attempt %s/%s): %s%s",
                attempt, MAX_RETRIES, exc, "" if is_last else f" — retrying in {delay}s",
            )
            if is_last:
                break
            time.sleep(delay)
            delay *= 2
    raise last_error


class MetaAdsSource(SignalSource):
    name = "meta_ads"

    def is_configured(self) -> bool:
        return bool(settings.meta_access_token)

    def _search_ads(self, term: str) -> list[dict]:
        cache_key = f"meta_ads_search:{term}:{settings.meta_ad_reached_countries}"
        cached = cache.get(cache_key, settings.meta_cache_ttl_hours)
        if cached is not None:
            return cached

        ads: list[dict] = []
        url = ADS_ARCHIVE_URL
        params = {
            "access_token": settings.meta_access_token,
            "search_terms": term,
            "ad_active_status": "ACTIVE",
            "ad_reached_countries": settings.meta_ad_reached_countries,
            "fields": "id,ad_delivery_start_time",
            "limit": 100,
        }

        for page in range(MAX_PAGES):
            def _fetch(url=url, params=params):
                resp = requests.get(url, params=params, timeout=15)
                resp.raise_for_status()
                return resp.json()

            data = _with_retry(_fetch)
            batch = data.get("data", [])
            if not batch:
                break
            ads.extend(batch)

            next_url = data.get("paging", {}).get("next")
            if not next_url:
                break
            # The "next" URL already carries every query param encoded.
            url, params = next_url, None
            if page < MAX_PAGES - 1:
                time.sleep(1)

        cache.set(cache_key, ads)
        return ads

    def _daily_series(self, ads: list[dict]) -> list[dict]:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=WINDOW_DAYS)
        counts: dict[str, int] = defaultdict(int)
        for ad in ads:
            raw_start = ad.get("ad_delivery_start_time")
            if not raw_start:
                continue
            started = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            if started < start:
                continue
            counts[started.date().isoformat()] += 1

        max_count = max(counts.values(), default=0)
        series = []
        for i in range(WINDOW_DAYS):
            day = (start + timedelta(days=i)).date().isoformat()
            raw = counts.get(day, 0)
            value = (raw / max_count * 100) if max_count else 0.0
            series.append({"date": day, "value": round(value, 1)})
        return series

    def fetch_signals(self, niche: str, max_terms: int) -> list[TermSignal]:
        ads = self._search_ads(niche)
        series = self._daily_series(ads)
        values = [point["value"] for point in series]
        scored = score_google_trends_series(values)

        active_count = len(ads)
        count_label = f"{active_count}+" if active_count >= MAX_PAGES * 100 else str(active_count)

        return [
            TermSignal(
                term=niche,
                source=self.name,
                score=scored["score"],
                growth_pct=scored["growth_pct"],
                momentum_pct=scored["momentum_pct"],
                avg_interest=scored["avg_interest"],
                competition_estimate=active_count,
                competition_label=f"{count_label} active ads matching this term (Meta Ad Library)",
                ad_library_url=ads_library_url(niche),
                series=series,
            )
        ]
