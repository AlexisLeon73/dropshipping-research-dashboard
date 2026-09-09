# Product Research Dashboard

A local dashboard for prioritizing dropshipping/marketplace products to
test, by cross-referencing **public demand signals** — not by asking an AI
to guess what will sell. No model here predicts sales; it surfaces and
scores public signals so you can decide what's worth testing and inspect
the evidence yourself.

You enter a niche (e.g. "cocina", "mascotas", "fitness"). The dashboard
pulls related search terms, scores each one by demand-signal growth, plots
its 90-day trend, and gives you a direct link to inspect real ads for that
term manually. Every search is saved so you can compare a niche week over
week.

## Current status

**Google Trends and Reddit are implemented.** Meta Ads Library, TikTok,
and Amazon Movers & Shakers are stubbed out as independent modules under
`app/sources/` with the integration plan documented in each file's
docstring — adding one is meant to be a self-contained follow-up, not a
redesign.

| Source | Status | Notes |
|---|---|---|
| Google Trends | ✅ Implemented | No API key. Unofficial (scrapes trends.google.com via `pytrends`), rate-limits hard. |
| Reddit | ✅ Implemented | Official OAuth2 API (client_credentials grant), needs `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`. Reports one signal per niche (post-volume growth), not per related term — see `app/sources/reddit.py`. |
| Meta Ads Library | 🚧 Stub only | Official API, needs `META_ACCESS_TOKEN`. Will also fill in the competition column. |
| TikTok | 🚧 Stub only | No usable public API — best-effort scrape of TikTok Creative Center, inherently fragile. |
| Amazon Movers & Shakers | 🔗 Manual link only | No public API; scraping amazon.com violates its ToS, so this is intentionally not automated. |

### How multiple sources combine on the same term

Google Trends and Reddit can both report a signal for the same term (most
often the bare niche itself, since Reddit doesn't have a "related terms"
feature the way Trends does). When that happens, `run_search()` in
`app/main.py` folds every source's score for that term into
`combine_source_scores()` — nothing is silently dropped just because two
sources agree on a term. The 90-day chart, growth/momentum numbers, and
ad-inspection link still come from a single "primary" source per term
(Google Trends outranks Reddit in `PRIMARY_SOURCE_PRIORITY`, since its
series has real daily granularity), but the **Sources** column on the
results page and in the CSV export always lists every source that
contributed to that row's score.

## Honest limitations of Google Trends / pytrends

- **No official API.** `pytrends` scrapes `trends.google.com`. Google can
  change that site at any time and break it without notice.
