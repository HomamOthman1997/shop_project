from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .mongo import db


def _now() -> datetime:
    return datetime.now(UTC)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_country(value: Any) -> str:
    return str(value or "").strip().upper()


def _block_key(*, mode: str, provider_code: str, service_key: str, country: str, provider_country_iso: str) -> str:
    return ":".join(
        [
            _norm(mode) or "temp",
            _norm(provider_code),
            _norm(service_key),
            _norm(country) or "none",
            _norm_country(provider_country_iso) or "any",
        ]
    )


def _mode(value: Any) -> str:
    return _norm(value) or "temp"


def _service_needs_provider_scope(service_key: str) -> bool:
    return _norm(service_key) in {"telegram"}


async def _write_purchase_block(
    *,
    mode: str,
    provider: str,
    service: str,
    country: str,
    provider_country_iso: str,
    api_service_name: str | None,
    reason: str | None,
    expires_at: datetime,
    now: datetime,
    scope: str,
) -> dict[str, Any]:
    key = _block_key(
        mode=mode,
        provider_code=provider,
        service_key=service,
        country=country,
        provider_country_iso=provider_country_iso,
    )
    await db.number_provider_purchase_blocks.update_one(
        {"_id": key},
        {
            "$set": {
                "mode": _mode(mode),
                "provider_code": provider,
                "service_key": service,
                "country": _norm(country) or "none",
                "provider_country_iso": _norm_country(provider_country_iso),
                "api_service_name": str(api_service_name or "").strip(),
                "reason": str(reason or "").strip(),
                "scope": str(scope or "location"),
                "expires_at": expires_at,
                "updated_at": now,
            },
            "$inc": {"failure_count": 1},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return {
        "_id": key,
        "provider_code": provider,
        "service_key": service,
        "country": _norm(country) or "none",
        "provider_country_iso": _norm_country(provider_country_iso),
        "expires_at": expires_at,
        "scope": str(scope or "location"),
    }


async def mark_number_provider_purchase_failure(
    *,
    mode: str,
    provider_code: str,
    service_key: str,
    country: str | None = None,
    provider_country_iso: str | None = None,
    api_service_name: str | None = None,
    reason: str | None = None,
    ttl_minutes: int = 30,
) -> dict[str, Any]:
    provider = _norm(provider_code)
    service = _norm(service_key)
    if not provider or not service:
        return {}
    now = _now()
    expires_at = now + timedelta(minutes=max(1, int(ttl_minutes or 30)))
    row = await _write_purchase_block(
        mode=mode,
        provider=provider,
        service=service,
        country=country or "none",
        provider_country_iso=provider_country_iso or "",
        api_service_name=api_service_name,
        reason=reason,
        expires_at=expires_at,
        now=now,
        scope="location",
    )
    if _mode(mode) == "temp" and _service_needs_provider_scope(service):
        await _write_purchase_block(
            mode=mode,
            provider=provider,
            service=service,
            country="any",
            provider_country_iso="",
            api_service_name=api_service_name,
            reason=reason,
            expires_at=expires_at,
            now=now,
            scope="provider_service",
        )
    return row


async def number_provider_purchase_blocked(
    *,
    mode: str,
    provider_code: str,
    service_key: str,
    country: str | None = None,
    provider_country_iso: str | None = None,
) -> dict[str, Any] | None:
    provider = _norm(provider_code)
    service = _norm(service_key)
    if not provider or not service:
        return None
    now = _now()
    country_norm = _norm(country) or "none"
    iso_norm = _norm_country(provider_country_iso)
    keys = [
        _block_key(mode=mode, provider_code=provider, service_key=service, country=country_norm, provider_country_iso=iso_norm),
    ]
    if iso_norm:
        keys.append(_block_key(mode=mode, provider_code=provider, service_key=service, country="none", provider_country_iso=iso_norm))
    keys.append(_block_key(mode=mode, provider_code=provider, service_key=service, country=country_norm, provider_country_iso=""))
    keys.append(_block_key(mode=mode, provider_code=provider, service_key=service, country="any", provider_country_iso=""))
    alternatives: list[dict[str, Any]] = [{"_id": {"$in": list(dict.fromkeys(keys))}}]
    if iso_norm:
        alternatives.append(
            {
                "mode": _mode(mode),
                "provider_code": provider,
                "service_key": service,
                "provider_country_iso": iso_norm,
            }
        )
    alternatives.append(
        {
            "mode": _mode(mode),
            "provider_code": provider,
            "service_key": service,
            "scope": "provider_service",
        }
    )
    row = await db.number_provider_purchase_blocks.find_one({"$or": alternatives, "expires_at": {"$gt": now}})
    return row if isinstance(row, dict) else None
