"""Amazon Movers & Shakers — intentionally NOT automated.

Amazon has no public API for this data, and scraping amazon.com violates
its Terms of Service. Rather than automate around that, this module only
generates a direct link for manual inspection — the same "trust but
verify by hand" treatment the ad-library links get elsewhere in the app.

Movers & Shakers is organized by fixed Amazon departments, not by search
term, so there's no reliable way to deep-link a free-text niche into it
without guessing a category mapping — the link is deliberately the same
generic page every time; browsing to the right department is on you.
"""
from __future__ import annotations

MOVERS_AND_SHAKERS_URL = "https://www.amazon.com/gp/movers-and-shakers"


def manual_link() -> str:
    return MOVERS_AND_SHAKERS_URL