- **Aggressive, undocumented rate limiting.** Expect HTTP 429s after a
  handful of requests in a short window. The app handles this with:
  - Exponential backoff retries (2s, 4s, 8s, 16s, 32s) per request.
  - A local disk cache (`data/cache/`, 12h TTL by default) so re-running a
    search for the same niche doesn't re-hit Google.
  - Batching related terms up to 5 per request (Google's own limit).
  - If a source fails entirely (rate-limited, network down), the app
    degrades gracefully — you get an empty-state message on the results
    page instead of a crash.
- **Relative, not absolute, numbers.** Trends values are 0-100 relative to
  the peak in the selected window — they tell you about *direction* and
  *momentum*, not units sold or absolute search volume.
- **This is a prioritization heuristic, not a prediction.** It tells you
  what to look at first. Always inspect the actual ads (the "inspect ads"
  link per term) before committing budget to test a product.

### A note on this build's testing

This app was built and tested in a sandboxed environment with no general
internet access (only a small dev-tooling allowlist — pypi, npm, github,
etc.). That means the actual live calls to `trends.google.com` and Reddit's
API could not be exercised here — a real run there returns a
`ProxyError`/403, which is this sandbox's network policy, not a bug in the
code. Everything else was tested end-to-end for real: the live FastAPI
server was started and hit with real HTTP requests (index → search →
results → CSV export → history), and each source's network call is mocked
in the test suite (`tests/test_pipeline.py`, `tests/test_reddit.py`) while
running through the exact same scoring/storage/merge code as the real
thing — including a regression test for the multi-source score-merging
logic (`test_multi_source_merge_combines_scores_instead_of_dropping_one`).
When you run this locally with normal internet access, `pytrends` and the
Reddit client will make real calls — you may still see occasional Trends
429s (see above), which the retry/cache logic is built to absorb.

## Requirements

- Python 3.11+
- Internet access (for the Google Trends and Reddit calls)
- Optional: a Reddit "script" app (`REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`)
  if you want Reddit signals — Google Trends alone needs no credentials.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in REDDIT_CLIENT_ID/SECRET if you want Reddit signals
```

Get a Reddit client id/secret at https://www.reddit.com/prefs/apps → create
app → type "script". Without these, Reddit is skipped automatically and
you still get full Google Trends results.

## Run it

```bash
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000, enter a niche (e.g. "cocina" or
"mascotas"), and submit. The first search for a niche can take a few
seconds to a couple of minutes if Google Trends rate-limits and the app
has to back off and retry; subsequent searches for the same niche within
the cache TTL (12h by default) load instantly from cache.

## How scoring works

Documented in full in `app/scoring.py`. Short version: for each term's
90-day daily interest series,

- **growth_pct** compares the first week of the window to the last week
  (did this trend up over ~3 months?).
- **momentum_pct** compares the last week to the whole 90-day average (is
  this spiking recently, even if the longer trend looks flat?).
- The two are blended (60% growth, 40% momentum) into a single 0-100
  score.

This is intentionally simple and inspectable — no hidden weights. Once
Reddit / Meta Ads / TikTok are wired up, `combine_source_scores()` blends
each source's own 0-100 score using the weights in `SOURCE_WEIGHTS`,
renormalized over whichever sources actually returned data.

## Data & history

Every search is saved to a local SQLite database (`data/dashboard.db` by
default, gitignored). Running the same niche again later shows a
week-over-week score delta per term next to the current results, and
lists all past runs for that niche so you can track how a niche is
trending over time.

## Exporting

Every results page has an **Export CSV** button
(`/export/{run_id}.csv`) with the full prioritized term list: score,
growth %, momentum %, average interest, competition estimate (currently
`N/A` until Meta Ads Library is wired up), and the ad-inspection link.

## Project layout

```
app/
  main.py              FastAPI routes
  config.py            Environment-driven settings (all future API keys live here)
  db.py                SQLite schema + queries
  scoring.py            Demand-signal scoring, documented and extensible
  cache.py              Disk cache used by rate-limited sources
  export.py             CSV export
  sources/
    base.py             SignalSource interface + shared ads_library_url() helper
    google_trends.py     Implemented
    reddit.py             Implemented
    meta_ads.py            Stub — integration plan in the docstring
    tiktok.py               Stub — integration plan in the docstring
    amazon.py                 Manual link only, by design (ToS)
  templates/            Jinja2 templates (Chart.js for the trend chart)
  static/                CSS
tests/
  test_scoring.py        Unit tests for the scoring formulas
  test_reddit.py           Reddit source unit tests (token caching, bucketing)
  test_pipeline.py           Full pipeline test through the real FastAPI app,
                              including the multi-source score-merge behavior
```

## Running the tests

```bash
pytest
```

## Adding the next source (Meta Ads or TikTok)

1. Fill in the credentials in `.env` (see `.env.example`).
2. Implement `fetch_signals()` in the corresponding module under
   `app/sources/` — the integration plan and rate-limit numbers are
   already in that file's docstring.
3. Add the source instance to `ACTIVE_SOURCES` in `app/main.py`, and give
   it a position in `PRIMARY_SOURCE_PRIORITY` (where it should rank when
   it shares a term with another source).

Nothing else needs to change: `run_search()` already loops over every
configured, implemented source, merges signals per term (combining scores
via `scoring.combine_source_scores()` even when multiple sources report
the same term), and the results page/CSV already show which sources
contributed to each row.
