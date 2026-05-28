from typing import Optional
from datetime import UTC, datetime
import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_service_port() -> int:
    try:
        return int(os.getenv("PORT") or "8080")
    except Exception:
        return 8080


class Settings(BaseSettings):
    bot_admin_token: str
    bot_main_token: str
    bot_numbers_token: Optional[str] = None
    bot_digital_products_token: Optional[str] = None
    bot_card_ex_token: Optional[str] = None
    mongo_uri: str
    db_name: str = "CyberZone"
    owner_id: int
    bot_version: int = 1
    interaction_lock_enabled: bool = True
    interaction_lock_message_window_ms: int = 2500
    interaction_lock_callback_window_ms: int = 1200
    # provider credentials - read from environment/.env
    smspool_key: Optional[str] = None
    telabot_user: Optional[str] = None
    telabot_key: Optional[str] = None
    tv_user: Optional[str] = None
    tv_key: Optional[str] = None
    herosms_key: Optional[str] = None
    herosms_base_url: str = "https://hero-sms.com/stubs/handler_api.php"
    nonvoip_key: Optional[str] = None
    nonvoip_email: Optional[str] = None
    nonvoip_base_url: str = "https://www.non-voip.com/api/reseller"
    pvadeals_key: Optional[str] = None
    pvadeals_base_url: str = "https://prod-v3.pvadeals.com/v3/api"
    smsready_key: Optional[str] = None
    smsready_base_url: str = "https://api.sms-ready.com/api"
    pvapins_key: Optional[str] = None
    pvapins_base_url: str = "https://api.pvapins.com/user/api"
    vaksms_key: Optional[str] = None
    vaksms_base_url: str = "https://vak-sms.com/api"
    vaksms_docs_url: str = "https://vak-sms.com/api/vak/"
    vaksms_site_base_url: str = "https://vak-sms.com/backend"
    vaksms_stub_base_url: str = "https://vak-sms.com/stubs/handler_api.php"
    vaksms_rub_to_usd_rate: float = 0.0112
    # Non-VoIP price feed currency handling.
    # Supported values:
    # - RUB: provider returns Russian rubles and we convert to USD
    # - USD: provider already returns USD
    # - CENTS_USD: provider returns USD cents (e.g. 53 => 0.53$)
    nonvoip_price_currency: str = "RUB"
    nonvoip_rub_to_usd_rate: float = 0.0112
    numbers_service_markup_percent: float = 0.0
    # Optional JSON override for temporary-number floors.
    # Example: {"whatsapp":{"*":1.0,"US":1.5},"telegram":{"*":0.75,"US":0.9}}
    numbers_temp_price_floors_json: Optional[str] = None
    numbers_markup_cache_ttl_sec: int = 60
    # Master switch: when disabled, all platform profit policy is bypassed.
    # This forces markups/fees/commissions to zero for analysis/testing.
    profit_policy_enabled: bool = True
    numbers_show_all_providers_for_testing: bool = False
    numbers_provider_webhook_token: Optional[str] = None
    numbers_provider_sms_polling_enabled: bool = False
    # JSON runtime override for provider readiness gates.
    # Example: {"smsready":{"status":"webhook_pending","quote_enabled":true,"purchase_enabled":true}}
    numbers_provider_readiness_overrides: Optional[str] = None
    # Legacy escape hatch only. Customer ordering on the real Numbers bot should
    # go through the Mini App; keep this false unless intentionally testing the
    # old Telegram FSM purchase flow.
    numbers_telegram_order_flow_enabled: bool = False
    # Temporary testing hook: JSON object like {"smspool": 5, "nonvoip": 10.5}
    # to simulate provider balances without querying the upstream provider.
    numbers_provider_balance_simulation: Optional[str] = None
    numbers_provider_balance_cache_ttl_sec: int = 90
    numbers_rental_cache_ttl_sec: int = 90
    numbers_rental_cache_stale_fallback_sec: int = 900
    numbers_rental_watch_poll_sec: int = 30
    numbers_rental_sweep_interval_sec: int = 60
    numbers_rental_sweep_limit: int = 200
    numbers_rental_safe_cutoff_sec: int = 60
    numbers_rental_owner_alert_window_sec: int = 180
    numbers_temp_recovery_sweep_interval_sec: int = 60
    numbers_temp_recovery_sweep_limit: int = 200
    numbers_unprovisioned_order_recovery_interval_sec: int = 60
    numbers_unprovisioned_order_recovery_limit: int = 100
    numbers_unprovisioned_order_grace_sec: int = 120
    numbers_hero_rental_cancel_window_sec: int = 1200
    numbers_smspool_rental_refund_window_sec: Optional[int] = None
    numbers_textverified_rental_refund_window_sec: Optional[int] = None
    numbers_provider_timeout_sec: float = 12.0
    numbers_rental_provider_timeout_sec: float = 10.0
    numbers_textverified_rental_timeout_sec: float = 8.0
    numbers_success_rate_enabled: bool = True
    numbers_success_rate_lookback_days: int = 14
    numbers_success_rate_min_attempts: int = 3
    numbers_success_rate_default_percent: float = 100.0
    numbers_success_rate_display_min_attempts: int = 5
    numbers_success_rate_query_timeout_sec: float = 2.0
    numbers_trust_enabled: bool = True
    numbers_trust_attempt_window_minutes: int = 15
    numbers_trust_allowed_no_code_attempts: int = 2
    numbers_trust_1h_score_limit: int = 2
    numbers_trust_24h_score_limit: int = 8
    numbers_trust_1h_cooldown_sec: int = 900
    numbers_trust_24h_cooldown_sec: int = 2700
    numbers_reuse_block_1h_score: int = 1
    numbers_reuse_block_24h_score: int = 4
    proxy_service_markup_percent: float = 0.0
    proxy_change_check_price: float = 0.015
    proxy_change_only_cooldown_minutes: int = 15
    proxy_quality_gate_enabled: bool = True
    proxy_quality_fail_closed: bool = False
    proxy_ipqs_api_key: Optional[str] = None
    proxy_ipqs_strict_fail_closed: bool = False
    proxy_ipqs_timeout_sec: float = 4.0
    proxy_ops_summary_interval_sec: int = 3600
    proxy_ops_failure_alert_threshold_percent: float = 45.0
    proxy_hide_unpriced_offers: bool = True
    reseller_bot_monthly_price_usd: float = 10.0
    reseller_bot_trial_price_usd: float = 1.0
    reseller_bot_trial_days: int = 30
    reseller_bot_grace_days: int = 3
    bot_subscription_sweep_interval_sec: int = 300
    bot_subscription_sweep_limit: int = 500
    nine_proxy_base_url: Optional[str] = None
    nine_proxy_key: Optional[str] = None
    fourg_proxy_base_url: Optional[str] = None
    fourg_proxy_key: Optional[str] = None
    fourg_proxy_token: Optional[str] = None
    fourg_proxy_email: Optional[str] = None
    fourg_proxy_password: Optional[str] = None
    fourg_proxy_default_price: float = 0.0
    fourg_proxy_package_prices: Optional[str] = None
    cyberyozh_proxy_base_url: str = "https://app.cyberyozh.com/api/v1"
    cyberyozh_proxy_key: Optional[str] = None
    g2bulk_base_url: str = "https://api.g2bulk.com"
    g2bulk_api_key: Optional[str] = None
    za3em_base_url: str = "https://api.za3em-card.com"
    za3em_enabled: bool = False
    za3em_api_token: Optional[str] = None
    za3em_catalog_cache_ttl_sec: int = 120
    esim_access_api_base: str = "https://api.esimaccess.com/api/v1/open"
    esim_access_code: Optional[str] = None
    esim_access_secret_key: Optional[str] = None
    esim_access_catalog_cache_ttl_sec: int = 600
    zendit_api_base: str = "https://api.zendit.io/v1"
    zendit_api_token: Optional[str] = None
    reloadly_client_id: Optional[str] = None
    reloadly_client_secret: Optional[str] = None
    g2bulk_catalog_cache_ttl_sec: int = 120
    digital_products_pubg_undercut_percent: float = 1.0
    digital_products_recovery_sweep_interval_sec: int = 300
    digital_products_recovery_pending_age_sec: int = 120
    digital_products_validation_interval_sec: int = 21600
    digital_products_miniapp_enabled: bool = False
    digital_products_miniapp_public_url: Optional[str] = None
    digital_products_miniapp_host: str = "0.0.0.0"
    digital_products_miniapp_port: int = _default_service_port()
    numbers_miniapp_enabled: bool = False
    numbers_miniapp_public_url: Optional[str] = None
    numbers_miniapp_path: str = "/mini/numbers-v2"
    cardex_miniapp_enabled: bool = False
    cardex_miniapp_public_url: Optional[str] = None
    cardex_release_sweep_interval_sec: int = 600
    financial_anomaly_sweep_interval_sec: int = 21600
    financial_anomaly_scan_days: int = 7
    financial_anomaly_scan_max_rows: int = 30
    proxy_validation_interval_sec: int = 21600
    proxy_catalog_refresh_interval_sec: int = 3600
    redis_url: Optional[str] = None
    redis_token: Optional[str] = None
    ai_provider: str = "openrouter"
    ai_owner_daily_limit: int = 40
    ai_dedupe_window_minutes: int = 15
    openrouter_api_key: Optional[str] = None
    openrouter_model: str = "openrouter/free"
    openrouter_api_base: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: Optional[str] = None
    openrouter_app_title: str = "Shop Project Bot"
    sentry_dsn: Optional[str] = None
    sentry_api_base: str = "https://sentry.io/api/0"
    sentry_org_slug: Optional[str] = None
    sentry_project_slug: Optional[str] = None
    sentry_auth_token: Optional[str] = None
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 0.0
    sentry_send_default_pii: bool = False
    sentry_enable_mcp_integration: bool = True
    legacy_ledger_mirror: bool = False
    main_bot_username: Optional[str] = None
    numbers_bot_username: Optional[str] = None
    digital_products_bot_username: Optional[str] = None
    card_ex_bot_username: Optional[str] = None
    # Optional Telegram custom emoji icons for keyboard buttons.
    # Keep empty to use plain text fallback.
    tg_icon_temp_numbers: Optional[str] = None
    tg_icon_rental_numbers: Optional[str] = None
    tg_icon_call_number: Optional[str] = None
    tg_icon_account: Optional[str] = None
    tg_icon_support: Optional[str] = None
    tg_icon_confirm: Optional[str] = None
    tg_icon_cancel: Optional[str] = None
    bot_sync_poll_seconds: int = 20
    production_mode: bool = False
    allow_env_file_in_production: bool = False
    secrets_rotated_at: Optional[str] = None
    secrets_max_age_days: int = 90
    lifecycle_cleanup_interval_sec: int = 21600
    lifecycle_telemetry_retention_days: int = 30
    lifecycle_number_events_retention_days: int = 120
    lifecycle_usage_retention_days: int = 180
    lifecycle_order_archive_age_days: int = 120
    lifecycle_orders_archive_retention_days: int = 365
    referral_enabled: bool = False
    referral_reward_percent: float = 0.0
    referral_max_reward_usd: float = 0.0
    referral_min_order_usd: float = 0.0
    custom_services_admin_ids: Optional[str] = None
    cardex_admin_ids: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",  # ignore unexpected environment variables
    )

    # ensure we don't accidentally use placeholder values
    @field_validator("mongo_uri")
    @classmethod
    def check_mongo_uri(cls, v: str):
        if not v or "your_mongo_uri" in v:
            raise ValueError("MONGO_URI must be set in environment/.env")
        return v


