from __future__ import annotations

import logging
from datetime import date

from family_newsletter.app.config import Settings, load_yaml_config
from family_newsletter.app.email.sender import send_email, smtp_config_from_settings
from family_newsletter.app.newsletter.preview import (
    build_preview_context,
    render_preview,
    write_preview_files,
)


logger = logging.getLogger(__name__)


def deliver_newsletter(
    settings: Settings,
    *,
    dry_run: bool = False,
    write_preview: bool = True,
    newsletter_date: date | None = None,
) -> dict:
    """Regenerate the newsletter fresh (all sections re-fetched) and send it.

    build_preview_context re-fetches every source on each call, so there is no
    stale/cached data: the email always reflects a live regeneration performed
    immediately before send. When dry_run is True nothing is transmitted.
    """
    logger.info("Regenerating newsletter (fresh fetch) dry_run=%s", dry_run)
    context = build_preview_context(settings, newsletter_date)
    rendered = render_preview(context)

    files = None
    if write_preview:
        files = write_preview_files(rendered, context["newsletter_date"])

    file_config = load_yaml_config(settings.config_file)
    smtp = smtp_config_from_settings(settings, file_config)

    # newsletter_enabled gates live sends only; dry runs always proceed so the
    # pipeline stays testable while the flag is off.
    send_dry_run = dry_run or not settings.newsletter_enabled
    if send_dry_run and not dry_run:
        logger.warning(
            "NEWSLETTER_ENABLED is false; skipping live send (no email transmitted)."
        )

    result = send_email(
        rendered["subject"],
        rendered["html"],
        rendered["text"],
        smtp,
        dry_run=send_dry_run,
    )
    result["skipped_disabled"] = send_dry_run and not dry_run
    result["newsletter_date"] = context["newsletter_date"]
    result["files"] = files
    result["field_status"] = context["field_status"]
    return result
