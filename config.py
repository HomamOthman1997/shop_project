from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_admin_token: str
    bot_main_token: str
    mongo_uri: str
    db_name: str = "CyberZone"
    owner_id: int
    bot_version: int = 1
    interaction_lock_enabled: bool = True
    interaction_lock_message_window_ms: int = 2500
    interaction_lock_callback_window_ms: int = 1200
    beta_mode_enabled: bool = False
    beta_markup_percent: float = 10.0
    beta_numbers_markup_percent: Optional[float] = None
    beta_game_store_markup_percent: Optional[float] = None
    beta_proxy_markup_percent: Optional[float] = None
    beta_disable_create_bot: bool = False

    # provider credentials - read from environment/.env
    smspool_key: Optional[str] = None
    telabot_user: Optional[str] = None
    telabot_key: Optional[str] = None
    tv_user: Optional[str] = None
    tv_key: Optional[str] = None
    herosms_key: Optional[str] = None
    herosms_base_url: str = "https://hero-sms.com/stubs/handler_api.php"
    smsman_key: Optional[str] = None
    smsman_base_url: str = "https://api.sms-man.com/control"
    # SMS-Man price feed currency handling.
    # Supported values:
    # - RUB: provider returns Russian rubles and we convert to USD
    # - USD: provider already returns USD
    # - CENTS_USD: provider returns USD cents (e.g. 53 => 0.53$)
    smsman_price_currency: str = "RUB"
    smsman_rub_to_usd_rate: float = 0.0112
    numbers_service_markup_percent: float = 25.0
    numbers_markup_cache_ttl_sec: int = 60
    # Master switch: when disabled, all platform profit policy is bypassed.
    # This forces markups/fees/commissions to zero for analysis/testing.
    profit_policy_enabled: bool = True
    numbers_show_all_providers_for_testing: bool = True
    numbers_price_cache_enabled: bool = True
    numbers_price_cache_ttl_sec: int = 60
    numbers_price_cache_stale_fallback_sec: int = 600
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
    proxy_hide_unpriced_offers: bool = True
    nine_proxy_base_url: Optional[str] = None
    nine_proxy_key: Optional[str] = None
    fourg_proxy_base_url: Optional[str] = None
    fourg_proxy_key: Optional[str] = None
    fourg_proxy_token: Optional[str] = None
    fourg_proxy_email: Optional[str] = None
    fourg_proxy_password: Optional[str] = None
    fourg_proxy_default_price: float = 0.0
    fourg_proxy_package_prices: Optional[str] = None
    g2bulk_base_url: str = "https://api.g2bulk.com"
    g2bulk_api_key: Optional[str] = None
    g2bulk_catalog_cache_ttl_sec: int = 120
    redis_url: Optional[str] = None
    redis_token: Optional[str] = None
    legacy_ledger_mirror: bool = False
    main_reseller_bot_username: Optional[str] = None
    # Optional Telegram custom emoji icons for keyboard buttons.
    # Keep empty to use plain text fallback.
    tg_icon_temp_numbers: Optional[str] = None
    tg_icon_rental_numbers: Optional[str] = None
    tg_icon_confirm: Optional[str] = None
    tg_icon_cancel: Optional[str] = None
    bot_sync_poll_seconds: int = 20

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
