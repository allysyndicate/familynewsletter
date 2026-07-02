from family_newsletter.app.email.sender import (
    SmtpConfig,
    build_message,
    send_email,
    smtp_config_from_settings,
)
from family_newsletter.app.config import Settings


def _full_config() -> SmtpConfig:
    return SmtpConfig(
        host="smtp.gmail.com",
        port=587,
        username="sender@gmail.com",
        password="app-password",
        from_address="sender@gmail.com",
        from_name="Family Morning Brief",
        recipients=["a@example.com", "b@example.com"],
    )


def test_dry_run_does_not_send_but_builds_message():
    result = send_email(
        "Subject", "<p>hello</p>", "hello", _full_config(), dry_run=True
    )
    assert result["dry_run"] is True
    assert result["sent"] is False
    assert result["would_send"] is True
    assert result["missing_config"] == []
    assert result["message_bytes"] > 0
    assert result["recipients"] == ["a@example.com", "b@example.com"]


def test_dry_run_reports_missing_config():
    config = SmtpConfig()  # no credentials or recipients
    result = send_email("Subject", "<p>hi</p>", "hi", config, dry_run=True)
    assert result["would_send"] is False
    assert "smtp_username" in result["missing_config"]
    assert "smtp_password" in result["missing_config"]
    assert "email_recipients" in result["missing_config"]


def test_build_message_is_multipart_with_html_and_text():
    message = build_message("Subj", "<p>x</p>", "x", _full_config())
    assert message["Subject"] == "Subj"
    assert message["To"] == "a@example.com, b@example.com"
    assert message.is_multipart()
    subtypes = {part.get_content_subtype() for part in message.iter_parts()}
    assert {"plain", "html"} <= subtypes


def test_recipients_from_env_override_yaml():
    settings = Settings(
        smtp_username="sender@gmail.com",
        smtp_password="pw",
        email_from="sender@gmail.com",
        email_recipients="env1@example.com, env2@example.com",
    )
    file_config = {"email": {"recipients": ["yaml@example.com"]}}
    config = smtp_config_from_settings(settings, file_config)
    assert config.recipients == ["env1@example.com", "env2@example.com"]
    assert config.host == "smtp.gmail.com"
