"""Central place for environment-driven settings.

Every source module reads its own credentials from here so that adding
Reddit / Meta Ads / TikTok later means filling in a few fields, not
touching the rest of the app.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    # Google Trends
    google_trends_hl: str = os.getenv("GOOGLE_TRENDS_HL", "en-US")
    google_trends_geo: str = os.getenv("GOOGLE_TRENDS_GEO", "")
    google_trends_cache_ttl_hours: float = float(
        os.getenv("GOOGLE_TRENDS_CACHE_TTL_HOURS", "12")
    )
    # Google's own category id to restrict results to. 18 = Shopping —
    # this cuts a lot of off-topic noise (news, pop culture, sports) that
    # a broad niche word like "mascotas" would otherwise pull in (e.g. World
    # Cup mascots). 0 = all categories, for niches where that noise doesn't
    # matter or you want the broadest possible related-terms list.
    google_trends_category: int = int(os.getenv("GOOGLE_TRENDS_CATEGORY", "18"))

    # Reddit
    reddit_client_id: str = os.getenv("REDDIT_CLIENT_ID", "")
    reddit_client_secret: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    reddit_user_agent: str = os.getenv(
        "REDDIT_USER_AGENT", "product-research-dashboard/0.1"
    )
    reddit_cache_ttl_hours: float = float(os.getenv("REDDIT_CACHE_TTL_HOURS", "6"))

    # Meta Ads Library
    meta_access_token: str = os.getenv("META_ACCESS_TOKEN", "")
    # JSON-array string, as the Graph API expects it, e.g. '["US","MX"]'.
    meta_ad_reached_countries: str = os.getenv("META_AD_REACHED_COUNTRIES", '["US"]')
    meta_cache_ttl_hours: float = float(os.getenv("META_CACHE_TTL_HOURS", "6"))

    # App
    db_path: str = os.getenv("DB_PATH", "data/dashboard.db")
    max_terms_per_search: int = int(os.getenv("MAX_TERMS_PER_SEARCH", "10"))
    cache_dir: str = os.getenv("CACHE_DIR", "data/cache")


settings = Settings()
