from __future__ import annotations

from typing import Any


def normalize_provider_error(raw: Any) -> dict[str, Any]:
    text = _error_text(raw).lower()
    code = "PROVIDER_ERROR"
    retryable = True
    category = "unknown"

    if any(marker in text for marker in ("temporarily unavailable", "timeout", "request_error")):
        code = "TEMPORARY_FAILURE"
        category = "transient"
        retryable = True
    elif any(marker in text for marker in ("out of stock", "unavailable", "no numbers", "no free phones")):
        code = "OUT_OF_STOCK"
        category = "availability"
        retryable = True
    elif any(marker in text for marker in ("insufficient balance", "not sufficient", "no_balance", "balance_error", "low balance")):
        code = "PROVIDER_BALANCE_LOW"
        category = "provider_balance"
        retryable = False
    elif any(marker in text for marker in ("unauthorized", "forbidden", "wrong token", "invalidtoken", "bad_key")):
        code = "AUTH_ERROR"
        category = "auth"
        retryable = False
    return {
        "code": code,
        "message": _error_text(raw),
        "category": category,
        "retryable": retryable,
    }


def _error_text(raw: Any) -> str:
    if isinstance(raw, dict):
        for key in ("errorDescription", "message", "error_msg", "error", "detail", "raw_text"):
            value = raw.get(key)
            if value:
                return str(value)
        if "pools" in raw and isinstance(raw.get("pools"), dict):
            parts: list[str] = []
            for pool_name, row in raw.get("pools", {}).items():
                if isinstance(row, dict) and row.get("message"):
                    parts.append(f"{pool_name}: {row.get('message')}")
            if parts:
                return " | ".join(parts)
        return str(raw)
    return str(raw or "provider_error")
