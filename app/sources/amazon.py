"""Amazon Movers & Shakers — intentionally NOT automated.

Amazon has no public API for this data, and scraping amazon.com violates
its Terms of Service. Rather than automate around that, this module only
generates a direct link for manual inspection — the same "trust but
verify by hand" treatment the ad-library links get elsewhere in the app.
"""
from __future__ import annotations

MOVERS_AND_SHAKERS_URL = "https://www.amazon.com/gp/movers-and-shakers"


def manual_link(category_hint: str | None = None) -> str:
    if not category_hint:
        return MOVERS_AND_SHAKERS_URL
    return MOVERS_AND_SHAKERS_URL
