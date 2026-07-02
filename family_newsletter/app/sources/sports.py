from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from family_newsletter.app.sources.rss import fetch_rss_headlines

USER_AGENT = "family-newsletter/0.1 backend-preview"

ESPN_SCHEDULE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_id}/schedule?season={season}"
)

ESPN_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={start}-{end}"
)

# Upcoming games to surface across all teams.
UPCOMING_LIMIT = 10
# Soonest games kept per team before merging into the cross-team list.
PER_TEAM_LIMIT = 3
# Upcoming World Cup matches to surface.
WORLD_CUP_LIMIT = 6
# How many days ahead of today to scan the World Cup scoreboard.
WORLD_CUP_DAYS = 5


def clean_google_news(result: dict[str, Any]) -> dict[str, Any]:
    """Move the publisher out of Google News titles ("Headline - Publisher") into the source byline.

    Google News RSS embeds the outlet name as a trailing " - Publisher" on each title and sets
    the feed source to "<query> - Google News". This rewrites those headlines in place so the
    byline shows the real outlet, leaving non-Google-News headlines untouched.
    """
    for item in result.get("headlines", []):
        source = item.get("source", "")
        if "Google News" not in source:
            continue
        title = item.get("title", "")
        headline, sep, publisher = title.rpartition(" - ")
        if sep and headline and publisher:
            item["title"] = headline
            item["source"] = publisher
        else:
            item["source"] = "Google News"
    return result


def _news_query_url(team_name: str, window: str) -> str:
    quoted = quote(f'"{team_name}" {window}')
    return f"https://news.google.com/rss/search?q={quoted}&hl=en-US&gl=US&ceid=US:en"


def _news_recency(item: dict[str, Any]) -> datetime:
    raw = item.get("published_at", "")
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _fetch_team_news(
    teams: list[dict[str, Any]], window: str, limit: int, per_team_pool: int = 3
) -> dict[str, Any]:
    """Fetch each team's Google News feed independently, then select with a recency-aware
    round-robin so every team is represented before any team gets a second headline.

    Pure global recency (the shared RSS merge) lets high-volume in-season teams crowd
    offseason teams out entirely — e.g. baseball in July burying the Bears. Here each team
    contributes its freshest item into the first round (ranked by recency), the next-freshest
    into the second round, and so on, until the cap is hit. Selection is fair; display order
    within the final set stays recency-first.
    """
    per_team: list[list[dict[str, str]]] = []
    statuses: list[dict[str, str]] = []

    for team in teams:
        name = str(team.get("name", "")).strip()
        if not name:
            continue
        result = clean_google_news(
            fetch_rss_headlines([_news_query_url(name, window)], limit=per_team_pool)
        )
        statuses.extend(result.get("sources", []))
        if result.get("headlines"):
            per_team.append(result["headlines"])

    if not per_team:
        return {"status": "empty" if statuses else "failed", "headlines": [], "sources": statuses}

    seen: set[str] = set()
    selected: list[dict[str, str]] = []
    max_rank = max(len(h) for h in per_team)
    for rank in range(max_rank):
        # One round = each team's rank-th freshest headline, ordered by recency
        # so scarce slots go to the freshest teams rather than list position.
        round_items = [h[rank] for h in per_team if rank < len(h)]
        round_items.sort(key=_news_recency, reverse=True)
        for item in round_items:
            key = item.get("title", "").lower()
            if key in seen:
                continue
            seen.add(key)
            selected.append(item)
            if len(selected) >= limit:
                break
        if len(selected) >= limit:
            break

    selected.sort(key=_news_recency, reverse=True)

    if selected and any(s.get("status") == "failed" for s in statuses):
        status = "partial"
    elif selected:
        status = "ok"
    else:
        status = "empty"
    return {"status": status, "headlines": selected, "sources": statuses}


def _parse_event_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_when(dt: datetime) -> str:
    # Human-readable date convention: "Thursday, July 2" — never a long-form timestamp.
    local = dt.astimezone()
    day = local.strftime("%A, %B %d").replace(" 0", " ")
    clock = local.strftime("%I:%M %p").lstrip("0")
    return f"{day} at {clock}"


