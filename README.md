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

**Google Trends, Reddit, and Meta Ads Library are implemented.** TikTok
and Amazon Movers & Shakers are intentionally not: see below.

| Source | Status | Notes |
|---|---|---|
| Google Trends | ✅ Implemented | No API key. Unofficial (scrapes trends.google.com via `pytrends`), rate-limits hard. This is the **discovery** layer — finds candidate terms. |
| Reddit | ✅ Implemented | Official OAuth2 API (client_credentials grant), needs `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`. Has no "related terms" feature of its own, so it's queried once per term Google Trends discovers — see below. |
| Meta Ads Library | ✅ Implemented | Official Ad Library API (`ads_archive`), needs `META_ACCESS_TOKEN`. This is the **validation** layer — see below. Also queried once per Trends-discovered term, not just the bare niche. |
| TikTok | ⏸️ Paused, stub only | No public API; the only option is reverse-engineering TikTok Creative Center's undocumented internal endpoints, which can't be verified without live access to the site. Decided this wasn't worth the risk of shipping code that silently doesn't work — effort went into Meta Ads Library instead, which is the stronger buy-signal anyway. The stub and integration notes are still in `app/sources/tiktok.py` if you want to pick it up later with real browser devtools access. |
| Amazon Movers & Shakers | 🔗 Manual link only | No public API; scraping amazon.com violates its ToS, so this is intentionally not automated — a "Check Amazon Movers & Shakers ↗" button on every results page links to it for manual browsing instead. |

### Why Meta Ads Library is the priority, not just another source

For dropshipping specifically, "someone is running paid ads for this right
now" is a stronger signal than search interest or discussion volume —
it means a real advertiser is spending real money on it, today. So Meta
Ads Library isn't just a fourth data point: it's the **validation** step
after Google Trends' **discovery** step. Concretely, for every term it
covers, Meta Ads Library reports:

- `competition_estimate`: how many active ads are currently running for
  the term (a real number, not a proxy).
- `top_advertisers`: the actual Page names running those ads, ranked by
  how many ads they have active, each linked to one of their real ads via
  `ad_snapshot_url` — so instead of a bare count you get "here's who's
  doing it, go look at what they're selling and how."

### Discovery vs. per-term sources

Sources split into two kinds (`SignalSource.per_term` in
`app/sources/base.py`):

- **Discovery** (`per_term = False`, only Google Trends today): runs once
  against the bare niche and discovers the candidate term list itself, via
  Trends' related-queries feature.
- **Per-term** (`per_term = True`: Reddit, Meta Ads, and the TikTok stub):
  these have no "related terms" feature of their own — given one term,
  that's the only term they know how to look up. `run_search()` in
  `app/main.py` calls a per-term source once for **each** term Google
  Trends discovered, not just the bare niche, so competition data and top
  advertisers end up covering every candidate term Trends surfaces (e.g.
  "cocina organizador", not only "cocina" itself). If no discovery source
  produced anything (Trends unconfigured, rate-limited, or just not
  running), per-term sources fall back to querying the bare niche alone,
  same as before this existed.

### How multiple sources combine on the same term

Because of the above, multiple sources will often report the very same
term (most reliably the bare niche, which every source touches one way or
another). When that happens, `run_search()` folds every source's score
for that term into `combine_source_scores()` — nothing is silently
dropped just because multiple sources agree on a term. The 90-day chart,
growth/momentum numbers, and ad-inspection link still come from a single
"primary" source per term, ranked by `PRIMARY_SOURCE_PRIORITY` (Google
Trends first, since its series has real daily granularity). The
**Competition** and **Top advertisers** columns are the exception: since
Meta Ads is currently the only source that ever fills them with real
data, those fields specifically come from Meta Ads whenever it reported
the term, regardless of which source won the primary slot for everything
else. The **Sources** column on the results page and in the CSV export
always lists every source that contributed to that row's score.

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
etc.). That means the actual live calls to `trends.google.com`, Reddit's
API, and the Meta Graph API could not be exercised here — a real run there
returns a `ProxyError`/403, which is this sandbox's network policy, not a
bug in the code. Everything else was tested end-to-end for real: the live
FastAPI server was started and hit with real HTTP requests (index → search
→ results → CSV export → history), and each source's network call is
mocked in the test suite (`tests/test_pipeline.py`, `tests/test_reddit.py`,
`tests/test_meta_ads.py`) while running through the exact same
scoring/storage/merge code as the real thing — including regression tests
for the multi-source merge logic
(`test_multi_source_merge_combines_scores_instead_of_dropping_one`,
`test_meta_ads_competition_data_wins_even_when_trends_is_primary`) and for
the discovery/per-term orchestration
(`test_per_term_sources_are_queried_once_per_discovered_term`,
`test_per_term_sources_fall_back_to_bare_niche_when_no_discovery_source_available`).
When you run this locally with normal internet access, `pytrends`, the
Reddit client, and the Meta Graph API client will make real calls — you
may still see occasional Trends 429s (see above), which the retry/cache
logic is built to absorb.

