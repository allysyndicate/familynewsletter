from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from family_newsletter.app.config import Settings


logger = logging.getLogger(__name__)


@dataclass
class SmtpConfig:
    """Resolved SMTP delivery configuration.

    Credentials are never hardcoded: they come from environment variables (via
    Settings / .env) or a git-ignored config. Defaults target Gmail SMTP.
    """

    host: str = "smtp.gmail.com"
    port: int = 587
    username: str = ""
    password: str = ""
    from_address: str = ""
    from_name: str = ""
    recipients: list[str] = field(default_factory=list)
    use_starttls: bool = True

    @property
    def sender(self) -> str:
        addr = self.from_address or self.username
        if self.from_name:
            return formataddr((self.from_name, addr))
        return addr

    def missing_fields(self) -> list[str]:
        """Return the names of required fields that are not yet configured."""
        missing = []
        if not self.host:
            missing.append("smtp_host")
        if not self.username:
            missing.append("smtp_username")
        if not self.password:
            missing.append("smtp_password")
        if not (self.from_address or self.username):
            missing.append("email_from")
        if not self.recipients:
            missing.append("email_recipients")
        return missing


def _parse_recipients(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        candidates = raw
    else:
        candidates = raw.replace(";", ",").split(",")
    return [addr.strip() for addr in candidates if addr and addr.strip()]


def smtp_config_from_settings(
    settings: Settings, file_config: dict | None = None
) -> SmtpConfig:
    """Build an SmtpConfig, preferring env-var Settings and falling back to the
    (git-ignored) YAML email block. Secrets only ever come from Settings/env."""
    email_cfg = (file_config or {}).get("email", {}) if file_config else {}

    host = settings.smtp_host or "smtp.gmail.com"
    from_address = settings.email_from or email_cfg.get("from_address", "")
    recipients = _parse_recipients(settings.email_recipients) or _parse_recipients(
        email_cfg.get("recipients", [])
    )

    return SmtpConfig(
        host=host,
        port=settings.smtp_port or 587,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_address=from_address,
        from_name=email_cfg.get("from_name", ""),
        recipients=recipients,
    )


def build_message(subject: str, html: str, text: str, config: SmtpConfig) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message.set_content(text or "This newsletter is best viewed as HTML.")
    message.add_alternative(html, subtype="html")
    return message


def send_email(
    subject: str,
    html: str,
    text: str,
    config: SmtpConfig,
    *,
    dry_run: bool = False,
) -> dict:
    """Send the rendered newsletter over SMTP with STARTTLS.

    In dry_run mode the message is fully built (validating recipients/config)
    but nothing is transmitted, so it is safe to run before real credentials
    exist.
    """
    missing = config.missing_fields()

    if dry_run:
        message = None
        if not missing:
            message = build_message(subject, html, text, config)
        logger.info(
            "DRY RUN: not sending. recipients=%s missing_config=%s",
            config.recipients or "(none)",
            missing or "(none)",
        )
        return {
            "sent": False,
            "dry_run": True,
            "recipients": config.recipients,
            "missing_config": missing,
            "subject": subject,
            "would_send": not missing,
            "message_bytes": len(bytes(message)) if message else 0,
        }

    if missing:
        raise ValueError(
            "Cannot send newsletter: missing SMTP configuration: "
            + ", ".join(missing)
        )

    message = build_message(subject, html, text, config)
    context = ssl.create_default_context()
    with smtplib.SMTP(config.host, config.port, timeout=30) as server:
        server.ehlo()
        if config.use_starttls:
            server.starttls(context=context)
            server.ehlo()
        server.login(config.username, config.password)
        server.send_message(message)

    logger.info("Newsletter sent to %s via %s", config.recipients, config.host)
    return {
        "sent": True,
        "dry_run": False,
        "recipients": config.recipients,
        "missing_config": [],
        "subject": subject,
        "would_send": True,
        "message_bytes": len(bytes(message)),
    }
