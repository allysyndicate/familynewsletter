from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from family_newsletter.app.config import get_effective_config, get_settings
from family_newsletter.app.db import init_db
from family_newsletter.app.newsletter.preview import build_preview_context, render_preview, write_preview_files


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(get_settings())
    yield


app = FastAPI(title="Family Newsletter", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": "family-newsletter",
        "environment": settings.app_env,
        "sample_mode": settings.sample_mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/config/effective")
def effective_config():
    return get_effective_config(get_settings())


@app.post("/runs/today/preview")
def preview_today():
    settings = get_settings()
    context = build_preview_context(settings)
    rendered = render_preview(context)
    files = write_preview_files(rendered, context["newsletter_date"])
    return {
        "status": "ok",
        "subject": rendered["subject"],
        "context": context,
        "files": files,
    }
