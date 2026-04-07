import logging
from typing import Any

from services.numbers.manager_helpers import (
    _normalize_key,
    _service_candidate_keys,
    _service_display_name,
)
from services.numbers.providers.error_normalizer import normalize_provider_error
from services.numbers.service_families import normalize_service_key
from services.numbers.service_map import get_service_provider_map, resolve_canonical_service_key

logger = logging.getLogger("numbers_manager")


def _service_resolution_snapshot(service_key: str, provider_code: str) -> dict[str, Any]:
    canonical = resolve_canonical_service_key(service_key)
    provider_code_norm = str(provider_code or "").strip().lower()
    provider_map = get_service_provider_map(canonical or service_key)
    return {
        "requested_service": str(service_key or ""),
        "canonical_service": canonical,
        "display_name": _service_display_name(canonical or service_key) or str(service_key or ""),
        "provider_code": provider_code_norm,
        "provider_mapped_value": provider_map.get(provider_code_norm),
        "provider_candidates": sorted(_service_candidate_keys(service_key)),
        "resolved_provider_service": None,
        "provider_reason": "",
    }


def _log_provider_resolution_failure(resolution: dict[str, Any]) -> None:
    logger.info(
        "provider service unresolved provider=%s requested=%s canonical=%s reason=%s candidates=%s",
        resolution.get("provider_code", ""),
        resolution.get("requested_service", ""),
        resolution.get("canonical_service", ""),
        resolution.get("provider_reason", ""),
        ",".join(str(item) for item in (resolution.get("provider_candidates") or [])),
    )


def _log_provider_resolution_event(
    resolution: dict[str, Any],
    *,
    phase: str,
    country: str | None = None,
    state: str | None = None,
) -> None:
    requested = str(resolution.get("requested_service") or "").strip()
    canonical = str(resolution.get("canonical_service") or "").strip()
    resolved = str(resolution.get("resolved_provider_service") or "").strip()
    reason = str(resolution.get("provider_reason") or "").strip()
    provider = str(resolution.get("provider_code") or "").strip().lower()
    display_name = str(resolution.get("display_name") or "").strip()
    candidates = ",".join(str(item) for item in (resolution.get("provider_candidates") or []))
    is_mismatch = bool(resolved) and normalize_service_key(requested) != normalize_service_key(resolved)
    if not is_mismatch and reason not in {"resolved_static_mapping", "resolved_provider_lookup"}:
        return
    logger.info(
        "provider resolution %s provider=%s requested=%s canonical=%s resolved=%s display=%s reason=%s country=%s state=%s candidates=%s mismatch=%s",
        phase,
        provider,
        requested,
        canonical,
        resolved,
        display_name,
        reason,
        str(country or ""),
        str(state or ""),
        candidates,
        is_mismatch,
    )


def _log_provider_attempt_event(
    *,
    phase: str,
    provider_code: str,
    requested_service: str | None,
    api_service_name: str | None,
    country: str | None,
    state: str | None,
    success: bool,
    reason: str | None = None,
    raw: Any = None,
) -> None:
    normalized = normalize_provider_error(raw) if not bool(success) else {"code": "", "message": ""}
    logger.info(
        "provider attempt %s provider=%s requested=%s api_service=%s country=%s state=%s success=%s reason=%s normalized_code=%s normalized_message=%s",
        phase,
        str(provider_code or "").strip().lower(),
        str(requested_service or "").strip(),
        str(api_service_name or "").strip(),
        str(country or ""),
        str(state or ""),
        bool(success),
        str(reason or "").strip(),
        str(normalized.get("code") or ""),
        str(normalized.get("message") or ""),
    )
