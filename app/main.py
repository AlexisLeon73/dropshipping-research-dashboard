from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db
from app.config import settings
from app.export import term_signals_to_csv
from app.scoring import combine_source_scores
from app.sources.base import SignalSource
from app.sources.google_trends import GoogleTrendsSource
from app.sources.meta_ads import MetaAdsSource
from app.sources.reddit import RedditSource

logging.basicConfig(level=logging.INFO)

# TikTok slots in here once implemented — nothing else in this file needs
# to change. Order matters for PRIMARY_SOURCE_PRIORITY below.
ACTIVE_SOURCES: list[SignalSource] = [GoogleTrendsSource(), RedditSource(), MetaAdsSource()]

# When more than one source reports the same term, its display fields
# (series/growth/momentum/ad link) come from whichever configured source
# ranks highest here — the score itself still blends every source that
# reported the term, via combine_source_scores.
PRIMARY_SOURCE_PRIORITY = ["google_trends", "reddit", "meta_ads", "tiktok"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Product Research Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def run_search(niche: str, max_terms: int) -> list[dict]:
    """Fetch signals from every configured+implemented source and combine
    them into one score per term.

    Different sources can report the same term (e.g. Google Trends,
    Reddit, and Meta Ads all report the bare niche term). When that
    happens, every source's score for that term feeds
    combine_source_scores() — nothing is silently dropped just because
    multiple sources agree on a term. Display fields that only make sense
    from one source (the 90-day series, growth/momentum, the
    ad-inspection link) come from whichever configured source ranks
    highest in PRIMARY_SOURCE_PRIORITY — except competition_estimate /
    competition_label / top_advertisers, which currently only Meta Ads
    ever fills in with real data, so those fields specifically come from
    Meta Ads whenever it reported the term, regardless of who "wins"
    otherwise.
    """
    per_term_scores: dict[str, dict[str, float]] = {}
    per_term_signals: dict[str, dict[str, dict]] = {}

    for source in ACTIVE_SOURCES:
        if not source.is_configured():
            logging.info("%s not configured, skipping", source.name)
            continue
        try:
            results = source.fetch_signals(niche, max_terms)
        except NotImplementedError:
            continue
        except Exception:
            logging.exception(
                "%s failed for niche=%r, skipping this source", source.name, niche
            )
            continue
        for signal in results:
            per_term_scores.setdefault(signal.term, {})[signal.source] = signal.score
            per_term_signals.setdefault(signal.term, {})[signal.source] = signal.as_dict()

    final_signals = []
    for term, sources_data in per_term_signals.items():
        primary_source = next(
            (s for s in PRIMARY_SOURCE_PRIORITY if s in sources_data),
            next(iter(sources_data)),
        )
        data = dict(sources_data[primary_source])
        data["score"] = combine_source_scores(per_term_scores[term])
        data["sources"] = sorted(sources_data.keys())

        # Competition data and top advertisers are currently only ever
        # supplied by Meta Ads Library — use them even when another
        # source won the primary slot.
        meta_ads_data = sources_data.get("meta_ads")
        if meta_ads_data and meta_ads_data.get("competition_estimate") is not None:
            data["competition_estimate"] = meta_ads_data["competition_estimate"]
            data["competition_label"] = meta_ads_data["competition_label"]
            data["top_advertisers"] = meta_ads_data.get("top_advertisers", [])

        final_signals.append(data)

    final_signals.sort(key=lambda s: s["score"], reverse=True)
    return final_signals


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    recent_runs = db.get_recent_runs(limit=15)
    return templates.TemplateResponse(
        request, "index.html", {"recent_runs": recent_runs}
    )


@app.post("/search")
def search(niche: str = Form(...)):
    niche = niche.strip()
    if not niche:
        return RedirectResponse(url="/", status_code=303)

    run_id = db.create_search_run(niche)
    signals = run_search(niche, settings.max_terms_per_search)
    for signal in signals:
        db.save_term_signal(run_id, signal)

    return RedirectResponse(url=f"/results/{run_id}", status_code=303)


@app.get("/results/{run_id}", response_class=HTMLResponse)
def results(request: Request, run_id: int):
    run = db.get_search_run(run_id)
    if run is None:
        return HTMLResponse("Search run not found", status_code=404)

    terms = db.get_term_signals(run_id)

    previous_run = db.get_previous_run(run["niche"], run_id)
    previous_scores: dict[str, float] = {}
    if previous_run is not None:
        for row in db.get_term_signals(previous_run["id"]):
            previous_scores[row["term"]] = row["score"]

    rows = []
    chart_series = {}
    for row in terms:
        delta = None
        if row["term"] in previous_scores:
            delta = round(row["score"] - previous_scores[row["term"]], 1)
        row_dict = dict(row)
        row_dict["top_advertisers"] = json.loads(row_dict.pop("top_advertisers_json") or "[]")
        rows.append({**row_dict, "score_delta": delta})
        chart_series[row["term"]] = json.loads(row["series_json"])

    other_runs = [r for r in db.get_runs_for_niche(run["niche"]) if r["id"] != run_id]

    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "run": run,
            "rows": rows,
            "chart_series_json": json.dumps(chart_series),
            "previous_run": previous_run,
            "other_runs": other_runs,
        },
    )


@app.get("/export/{run_id}.csv")
def export_csv(run_id: int):
    run = db.get_search_run(run_id)
    if run is None:
        return PlainTextResponse("Search run not found", status_code=404)
    terms = db.get_term_signals(run_id)
    csv_text = term_signals_to_csv(run["niche"], terms)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{run["niche"]}_{run_id}.csv"'
        },
    )
