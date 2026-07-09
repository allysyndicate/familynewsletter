from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader

from family_newsletter.app.config import PROJECT_ROOT, Settings, load_yaml_config
from family_newsletter.app.sources.celebrity import fetch_celebrity
from family_newsletter.app.sources.chores import fetch_chores
from family_newsletter.app.sources.rss import fetch_rss_headlines
from family_newsletter.app.sources.sports import fetch_sports
from family_newsletter.app.sources.weather import fetch_weather


TEMPLATE_DIR = Path(__file__).parent / "templates"

# The daily edition is a Pacific-morning artifact. GitHub Actions runs in UTC,
# so date.today() there can read as the *next* day and drift the chore weekday.
# Anchor the edition date to America/Los_Angeles so the weekday is always the
# recipient's local day.
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def pacific_today() -> date:
    return datetime.now(PACIFIC_TZ).date()


def _long_date(value: date) -> str:
    """Human-readable long date, e.g. 'Thursday, July 2, 2026' (no leading zero)."""
    return f"{value.strftime('%A')}, {value.strftime('%B')} {value.day}, {value.year}"


def _friendly_datetime(value: datetime) -> str:
    """Human-readable date + 12-hour time, e.g. 'July 2, 2026 at 3:42 PM'."""
    hour12 = value.strftime("%I").lstrip("0") or "12"
    return f"{value.strftime('%B')} {value.day}, {value.year} at {hour12}:{value.strftime('%M %p')}"


def _human_date_filter(value: str) -> str:
    """Jinja filter: turn an ISO date/timestamp into 'July 2, 2026'.

    Falls back to the original string if it can't be parsed so we never crash
    on an unexpected feed date format.
    """
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return value
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def _autoescape(template_name: str | None) -> bool:
    # Templates are named e.g. "newsletter.html.j2", so the trailing ".j2"
    # extension hides ".html" from select_autoescape's suffix check and leaves
    # HTML escaping OFF. Match ".html"/".xml" anywhere in the name so feed text
    # containing quotes/angle-brackets can't break attributes or markup. The
    # ".txt.j2" plain-text template stays unescaped (correct — no entities).
    return bool(template_name) and (".html" in template_name or ".xml" in template_name)


def _template_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=_autoescape,
    )
    env.filters["human_date"] = _human_date_filter
    return env


def _household(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("household", {})


def _weather_config(config: dict[str, Any]) -> dict[str, Any]:
    household = _household(config)
    weather = dict(config.get("weather", {}))
    weather.setdefault("latitude", household.get("latitude"))
    weather.setdefault("longitude", household.get("longitude"))
    weather.setdefault("location", f"{household.get('city', 'Wilsonville')}, {household.get('state', 'OR')} {household.get('zip', '97070')}")
    return weather


def build_preview_context(settings: Settings, newsletter_date: date | None = None) -> dict[str, Any]:
    config = load_yaml_config(settings.config_file)
    run_date = newsletter_date or pacific_today()
    news_config = config.get("news", {})
    local_feeds = [str(feed) for feed in news_config.get("local_feeds", [])]
    global_feeds = [str(feed) for feed in news_config.get("global_feeds", [])]
    ai_feeds = [str(feed) for feed in news_config.get("ai_feeds", [])]

    weather = fetch_weather(_weather_config(config))
    local_news = fetch_rss_headlines(local_feeds, limit=6)
    global_news = fetch_rss_headlines(global_feeds, limit=5)
    ai_news = fetch_rss_headlines(ai_feeds, limit=5)
    chores = fetch_chores(config.get("chores", {}), run_date)

    sports = fetch_sports(config.get("sports", {}), run_date)
    celebrity = fetch_celebrity(config.get("celebrity", {}))

    household = _household(config)
    subject = f"{household.get('name', 'Family')} Morning Brief - {_long_date(run_date)}"

    real_fields = ["household ZIP/city", "NWS weather"]
    placeholder_fields = ["toddler schedule", "email recipients"]
    for label, source in (
        ("local RSS headlines", local_news),
        ("global RSS headlines", global_news),
        ("AI update RSS headlines", ai_news),
    ):
        if source["status"] in ("ok", "partial"):
            real_fields.append(label)
        else:
            placeholder_fields.append(label)

    if chores["status"] == "ok":
        real_fields.append("chores")
    else:
        placeholder_fields.append("chores")

    if sports["status"] in ("ok", "partial"):
        real_fields.append("sports")
    else:
        placeholder_fields.append("sports")

    if celebrity["status"] in ("ok", "partial"):
        real_fields.append("celebrity news")
    else:
        placeholder_fields.append("celebrity news")

    return {
        "subject": subject,
        "generated_at": _friendly_datetime(datetime.now(PACIFIC_TZ)),
        "newsletter_date": run_date.isoformat(),
        "newsletter_date_display": _long_date(run_date),
        "household": household,
        "weather": weather,
        "local_news": local_news,
        "global_news": global_news,
        "ai_news": ai_news,
        "schedule": {
            "status": "placeholder",
            "items": ["Toddler schedule source is not configured yet."],
        },
        "chores": chores,
        "sports": sports,
        "celebrity": celebrity,
        "field_status": {
            "real": real_fields,
            "placeholder": placeholder_fields,
        },
    }


def render_preview(context: dict[str, Any]) -> dict[str, str]:
    env = _template_env()
    return {
        "subject": context["subject"],
        "html": env.get_template("newsletter.html.j2").render(**context),
        "text": env.get_template("newsletter.txt.j2").render(**context),
    }


def write_preview_files(rendered: dict[str, str], newsletter_date: str) -> dict[str, str]:
    preview_dir = PROJECT_ROOT / "data" / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    html_path = preview_dir / f"{newsletter_date}.html"
    text_path = preview_dir / f"{newsletter_date}.txt"
    html_path.write_text(rendered["html"], encoding="utf-8")
    text_path.write_text(rendered["text"], encoding="utf-8")
    return {"html_path": str(html_path), "text_path": str(text_path)}
