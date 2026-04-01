from __future__ import annotations

import logging
from typing import Any

from config import settings

logger = logging.getLogger("sentry")


def _looks_sensitive_key(key: str) -> bool:
    raw = str(key or "").strip().lower()
    if not raw:
        return False
    return any(token in raw for token in ("token", "password", "secret", "dsn", "key", "proof"))


def _scrub_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _looks_sensitive_key(str(key)):
                cleaned[str(key)] = "[redacted]"
            else:
                cleaned[str(key)] = _scrub_value(item)
        return cleaned
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_value(item) for item in value)
    return value


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    event = _scrub_value(event)
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers.keys()):
                if _looks_sensitive_key(key) or str(key).strip().lower() in {"authorization", "cookie"}:
                    headers[key] = "[redacted]"
    return event


def init_sentry(*, service_name: str) -> bool:
    dsn = str(getattr(settings, "sentry_dsn", "") or "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk  # type: ignore
    except Exception as exc:
        logger.warning("Sentry DSN is set but sentry-sdk is unavailable: %s", exc)
        return False

    environment = str(getattr(settings, "sentry_environment", "development") or "development").strip()
    try:
        traces_sample_rate = float(getattr(settings, "sentry_traces_sample_rate", 0.0) or 0.0)
    except Exception:
        traces_sample_rate = 0.0
    if traces_sample_rate < 0:
        traces_sample_rate = 0.0
    if traces_sample_rate > 1:
        traces_sample_rate = 1.0
    send_default_pii = bool(getattr(settings, "sentry_send_default_pii", False))
    enable_mcp_integration = bool(getattr(settings, "sentry_enable_mcp_integration", True))
    integrations: list[Any] = []
    mcp_integration_enabled = False
    if enable_mcp_integration:
        try:
            from sentry_sdk.integrations.mcp import MCPIntegration  # type: ignore

            integrations.append(MCPIntegration())
            mcp_integration_enabled = True
        except Exception as exc:
            logger.info("MCP integration unavailable, continuing without it: %s", exc)

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=send_default_pii,
        integrations=integrations,
        before_send=_before_send,
        release=None,
    )
    sentry_sdk.set_tag("service_name", service_name)
    sentry_sdk.set_tag("bot_version", str(getattr(settings, "bot_version", 0)))
    logger.info(
        "Sentry initialized service=%s environment=%s send_default_pii=%s",
        service_name,
        environment,
        send_default_pii,
    )
    logger.info("Sentry MCP integration enabled=%s", mcp_integration_enabled)
    return True
