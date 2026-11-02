from datetime import UTC, datetime, timedelta

import config


def test_validate_runtime_security_allows_overdue_secrets_when_override_enabled(monkeypatch):
    stale_rotation = (datetime.now(UTC) - timedelta(days=160)).isoformat().replace("+00:00", "Z")

    monkeypatch.setattr(config.settings, "production_mode", True)
    monkeypatch.setattr(config.settings, "allow_env_file_in_production", True)
    monkeypatch.setattr(config.settings, "allow_stale_production_secrets", True)
    monkeypatch.setattr(config.settings, "bot_admin_token", "123456:valid_prod_token")
    monkeypatch.setattr(config.settings, "bot_main_token", "123456:valid_prod_token")
    monkeypatch.setattr(config.settings, "mongo_uri", "mongodb://localhost:27017/test")
    monkeypatch.setattr(config.settings, "secrets_rotated_at", stale_rotation)
    monkeypatch.setattr(config.settings, "secrets_max_age_days", 90)

    warnings = config.validate_runtime_security()

    assert warnings
    assert any("ALLOW_STALE_PRODUCTION_SECRETS=true" in warning for warning in warnings)