settings = Settings()

# convenience alias for legacy imports
# some modules expect OWNER_ID constant; keep compatibility
OWNER_ID = settings.owner_id


def validate_runtime_security() -> list[str]:
    warnings: list[str] = []
    if not bool(getattr(settings, "production_mode", False)):
        return warnings

    if (not bool(getattr(settings, "allow_env_file_in_production", False))) and Path(".env").exists():
        raise RuntimeError(
            "production_mode is enabled but local .env file exists. "
            "Use host secret manager or set ALLOW_ENV_FILE_IN_PRODUCTION=true intentionally."
        )

    weak_tokens: list[str] = []
    token_checks = {
        "bot_admin_token": settings.bot_admin_token,
        "bot_main_token": settings.bot_main_token,
        "mongo_uri": settings.mongo_uri,
    }
    for key, value in token_checks.items():
        text = str(value or "").strip().lower()
        if not text or "your_" in text or "changeme" in text or "example" in text:
            weak_tokens.append(key)
    if weak_tokens:
        raise RuntimeError(f"Weak/placeholder production secrets: {', '.join(sorted(weak_tokens))}")

    rotated_at_raw = str(getattr(settings, "secrets_rotated_at", "") or "").strip()
    if not rotated_at_raw:
        raise RuntimeError("SECRETS_ROTATED_AT is required in production mode.")
    try:
        rotated_at = datetime.fromisoformat(rotated_at_raw.replace("Z", "+00:00"))
    except Exception as exc:
        raise RuntimeError("SECRETS_ROTATED_AT must be ISO datetime/date (example: 2026-03-20).") from exc
    if rotated_at.tzinfo is None:
        rotated_at = rotated_at.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - rotated_at.astimezone(UTC)).days
    max_age_days = max(7, int(getattr(settings, "secrets_max_age_days", 90) or 90))
    if age_days > max_age_days:
        raise RuntimeError(
            f"Production secrets are older than policy ({age_days}d > {max_age_days}d). Rotate keys before startup."
        )
    if age_days > int(max_age_days * 0.8):
        warnings.append(f"Secrets rotation nearing limit ({age_days}d/{max_age_days}d).")
    return warnings


def enforce_openrouter_only_mode() -> list[str]:
    notes: list[str] = []
    blocked_keys = (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "OPENAI_ORGANIZATION",
        "OPENAI_PROJECT",
    )
    removed = []
    for key in blocked_keys:
        if os.environ.pop(key, None):
            removed.append(key)
    if removed:
        notes.append(f"Removed OpenAI env keys: {', '.join(removed)}")

    provider = str(getattr(settings, "ai_provider", "openrouter") or "openrouter").strip().lower()
    if provider != "openrouter":
        settings.ai_provider = "openrouter"  # type: ignore[attr-defined]
        notes.append(f"AI_PROVIDER forced to openrouter (was '{provider}').")
    return notes
