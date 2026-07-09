from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx


USER_AGENT = "family-newsletter/0.1 backend-preview"

DAILY_FORECAST_DAYS = 7


def _condition_icon(short_forecast: str) -> str:
    text = (short_forecast or "").lower()
    if "thunder" in text:
        return "⛈️"
    if "snow" in text or "sleet" in text:
        return "❄️"
    if "rain" in text or "shower" in text or "drizzle" in text:
        return "🌧️"
    if "fog" in text or "haze" in text or "mist" in text:
        return "🌫️"
    if "partly" in text and "cloud" in text:
        return "⛅"
    if "cloud" in text or "overcast" in text:
        return "☁️"
    if "wind" in text:
        return "💨"
    if "clear" in text or "sunny" in text:
        return "☀️"
    return "🌤️"


def _hour_label(iso_time: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_time)
    except ValueError:
        return ""
    label = dt.strftime("%I %p").lstrip("0")
    return label or dt.strftime("%I %p")


def _build_hourly_slots(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One slot per remaining hour of today (no sampling)."""
    if not periods:
        return []

    try:
        anchor_date = datetime.fromisoformat(periods[0]["startTime"]).date()
    except (KeyError, ValueError):
        anchor_date = None

    if anchor_date is not None:
        todays_periods = []
        for period in periods:
            try:
                period_date = datetime.fromisoformat(period["startTime"]).date()
            except (KeyError, ValueError):
                continue
            if period_date == anchor_date:
                todays_periods.append(period)
    else:
        todays_periods = periods

    slots = []
    for period in todays_periods:
        precip = period.get("probabilityOfPrecipitation", {}) or {}
        slots.append(
            {
                "time_label": _hour_label(period.get("startTime", "")),
                "temperature": period.get("temperature"),
                "icon": _condition_icon(period.get("shortForecast", "")),
                "short_forecast": period.get("shortForecast", ""),
                "precip_chance": precip.get("value"),
            }
        )
    return slots


def _day_label(iso_time: str) -> str:
    try:
        return datetime.fromisoformat(iso_time).strftime("%a")
    except ValueError:
        return ""


def _build_daily_forecast(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair NWS day/night periods into up to 7 daily hi/lo cards."""
    days: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for period in periods:
        start = period.get("startTime", "")
        try:
            day_key = datetime.fromisoformat(start).date().isoformat()
        except ValueError:
            continue
        if day_key not in days:
            days[day_key] = {
                "day_label": _day_label(start),
                "icon": "",
                "short_forecast": "",
                "high": None,
                "low": None,
                "precip_chance": None,
            }
            order.append(day_key)
        entry = days[day_key]
        precip = (period.get("probabilityOfPrecipitation", {}) or {}).get("value")
        if precip is not None:
            entry["precip_chance"] = precip if entry["precip_chance"] is None else max(entry["precip_chance"], precip)
        temp = period.get("temperature")
        if period.get("isDaytime"):
            entry["high"] = temp
            entry["icon"] = _condition_icon(period.get("shortForecast", ""))
            entry["short_forecast"] = period.get("shortForecast", "")
        else:
            entry["low"] = temp
            if not entry["icon"]:
                entry["icon"] = _condition_icon(period.get("shortForecast", ""))
                entry["short_forecast"] = period.get("shortForecast", "")

    return [days[key] for key in order[:DAILY_FORECAST_DAYS]]


def _fetch_open_meteo_current(latitude: float, longitude: float) -> dict[str, Any] | None:
    """Real 'right now' observed-ish temperature from Open-Meteo (no API key)."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        "&current=temperature_2m&temperature_unit=fahrenheit"
    )
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15.0) as client:
            response = client.get(url)
            response.raise_for_status()
            current = response.json().get("current", {})
    except (httpx.HTTPError, ValueError):
        return None
    temp = current.get("temperature_2m")
    if temp is None:
        return None
    return {"temperature": temp, "temperature_unit": "F"}


def _sample_weather() -> dict[str, Any]:
    return {
        "status": "placeholder",
        "provider": "sample",
        "location": "Sample City",
        "summary": "Sample weather is enabled.",
        "temperature": None,
        "temperature_unit": "F",
        "high": None,
        "low": None,
        "details": "Configure `weather.provider: nws` plus latitude and longitude for real weather.",
        "source_url": "",
        "hourly": [],
        "daily": [],
    }


def fetch_weather(config: dict[str, Any]) -> dict[str, Any]:
    provider = str(config.get("provider", "sample")).lower()
    if provider != "nws":
        return _sample_weather()

    latitude = config.get("latitude")
    longitude = config.get("longitude")
    if latitude is None or longitude is None:
        return {
            **_sample_weather(),
            "status": "failed",
            "provider": "nws",
            "details": "NWS weather requires latitude and longitude.",
        }

    point_url = f"https://api.weather.gov/points/{latitude},{longitude}"
    hourly_periods: list[dict[str, Any]] = []
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=True) as client:
            point_response = client.get(point_url)
            point_response.raise_for_status()
            point_data = point_response.json()
            forecast_url = point_data["properties"]["forecast"]
            hourly_url = point_data["properties"].get("forecastHourly")

            forecast_response = client.get(forecast_url)
            forecast_response.raise_for_status()
            forecast_data = forecast_response.json()

            if hourly_url:
                try:
                    hourly_response = client.get(hourly_url)
                    hourly_response.raise_for_status()
                    hourly_periods = hourly_response.json().get("properties", {}).get("periods", [])
                except (httpx.HTTPError, ValueError):
                    hourly_periods = []
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        return {
            "status": "failed",
            "provider": "nws",
            "location": config.get("location", "ZIP 97070"),
            "summary": "Weather unavailable.",
            "temperature": None,
            "temperature_unit": "F",
            "high": None,
            "low": None,
            "details": str(exc),
            "source_url": point_url,
            "hourly": [],
            "daily": [],
        }

    periods = forecast_data.get("properties", {}).get("periods", [])
    if not periods:
        return {
            "status": "empty",
            "provider": "nws",
            "location": config.get("location", "ZIP 97070"),
            "summary": "NWS returned no forecast periods.",
            "temperature": None,
            "temperature_unit": "F",
            "high": None,
            "low": None,
            "details": "",
            "source_url": forecast_url,
            "hourly": [],
            "daily": [],
        }

    current = periods[0]
    next_period = periods[1] if len(periods) > 1 else None
    details = current.get("detailedForecast", "")
    if next_period:
        details = f"{details} Next: {next_period.get('name')}: {next_period.get('shortForecast')}."

    high = current.get("temperature") if current.get("isDaytime") else None
    low = None
    if next_period and not next_period.get("isDaytime"):
        low = next_period.get("temperature")
    elif not current.get("isDaytime"):
        low = current.get("temperature")

    # Headline temp should be a real "right now" reading. Prefer Open-Meteo's
    # observed-ish current temperature; fall back to the NWS hourly feed's
    # current hour, then the forecast period, if Open-Meteo is unavailable.
    current_hour = hourly_periods[0] if hourly_periods else current
    headline_temp = current_hour.get("temperature")
    headline_unit = current_hour.get("temperatureUnit", current.get("temperatureUnit", "F"))
    open_meteo = _fetch_open_meteo_current(latitude, longitude)
    if open_meteo is not None:
        headline_temp = open_meteo["temperature"]
        headline_unit = open_meteo["temperature_unit"]

    return {
        "status": "ok",
        "provider": "nws",
        "location": config.get("location", "Wilsonville, OR 97070"),
        "period": current.get("name", "Current"),
        "summary": current.get("shortForecast", "Forecast available"),
        "temperature": headline_temp,
        "temperature_unit": headline_unit,
        "high": high,
        "low": low,
        "details": details,
        "source_url": forecast_url,
        "hourly": _build_hourly_slots(hourly_periods),
        "daily": _build_daily_forecast(periods),
    }
