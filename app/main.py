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

logging.basicConfig(level=logging.INFO)

# Only Google Trends is wired up today. Reddit / Meta Ads / TikTok slot in
# here once implemented — nothing else in this file needs to change.
ACTIVE_SOURCES: list[SignalSource] = [GoogleTrendsSource()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Product Research Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def run_search(niche: str, max_terms: int) -> list[dict]:
    """Fetch signals from every configured+implemented source and combine
    them into one score per term. Today there's only one source, so this
    is mostly a pass-through — the merge point is here so wiring up a
    second source later doesn't touch the routes below.
    """
    signals_by_term: dict[str, dict] = {}
    for source in ACTIVE_SOURCES:
        if not source.is_configured():
            logger_msg = f"{source.name} not configured, skipping"
            logging.info(logger_msg)
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
            signals_by_term.setdefault(signal.term, signal.as_dict())

    final_signals = []
    for term, data in signals_by_term.items():
        data["score"] = combine_source_scores({data["source"]: data["score"]})
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
        rows.append({**dict(row), "score_delta": delta})
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
