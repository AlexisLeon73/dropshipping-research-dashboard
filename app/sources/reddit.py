"""Reddit source: official OAuth2 API, "app-only" access via the
client_credentials grant (no Reddit account login needed — just the
app's own REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET from a "script" app at
https://www.reddit.com/prefs/apps).

Rate limit: ~60 requests/minute per Reddit's API rules. Handled with the
same disk-cache + exponential-backoff pattern as
app/sources/google_trends.py (cache TTL: REDDIT_CACHE_TTL_HOURS, default
6h — shorter than Trends' because Reddit discussion moves faster than
search-interest trends).

v1 scope: Reddit has no "related queries" endpoint like Google Trends
does, so this source returns a single TermSignal for the niche term
itself — not a list of related terms. It searches Reddit for posts
mentioning the niche over the last year, buckets them into a 90-day daily
post-count series, normalizes that to a 0-100 scale, and scores it with
the exact same growth/momentum formula used for Trends (post volume
standing in for search interest). Extending this to score Trends'
individual related terms too would mean one Reddit search call per term —
budget that against the 60 req/min limit before doing it.
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

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
SEARCH_URL = "https://oauth.reddit.com/search"
WINDOW_DAYS = 90
MAX_RETRIES = 4
INITIAL_BACKOFF_SECONDS = 2
MAX_PAGES = 3  # up to 3 * 100 = 300 posts considered per search


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
                "Reddit API call failed (attempt %s/%s): %s%s",
                attempt, MAX_RETRIES, exc, "" if is_last else f" — retrying in {delay}s",
            )
            if is_last:
                break
            time.sleep(delay)
            delay *= 2
    raise last_error


class RedditSource(SignalSource):
    name = "reddit"

    def __init__(self):
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def is_configured(self) -> bool:
        return bool(settings.reddit_client_id and settings.reddit_client_secret)

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        def _fetch():
            resp = requests.post(
                TOKEN_URL,
                auth=(settings.reddit_client_id, settings.reddit_client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": settings.reddit_user_agent},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()

        payload = _with_retry(_fetch)
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 3600)
        return self._token

    def _search_posts(self, term: str) -> list[dict]:
        cache_key = f"reddit_search:{term}"
        cached = cache.get(cache_key, settings.reddit_cache_ttl_hours)
        if cached is not None:
            return cached

        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": settings.reddit_user_agent,
        }

        posts: list[dict] = []
        after = None
        for page in range(MAX_PAGES):
            params = {"q": term, "sort": "new", "limit": 100, "t": "year"}
            if after:
                params["after"] = after

            def _fetch(params=params):
                resp = requests.get(SEARCH_URL, headers=headers, params=params, timeout=10)
                resp.raise_for_status()
                return resp.json()

            data = _with_retry(_fetch)
            children = data.get("data", {}).get("children", [])
            if not children:
                break
            posts.extend(c["data"] for c in children)
            after = data.get("data", {}).get("after")
            if not after:
                break
            if page < MAX_PAGES - 1:
                time.sleep(1)  # stay comfortably under 60 req/min

        cache.set(cache_key, posts)
        return posts

    def _daily_series(self, posts: list[dict]) -> list[dict]:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=WINDOW_DAYS)
        counts: dict[str, int] = defaultdict(int)
        for post in posts:
            created = datetime.fromtimestamp(post["created_utc"], tz=timezone.utc)
            if created < start:
                continue
            counts[created.date().isoformat()] += 1

        max_count = max(counts.values(), default=0)
        series = []
        for i in range(WINDOW_DAYS):
            day = (start + timedelta(days=i)).date().isoformat()
            raw = counts.get(day, 0)
            value = (raw / max_count * 100) if max_count else 0.0
            series.append({"date": day, "value": round(value, 1)})
        return series

    def fetch_signals(self, niche: str, max_terms: int) -> list[TermSignal]:
        posts = self._search_posts(niche)
        series = self._daily_series(posts)
        values = [point["value"] for point in series]
        scored = score_google_trends_series(values)

        return [
            TermSignal(
                term=niche,
                source=self.name,
                score=scored["score"],
                growth_pct=scored["growth_pct"],
                momentum_pct=scored["momentum_pct"],
                avg_interest=scored["avg_interest"],
                competition_estimate=None,
                competition_label="Requires Meta Ads Library (not wired up yet)",
                ad_library_url=ads_library_url(niche),
                series=series,
            )
        ]
