from fastapi.testclient import TestClient

import family_newsletter.app.newsletter.preview as preview
from family_newsletter.app.main import app


def test_preview_endpoint_writes_draft(monkeypatch, tmp_path):
    # Isolate file writes so the test never overwrites the real data/previews draft.
    def _write_to_tmp(rendered, newsletter_date):
        html_path = tmp_path / f"{newsletter_date}.html"
        text_path = tmp_path / f"{newsletter_date}.txt"
        html_path.write_text(rendered["html"], encoding="utf-8")
        text_path.write_text(rendered["text"], encoding="utf-8")
        return {"html_path": str(html_path), "text_path": str(text_path)}

    monkeypatch.setattr("family_newsletter.app.main.write_preview_files", _write_to_tmp)
    monkeypatch.setattr(
        preview,
        "fetch_weather",
        lambda _: {
            "status": "ok",
            "provider": "nws",
            "location": "Wilsonville, OR 97070",
            "summary": "Clear",
            "temperature": 72,
            "temperature_unit": "F",
            "high": 75,
            "low": 58,
            "details": "Mock forecast.",
            "source_url": "https://api.weather.gov/",
            "hourly": [
                {"time_label": "9 AM", "temperature": 65, "icon": "☀️", "short_forecast": "Sunny", "precip_chance": 10},
                {"time_label": "12 PM", "temperature": 72, "icon": "⛅", "short_forecast": "Partly Cloudy", "precip_chance": 20},
            ],
            "daily": [
                {"day_label": "Thu", "icon": "☀️", "short_forecast": "Sunny", "high": 75, "low": 58, "precip_chance": 10},
                {"day_label": "Fri", "icon": "🌧️", "short_forecast": "Rain", "high": 68, "low": 54, "precip_chance": 60},
            ],
        },
    )
    monkeypatch.setattr(
        preview,
        "fetch_rss_headlines",
        lambda _, limit=6: {
            "status": "ok",
            "headlines": [
                {
                    "title": "Mock local headline",
                    "link": "https://example.com/news",
                    "source": "Mock feed",
                    "published_at": "",
                    "summary": "",
                }
            ],
            "sources": [],
        },
    )

    client = TestClient(app)
    response = client.post("/runs/today/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["context"]["household"]["zip"] == "97070"
    assert body["files"]["html_path"].endswith(".html")
