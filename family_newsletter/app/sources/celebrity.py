from __future__ import annotations

from typing import Any

from family_newsletter.app.sources.rss import fetch_rss_headlines
from family_newsletter.app.sources.sports import clean_google_news

DEFAULT_LIMIT = 6


def fetch_celebrity(config: dict[str, Any]) -> dict[str, Any]:
    """Assemble the celebrity / entertainment headlines card.

    Reuses the shared RSS fetcher (cross-feed title dedupe + recency sort) and the
    Google News byline cleanup so headlines show the real outlet rather than
    "<query> - Google News".
    """
    if not config or not config.get("enabled", True):
        return {"status": "placeholder", "headlines": [], "sources": []}

    feeds = [str(feed) for feed in config.get("feeds", [])]
    if not feeds:
        return {"status": "empty", "headlines": [], "sources": []}

    limit = int(config.get("limit", DEFAULT_LIMIT))
    return clean_google_news(fetch_rss_headlines(feeds, limit=limit))