## Requirements

- Python 3.11+
- Internet access (for the Google Trends, Reddit, and Meta Ads calls)
- Optional: a Reddit "script" app (`REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`)
  and/or a Meta app with Ad Library API access (`META_ACCESS_TOKEN`) —
  Google Trends alone needs no credentials, and any source without its
  credentials is skipped automatically.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in REDDIT_ / META_ credentials if you want those signals
```

- Reddit: create a "script" app at https://www.reddit.com/prefs/apps to get
  `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`.
- Meta Ads Library: create an app at https://developers.facebook.com with
  Ad Library API access to get `META_ACCESS_TOKEN`.

Without either, that source is skipped automatically and you still get
full results from whatever's configured.

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

This is intentionally simple and inspectable — no hidden weights. Reddit
and Meta Ads scores are computed the same way from their own volume series
(posts per day, ads started per day); `combine_source_scores()` blends
whichever sources reported a given term using the weights in
`SOURCE_WEIGHTS`, renormalized over just those sources.

## Data & history

Every search is saved to a local SQLite database (`data/dashboard.db` by
default, gitignored). Running the same niche again later shows a
week-over-week score delta per term next to the current results, and
lists all past runs for that niche so you can track how a niche is
trending over time.

The schema has grown as sources were added (`sources`,
`top_advertisers_json`). `init_db()` adds any missing columns to an
existing `data/dashboard.db` automatically on startup — you don't need to
delete it between updates.

## Exporting

Every results page has an **Export CSV** button
(`/export/{run_id}.csv`) with the full prioritized term list: score,
contributing sources, growth %, momentum %, average interest, competition
estimate, top advertisers (page names + ad counts, from Meta Ads Library
when configured, blank otherwise), and the ad-inspection link.

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
    meta_ads.py            Implemented
    tiktok.py                Stub — integration plan in the docstring
    amazon.py                  Manual link only, by design (ToS)
  templates/            Jinja2 templates (Chart.js for the trend chart)
  static/                CSS
tests/
  test_scoring.py        Unit tests for the scoring formulas
  test_reddit.py           Reddit source unit tests (token caching, bucketing)
  test_meta_ads.py           Meta Ads source unit tests (pagination, bucketing,
                              top-advertisers aggregation)
  test_db_migration.py         Regression test for the term_signals column
                                migrations (old DB -> new schema, in place)
  test_pipeline.py                Full pipeline test through the real FastAPI
                                   app: multi-source score-merge, and the
                                   discovery/per-term orchestration
```

## Running the tests

```bash
pytest
```

## Adding the next source (TikTok)

1. Fill in the credentials in `.env` (see `.env.example`).
2. Implement `fetch_signals()` in the corresponding module under
   `app/sources/` — the integration plan and rate-limit numbers are
   already in that file's docstring. `per_term` is already set to `True`
   on `TikTokSource` (Creative Center's Keyword Insights is a
   single-keyword lookup, same as Reddit/Meta Ads) — leave it as-is
   unless the implementation actually discovers its own related terms.
3. Add the source instance to `ACTIVE_SOURCES` in `app/main.py`, and give
   it a position in `PRIMARY_SOURCE_PRIORITY` (where it should rank when
   it shares a term with another source).

Nothing else needs to change: `run_search()` already loops over every
configured, implemented source — calling per_term sources once per
Trends-discovered term automatically — merges signals per term (combining
scores via `scoring.combine_source_scores()` even when multiple sources
report the same term), and the results page/CSV already show which
sources contributed to each row.
