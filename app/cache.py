"""Tiny on-disk JSON cache, keyed by an arbitrary string.

Google Trends has no official API and rate-limits hard (HTTP 429) after a
handful of requests. Caching every response we get, even for a few hours,
is the difference between the app being usable and being unusable.
"""
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.config import settings


def _cache_path(key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    cache_dir = Path(settings.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{digest}.json"


def get(key: str, ttl_hours: float) -> Any | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    age_hours = (time.time() - payload["cached_at"]) / 3600
    if age_hours > ttl_hours:
        return None
    return payload["data"]


def set(key: str, data: Any) -> None:
    path = _cache_path(key)
    payload = {"cached_at": time.time(), "data": data}
    path.write_text(json.dumps(payload))
