from __future__ import annotations

from config import settings


def beta_mode_enabled() -> bool:
    return bool(getattr(settings, "beta_mode_enabled", False))


def beta_markup_percent(default: float = 10.0) -> float:
    try:
        value = float(getattr(settings, "beta_markup_percent", default) or default)
    except Exception:
        value = float(default)
    return max(0.0, min(500.0, value))


def _optional_percent(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    return max(0.0, min(500.0, parsed))


def beta_numbers_markup_percent(default: float = 10.0) -> float:
    specific = _optional_percent(getattr(settings, "beta_numbers_markup_percent", None))
    if specific is not None:
        return specific
    return beta_markup_percent(default)


def beta_game_store_markup_percent(default: float = 10.0) -> float:
    specific = _optional_percent(getattr(settings, "beta_game_store_markup_percent", None))
    if specific is not None:
        return specific
    return beta_markup_percent(default)


def beta_proxy_markup_percent(default: float = 10.0) -> float:
    specific = _optional_percent(getattr(settings, "beta_proxy_markup_percent", None))
    if specific is not None:
        return specific
    return beta_markup_percent(default)


def beta_disable_create_bot() -> bool:
    return beta_mode_enabled() and bool(getattr(settings, "beta_disable_create_bot", False))


def apply_beta_markup(default_percent: float) -> float:
    if beta_mode_enabled():
        return beta_markup_percent(default_percent)
    try:
        value = float(default_percent)
    except Exception:
        value = 0.0
    return max(0.0, value)
