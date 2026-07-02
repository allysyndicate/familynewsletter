from family_newsletter.app.config import Settings, get_effective_config


def test_effective_config_redacts_secrets():
    settings = Settings(
        smtp_password="secret",
        resend_api_key="secret",
        weather_api_key="secret",
    )

    config = get_effective_config(settings).model_dump()

    assert config["environment"]["smtp_password"] == "***REDACTED***"
    assert config["environment"]["resend_api_key"] == "***REDACTED***"
    assert config["environment"]["weather_api_key"] == "***REDACTED***"

