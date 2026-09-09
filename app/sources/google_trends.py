"""Google Trends source, via pytrends (unofficial, scrapes trends.google.com).

There is no official Trends API and no API key. In exchange we get:
  - Aggressive rate limiting: Google returns HTTP 429 after a handful of
    requests in a short window, sometimes even sooner.
  - No SLA / no stability guarantee: this can break if Google changes the
    site pytrends scrapes.

To live with that:
  - Every request result is cached to disk (see app/cache.py) for
    GOOGLE_TRENDS_CACHE_TTL_HOURS (default 12h), so re-running a search
    for the same niche doesn't re-hit Google.
  - interest_over_time requests are batched up to 5 keywords per call
    (the max pytrends/Google Trends allows in one request), so a search
    for 10 related terms costs ~2 requests instead of 10.
  - Failed requests are retried with exponential backoff (2s, 4s, 8s, 16s,
    32s). If a batch still fails after that, it's skipped rather than
    crashing the whole search — you get a partial result instead of
    nothing.

Related-terms noise: "related queries" for a broad niche word isn't
product-aware — it returns whatever else people search alongside that
word, which for something like "mascotas" (pets) can pull in unrelated
current events (e.g. World Cup mascots) that happen to share the word.
GOOGLE_TRENDS_CATEGORY restricts every request to a Google category (18 =
Shopping by default) to bias results toward commercial/shopping intent
and cut most of that noise. It's a real improvement, not a full fix: for
a generic niche you'll still get topic-level related terms (types of
products, not one specific product) — that's inherent to how broad the
seed word is, not something a category filter alone can solve.
"""
from __future__ import annotations

import logging
import time

from pytrends.request import TrendReq

from app import cache
from app.config import settings
from app.scoring import score_google_trends_series
from app.sources.base import SignalSource, TermSignal, ads_library_url

logger = logging.getLogger(__name__)

TIMEFRAME = "today 3-m"  # ~90 days
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2
BATCH_SIZE = 5  # Google Trends allows up to 5 keywords per request


def _with_retry(fn, *args, **kwargs):
    delay = INITIAL_BACKOFF_SECONDS
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # pytrends raises plain Exception/ResponseError
            last_error = exc
            is_last = attempt == MAX_RETRIES
            logger.warning(
                "pytrends call failed (attempt %s/%s): %s%s",
                attempt, MAX_RETRIES, exc, "" if is_last else f" — retrying in {delay}s",
            )
            if is_last:
                break
            time.sleep(delay)
            delay *= 2
    raise last_error


class GoogleTrendsSource(SignalSource):
    name = "google_trends"
    # per_term = False (default): this is the source that *discovers* the
    # candidate term list from the niche via related_queries(), which
    # app.main.run_search then feeds to the per_term=True sources.

    def __init__(self):
        self._pytrends = None

    def is_configured(self) -> bool:
        return True  # no credentials needed

    def _client(self) -> TrendReq:
        if self._pytrends is None:
            self._pytrends = TrendReq(hl=settings.google_trends_hl, tz=360)
        return self._pytrends

    def _related_terms(self, niche: str, max_terms: int) -> list[str]:
        cache_key = (
            f"related:{niche}:{settings.google_trends_geo}:"
            f"{settings.google_trends_hl}:cat{settings.google_trends_category}"
        )
        cached = cache.get(cache_key, settings.google_trends_cache_ttl_hours)
        if cached is not None:
            return cached[:max_terms]

        def _fetch():
            client = self._client()
            client.build_payload(
                [niche],
                timeframe=TIMEFRAME,
                geo=settings.google_trends_geo,
                cat=settings.google_trends_category,
            )
            return client.related_queries()

        related = _with_retry(_fetch)
        terms: list[str] = []
        entry = related.get(niche) if related else None
        if entry:
            for key in ("top", "rising"):
                df = entry.get(key)
                if df is not None and not df.empty:
                    terms.extend(df["query"].tolist())

        # Dedupe, keep order, always include the niche term itself first.
        seen = {niche.lower()}
        ordered = [niche]
        for t in terms:
            if t.lower() not in seen:
                seen.add(t.lower())
                ordered.append(t)

        cache.set(cache_key, ordered)
        return ordered[:max_terms]

    def _interest_over_time_batch(self, terms: list[str]) -> dict[str, list[dict]]:
        cache_key = (
            f"iot:{','.join(sorted(terms))}:{settings.google_trends_geo}:"
            f"{settings.google_trends_hl}:cat{settings.google_trends_category}"
        )
        cached = cache.get(cache_key, settings.google_trends_cache_ttl_hours)
        if cached is not None:
            return cached

        def _fetch():
            client = self._client()
            client.build_payload(
                terms,
                timeframe=TIMEFRAME,
                geo=settings.google_trends_geo,
                cat=settings.google_trends_category,
            )
            return client.interest_over_time()

        df = _with_retry(_fetch)
        result: dict[str, list[dict]] = {}
        if df is not None and not df.empty:
            for term in terms:
                if term not in df.columns:
                    continue
                series = [
                    {"date": str(idx.date()), "value": float(val)}
                    for idx, val in df[term].items()
                ]
                result[term] = series

        cache.set(cache_key, result)
        return result

    def fetch_signals(self, niche: str, max_terms: int) -> list[TermSignal]:
        terms = self._related_terms(niche, max_terms)
        signals: list[TermSignal] = []

        for i in range(0, len(terms), BATCH_SIZE):
            batch = terms[i : i + BATCH_SIZE]
            try:
                batch_series = self._interest_over_time_batch(batch)
            except Exception as exc:
                logger.warning("Skipping batch %s after repeated failures: %s", batch, exc)
                continue

            for term in batch:
                series = batch_series.get(term)
                if not series:
                    continue
                values = [point["value"] for point in series]
                scored = score_google_trends_series(values)
                signals.append(
                    TermSignal(
                        term=term,
                        source=self.name,
                        score=scored["score"],
                        growth_pct=scored["growth_pct"],
                        momentum_pct=scored["momentum_pct"],
                        avg_interest=scored["avg_interest"],
                        competition_estimate=None,
                        competition_label="No Meta Ads Library data for this term",
                        ad_library_url=ads_library_url(term),
                        series=series,
                    )
                )

            # Be polite even when everything succeeds — this is what
            # actually keeps repeated searches from tripping the 429 wall.
            if i + BATCH_SIZE < len(terms):
                time.sleep(1.5)

        return signals
