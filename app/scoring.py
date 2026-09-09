"""Demand-signal scoring.

Goal: turn a raw interest-over-time series into a single 0-100 score that's
easy to explain, not a black box. Right now only Google Trends feeds this,
but the shape is built so that Reddit / Meta Ads / TikTok scores can be
added later as more weighted inputs to `combine_source_scores`.

--- Google Trends per-term score (0-100) ---

From the 90-day daily interest series (0-100 scale, as returned by Google):

1. growth_pct: compares the average of the first 7 days of the window to
   the average of the last 7 days. This is the "did this actually go up
   over the last ~3 months" signal.

       growth_pct = (avg_last_7 - avg_first_7) / max(avg_first_7, 1) * 100

2. momentum_pct: compares the last 7 days to the whole 90-day average.
   This catches something that's spiking *right now* even if the 90-day
   trend line looks flat overall.

       momentum_pct = (avg_last_7 - avg_all) / max(avg_all, 1) * 100

3. Both percentages are clipped to [-100, 200] and rescaled into [0, 100]
   with clip_and_scale(), then blended:

       raw_score = 0.6 * scaled(growth_pct) + 0.4 * scaled(momentum_pct)

   Growth is weighted higher because a term that's been climbing steadily
   for 3 months is a stronger signal than a single recent blip, but recent
   momentum still matters for catching things early.

This is deliberately simple. It is a prioritization heuristic, not a
prediction: it tells you what to look at first, not what will sell.

--- Combining sources (future) ---

Once Reddit / Meta Ads / TikTok are wired up, each source produces its own
0-100 score for a term the same way (documented in its own module).
`combine_source_scores` averages whatever sources are available, weighted
by SOURCE_WEIGHTS, and renormalizes over just the sources that returned
data (so a term isn't penalized for a source being unconfigured).
"""
from __future__ import annotations

# Relative importance of each source once it's wired up. Google Trends is
# the only one active today, so it's the only one that matters right now.
SOURCE_WEIGHTS = {
    "google_trends": 1.0,
    "reddit": 0.7,
    "meta_ads": 1.2,  # active ads are a stronger buy-signal than search interest
    "tiktok": 0.6,
}


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _clip_and_scale(pct: float, lo: float = -100.0, hi: float = 200.0) -> float:
    """Map a percentage change (roughly -100%..+200%) onto a 0-100 scale."""
    clipped = max(lo, min(hi, pct))
    return (clipped - lo) / (hi - lo) * 100


def score_google_trends_series(values: list[float]) -> dict:
    """values: daily interest values (0-100), oldest first, ~90 days."""
    if len(values) < 2:
        return {"score": 0.0, "growth_pct": 0.0, "momentum_pct": 0.0, "avg_interest": _avg(values)}

    window = min(7, len(values) // 2 or 1)
    first_chunk = values[:window]
    last_chunk = values[-window:]

    avg_first = _avg(first_chunk)
    avg_last = _avg(last_chunk)
    avg_all = _avg(values)

    growth_pct = (avg_last - avg_first) / max(avg_first, 1.0) * 100
    momentum_pct = (avg_last - avg_all) / max(avg_all, 1.0) * 100

    raw_score = 0.6 * _clip_and_scale(growth_pct) + 0.4 * _clip_and_scale(momentum_pct)

    return {
        "score": round(raw_score, 1),
        "growth_pct": round(growth_pct, 1),
        "momentum_pct": round(momentum_pct, 1),
        "avg_interest": round(avg_all, 1),
    }


def combine_source_scores(source_scores: dict[str, float]) -> float:
    """source_scores: {"google_trends": 72.0, "reddit": None, ...}.

    Only sources with a non-None score contribute, weighted by
    SOURCE_WEIGHTS and renormalized so missing sources don't drag the
    score down just because they aren't configured yet.
    """
    available = {k: v for k, v in source_scores.items() if v is not None}
    if not available:
        return 0.0
    total_weight = sum(SOURCE_WEIGHTS.get(k, 1.0) for k in available)
    weighted_sum = sum(v * SOURCE_WEIGHTS.get(k, 1.0) for k, v in available.items())
    return round(weighted_sum / total_weight, 1)
