"""TikTok source — NOT IMPLEMENTED YET.

TikTok has no public API usable for this (the official Research API is
restricted to approved academic/institutional applicants). The only
practical option is TikTok Creative Center
(https://ads.tiktok.com/business/creativecenter/), which is public and
needs no login, but is an undocumented, best-effort scrape target that can
break without notice — treat any implementation here as fragile by design,
same caching/backoff discipline as the other sources, and degrade
gracefully (skip the source) rather than fail the whole search when it
breaks. Its Keyword Insights tool is a single-keyword lookup (no
"related terms" of its own), so set per_term = True like Reddit and Meta
Ads — `app.main.run_search` will then call fetch_signals once per term
Google Trends discovers instead of just the bare niche.
"""
from __future__ import annotations

from app.sources.base import SignalSource, TermSignal


class TikTokSource(SignalSource):
    name = "tiktok"
    per_term = True

    def is_configured(self) -> bool:
        return False

    def fetch_signals(self, niche: str, max_terms: int) -> list[TermSignal]:
        raise NotImplementedError(
            "TikTok source is not implemented yet — see module docstring "
            "for why this one is inherently fragile."
        )