def _extract_matchup(competition: dict[str, Any], team_name: str) -> dict[str, str]:
    competitors = competition.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)

    home_name = (home or {}).get("team", {}).get("displayName", "") if home else ""
    away_name = (away or {}).get("team", {}).get("displayName", "") if away else ""

    if not home_name and not away_name:
        return {"matchup": team_name, "home_away": ""}

    is_home = home_name == team_name
    opponent = away_name if is_home else home_name
    if is_home:
        return {"matchup": f"{team_name} vs {opponent}", "home_away": "home"}
    return {"matchup": f"{team_name} @ {opponent}", "home_away": "away"}


def _fetch_team_games(
    client: httpx.Client, team: dict[str, Any], season: int, now: datetime
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    name = str(team.get("name", "")).strip()
    sport = str(team.get("sport", "")).strip()
    league = str(team.get("league", "")).strip()
    team_id = str(team.get("team_id", "")).strip()

    label = f"{name} ({sport}/{league}/{team_id})"
    if not (name and sport and league and team_id):
        return [], {"team": name or label, "status": "failed", "detail": "incomplete team config"}

    url = ESPN_SCHEDULE_URL.format(sport=sport, league=league, team_id=team_id, season=season)
    try:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return [], {"team": label, "status": "failed", "detail": str(exc)}

    events = data.get("events", []) or []
    upcoming: list[dict[str, Any]] = []
    for event in events:
        event_dt = _parse_event_date(event.get("date", ""))
        if event_dt is None or event_dt <= now:
            continue
        competitions = event.get("competitions", [])
        competition = competitions[0] if competitions else {}
        matchup = _extract_matchup(competition, name)
        link = ""
        for link_entry in event.get("links", []) or []:
            if link_entry.get("href"):
                link = link_entry["href"]
                break
        upcoming.append(
            {
                "team": name,
                "league": league.upper(),
                "matchup": matchup["matchup"],
                "home_away": matchup["home_away"],
                "when": _format_when(event_dt),
                "sort_key": event_dt,
                "link": link,
            }
        )

    upcoming.sort(key=lambda g: g["sort_key"])
    detail = f"{len(upcoming)} upcoming" if upcoming else "no upcoming games"
    return upcoming[:PER_TEAM_LIMIT], {"team": label, "status": "ok", "detail": detail}


def _fetch_games(teams: list[dict[str, Any]], season: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    all_games: list[dict[str, Any]] = []
    statuses: list[dict[str, str]] = []

    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=True
    ) as client:
        for team in teams:
            games, status = _fetch_team_games(client, team, season, now)
            all_games.extend(games)
            statuses.append(status)

    all_games.sort(key=lambda g: g["sort_key"])
    games = all_games[:UPCOMING_LIMIT]
    for game in games:
        game.pop("sort_key", None)

    any_failed = any(s["status"] == "failed" for s in statuses)
    if games and any_failed:
        status = "partial"
    elif games:
        status = "ok"
    elif statuses and any_failed and not any(s["status"] == "ok" for s in statuses):
        status = "failed"
    else:
        status = "empty"

    return {"status": status, "games": games, "sources": statuses}


def _format_stage(slug: str) -> str:
    if not slug:
        return ""
    words = slug.replace("-", " ").split()
    small = {"of", "the", "and"}
    return " ".join(
        w if (i and w in small) else w.capitalize() for i, w in enumerate(words)
    )


def _fetch_world_cup_matches(league: str, days: int, run_date: date, now: datetime) -> dict[str, Any]:
    start = run_date.strftime("%Y%m%d")
    end = (run_date + timedelta(days=days)).strftime("%Y%m%d")
    url = ESPN_SCOREBOARD_URL.format(league=league, start=start, end=end)

    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=True
    ) as client:
        try:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "failed", "matches": [], "detail": str(exc)}

    events = data.get("events", []) or []
    matches: list[dict[str, Any]] = []
    for event in events:
        competitions = event.get("competitions", [])
        competition = competitions[0] if competitions else {}
        state = competition.get("status", {}).get("type", {}).get("state", "")
        # Skip finished matches; keep upcoming ("pre") and in-progress ("in").
        if state == "post":
            continue

        event_dt = _parse_event_date(event.get("date", ""))
        if event_dt is None:
            continue

        competitors = competition.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        home_name = (home or {}).get("team", {}).get("displayName", "")
        away_name = (away or {}).get("team", {}).get("displayName", "")
        if home_name and away_name:
            matchup = f"{home_name} vs {away_name}"
        else:
            matchup = event.get("name", "")

        link = ""
        for link_entry in event.get("links", []) or []:
            if link_entry.get("href"):
                link = link_entry["href"]
                break

        matches.append(
            {
                "matchup": matchup,
                "stage": _format_stage((event.get("season") or {}).get("slug", "")),
                "when": _format_when(event_dt),
                "live": state == "in",
                "sort_key": event_dt,
                "link": link,
            }
        )

    matches.sort(key=lambda m: m["sort_key"])
    matches = matches[:WORLD_CUP_LIMIT]
    for match in matches:
        match.pop("sort_key", None)

    status = "ok" if matches else "empty"
    return {"status": status, "matches": matches, "detail": f"{len(matches)} matches"}


