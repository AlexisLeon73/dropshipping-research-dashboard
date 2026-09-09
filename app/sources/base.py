"""Shared interface every signal source implements.

Adding a new source (Reddit, Meta Ads, TikTok, ...) means writing one
class here that implements `is_configured` and `fetch_signals`, then
registering it in `app/sources/__init__.py`'s ACTIVE_SOURCES-equivalent in
main.py. Nothing else in the app needs to change.
"""
from __future__ import annotations

import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


def ads_library_url(term: str) -> str:
    """Meta Ads Library search URL for manually inspecting active ads for a
    term. Shared by every source, since "go look at the actual ads" is the
    same follow-up regardless of which source flagged the term.
    """
    query = urllib.parse.urlencode({
        "active_status": "active",
        "ad_type": "all",
        "country": "ALL",
        "q": term,
    })
    return f"https://www.facebook.com/ads/library/?{query}"


@dataclass
class TermSignal:
    term: str
    source: str
    score: float
    growth_pct: float | None = None
    momentum_pct: float | None = None
    avg_interest: float | None = None
    competition_estimate: int | None = None
    competition_label: str | None = None
    ad_library_url: str | None = None
    series: list[dict] = field(default_factory=list)  # [{"date": "...", "value": 0}]
    # [{"page_name": ..., "ad_count": N, "sample_ad_url": "..."}, ...],
    # ranked by ad_count desc. Only ever populated by Meta Ads Library today.
    top_advertisers: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "term": self.term,
            "source": self.source,
            "score": self.score,
            "growth_pct": self.growth_pct,
            "momentum_pct": self.momentum_pct,
            "avg_interest": self.avg_interest,
            "competition_estimate": self.competition_estimate,
            "competition_label": self.competition_label,
            "ad_library_url": self.ad_library_url,
            "series": self.series,
            "top_advertisers": self.top_advertisers,
        }


class SignalSource(ABC):
    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether the credentials/config this source needs are present."""

    @abstractmethod
    def fetch_signals(self, niche: str, max_terms: int) -> list[TermSignal]:
        """Return demand signals for terms related to `niche`."""
