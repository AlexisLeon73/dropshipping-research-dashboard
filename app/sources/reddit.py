"""Reddit source — NOT IMPLEMENTED YET.

Plan (documented so this is a quick follow-up, not a redesign):
  - Auth: OAuth2 "script" app (praw or raw requests against
    https://oauth.reddit.com). Needs REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET
    (see .env.example) from https://www.reddit.com/prefs/apps.
  - Rate limit: ~60 requests/minute per the Reddit API terms — reuse the
    same disk cache + backoff pattern as app/sources/google_trends.py.
  - Signal: search relevant subreddits (or site-wide) for the niche/term,
    count mentions and upvotes/comments growth over a recent window vs a
    baseline window. Score it 0-100 the same shape as
    score_google_trends_series so it drops straight into
    scoring.combine_source_scores under the "reddit" key.
"""
from __future__ import annotations

from app.config import settings
from app.sources.base import SignalSource, TermSignal


class RedditSource(SignalSource):
    name = "reddit"

    def is_configured(self) -> bool:
        return bool(settings.reddit_client_id and settings.reddit_client_secret)

    def fetch_signals(self, niche: str, max_terms: int) -> list[TermSignal]:
        raise NotImplementedError(
            "Reddit source is not implemented yet. Set REDDIT_CLIENT_ID / "
            "REDDIT_CLIENT_SECRET and implement fetch_signals() in "
            "app/sources/reddit.py."
        )