def fetch_world_cup(config: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Assemble upcoming World Cup matches (ESPN) and top headlines (Google News)."""
    if not config or not config.get("enabled", True):
        return {
            "status": "placeholder",
            "matches": [],
            "news": {"status": "placeholder", "headlines": [], "sources": []},
        }

    league = str(config.get("league", "fifa.world"))
    days = int(config.get("days", WORLD_CUP_DAYS))
    news_query = str(config.get("news_query", "FIFA World Cup"))
    news_limit = int(config.get("news_limit", 3))
    news_window = str(config.get("news_window", "when:1d"))
    run_date = today or date.today()
    now = datetime.now(timezone.utc)

    match_result = _fetch_world_cup_matches(league, days, run_date, now)

    news_feeds = [_news_query_url(news_query, news_window)]
    news = clean_google_news(fetch_rss_headlines(news_feeds, limit=news_limit))

    if match_result["status"] == "ok" or news["status"] in ("ok", "partial"):
        status = "ok"
    elif match_result["status"] == "empty" and news["status"] == "empty":
        status = "empty"
    else:
        status = "failed"

    return {"status": status, "matches": match_result["matches"], "news": news}


def fetch_sports(config: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Assemble team news (Google News) and upcoming games (ESPN) for the sports card."""
    if not config or not config.get("enabled", True):
        return {
            "status": "placeholder",
            "news": {"status": "placeholder", "headlines": [], "sources": []},
            "games": {"status": "placeholder", "games": [], "sources": []},
            "world_cup": {"status": "placeholder", "matches": [], "news": {"status": "placeholder", "headlines": [], "sources": []}},
        }

    teams = [t for t in config.get("teams", []) if isinstance(t, dict)]
    window = str(config.get("news_window", "when:2d"))
    news_limit = int(config.get("news_limit", 8))
    run_date = today or date.today()
    season = int(config.get("season", run_date.year))

    if any(team.get("name") for team in teams):
        news = _fetch_team_news(teams, window, news_limit)
    else:
        news = {"status": "empty", "headlines": [], "sources": []}

    games = _fetch_games(teams, season)

    wc_config = config.get("world_cup", {})
    if isinstance(wc_config, dict) and wc_config.get("enabled", True):
        world_cup = fetch_world_cup(wc_config, today=run_date)
    else:
        world_cup = {
            "status": "placeholder",
            "matches": [],
            "news": {"status": "placeholder", "headlines": [], "sources": []},
        }

    section_states = [news["status"], games["status"]]
    if world_cup["status"] != "placeholder":
        section_states.append(world_cup["status"])
    if any(s in ("ok", "partial") for s in section_states):
        status = "ok"
    elif all(s == "empty" for s in section_states):
        status = "empty"
    else:
        status = "failed"

    return {"status": status, "news": news, "games": games, "world_cup": world_cup}
