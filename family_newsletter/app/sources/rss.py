from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from xml.etree import ElementTree

import httpx

MEDIA_NS = "{http://search.yahoo.com/mrss/}"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
IMG_TAG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 family-newsletter/0.1"
)


def _text(element: ElementTree.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return unescape(element.text.strip())


def _normalize_image_url(url: str, max_dimension: int = 240) -> str:
    """Cap oversized CDN-resizer dimensions so mail image proxies don't skip
    multi-megabyte images. Gmail's proxy refuses very large images; some feeds
    (e.g. Arc/arcpublishing resizer) hand out 5000px+, multi-MB originals whose
    ``auth`` token does NOT cover width/height, so shrinking them is safe."""
    if not url or "arcpublishing.com/resizer" not in url:
        return url

    def _cap(match: re.Match[str]) -> str:
        return f"{match.group(1)}={min(int(match.group(2)), max_dimension)}"

    return re.sub(r"(width|height)=(\d+)", _cap, url)


def _image_url(item: ElementTree.Element) -> str:
    thumbnail = item.find(f"{MEDIA_NS}thumbnail")
    if thumbnail is not None and thumbnail.get("url"):
        return _normalize_image_url(thumbnail.get("url", ""))

    for content in item.findall(f"{MEDIA_NS}content"):
        medium = content.get("medium", "")
        url = content.get("url", "")
        if url and (medium == "image" or content.get("type", "").startswith("image/")):
            return _normalize_image_url(url)

    enclosure = item.find("enclosure")
    if enclosure is not None and enclosure.get("type", "").startswith("image/"):
        return _normalize_image_url(enclosure.get("url", ""))

    description = _text(item.find("description"))
    match = IMG_TAG_RE.search(description)
    if match:
        return _normalize_image_url(match.group(1))

    return ""


def _published_at(item: ElementTree.Element) -> str:
    for tag in (
        "pubDate",
        "{http://purl.org/dc/elements/1.1/}date",
        f"{ATOM_NS}published",
        f"{ATOM_NS}updated",
    ):
        raw = _text(item.find(tag))
        if not raw:
            continue
        try:
            return parsedate_to_datetime(raw).isoformat()
        except (TypeError, ValueError):
            return raw
    return ""


def _entry_link(item: ElementTree.Element) -> str:
    """Link from RSS (<link> text) or Atom (<link href> preferring alternate)."""
    rss_link = _text(item.find("link"))
    if rss_link:
        return rss_link
    fallback = ""
    for link in item.findall(f"{ATOM_NS}link"):
        href = link.get("href", "")
        if not href:
            continue
        if link.get("rel", "alternate") == "alternate":
            return href
        fallback = fallback or href
    return fallback


def _entry_title(item: ElementTree.Element) -> str:
    return _text(item.find("title")) or _text(item.find(f"{ATOM_NS}title"))


def _entry_summary(item: ElementTree.Element) -> str:
    return (
        _text(item.find("description"))
        or _text(item.find(f"{ATOM_NS}summary"))
        or _text(item.find(f"{ATOM_NS}content"))
    )


def _fetch_feed(client: httpx.Client, feed_url: str, retries: int = 1) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.get(feed_url)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.75 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def _published_sort_value(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def fetch_rss_headlines(feeds: list[str], limit: int = 6) -> dict[str, Any]:
    all_headlines: list[dict[str, str]] = []
    statuses: list[dict[str, str]] = []
    seen: set[str] = set()

    headers = {"User-Agent": BROWSER_UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8"}
    with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers) as client:
        for feed_url in feeds:
            try:
                response = _fetch_feed(client, feed_url, retries=2)
                root = ElementTree.fromstring(response.content)
            except (httpx.HTTPError, ElementTree.ParseError) as exc:
                statuses.append({"source_url": feed_url, "status": "failed", "detail": str(exc)})
                continue

            channel = root.find("channel")
            if channel is not None:
                source_name = _text(channel.find("title")) or feed_url
                items = root.findall("./channel/item") or root.findall(".//item")
            else:
                # Atom feed: <feed><entry>...
                source_name = _text(root.find(f"{ATOM_NS}title")) or feed_url
                items = root.findall(f"{ATOM_NS}entry")
                if not items:
                    items = root.findall(".//item")
            statuses.append({"source_url": feed_url, "status": "ok", "detail": f"{len(items)} item(s)"})

            for item in items:
                title = _entry_title(item)
                link = _entry_link(item)
                if not title or title.lower() in seen:
                    continue
                seen.add(title.lower())
                published_at = _published_at(item)
                all_headlines.append(
                    {
                        "title": title,
                        "link": link,
                        "source": source_name,
                        "published_at": published_at,
                        "summary": _entry_summary(item),
                        "image": _image_url(item),
                    }
                )

    # Sort by recency across all feeds first so a newer story from one feed
    # can't be buried behind older stories from another (previously a
    # round-robin selection surfaced stale items ahead of fresher ones).
    all_headlines.sort(key=lambda item: _published_sort_value(item["published_at"]), reverse=True)
    headlines = all_headlines[:limit]

    if headlines and any(status["status"] == "failed" for status in statuses):
        status = "partial"
    elif headlines:
        status = "ok"
    elif statuses:
        status = "empty"
    else:
        status = "failed"

    return {"status": status, "headlines": headlines, "sources": statuses}
