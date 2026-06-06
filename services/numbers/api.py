from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from aiohttp import web

from database.financial_ledger import get_user_wallet_balance, list_user_wallet_entries
from database.owner_payment_settings_repo import get_owner_payment_methods
from database.orders_repo import (
    get_user_number_order,
    list_api_temp_refund_support_reviews,
    list_user_recent_temp_and_voice_orders,
    list_user_rental_orders,
    resolve_api_temp_refund_support_review,
)
from database.provider_webhook_repo import list_provider_webhook_events
from database.user_repo import get_user
from services.numbers.api_payloads import (
    TEMP_QUOTE_PROVIDER_CODES,
    VOICE_GENERIC_SERVICE,
    normalize_rental_quote_rows,
    normalize_temp_quote_rows,
    normalize_voice_quote_rows,
    numbers_bootstrap_payload,
    voice_provider_offer_is_buyable,
)
from services.numbers.api_docs import render_numbers_api_docs
from services.numbers.api_schema import numbers_openapi_schema
from services.numbers.country_suggestions_service import country_suggestions_for_service
from services.numbers.customer_flows import (
    SUPPORT_CATEGORIES,
    recharge_methods_payload as shared_recharge_methods_payload,
    submit_recharge_request as shared_submit_recharge_request,
)
from services.numbers.manager import get_all_prices, get_all_rental_prices, get_all_voice_prices
from services.numbers.order_recording_service import download_voice_order_recording
from services.numbers.order_cancel_service import cancel_number_order
from services.numbers.order_refresh_service import refresh_number_order
from services.numbers.order_rental_service import (
    finish_rental_order,
    renew_rental_order,
    rental_notes_state,
    rental_sms_state,
    wake_rental_order,
)
from services.numbers.order_resend_service import request_number_order_resend
from services.numbers.order_service import NumbersOrderError, create_number_order_from_quote, public_order_payload, request_replacement_order
from services.numbers.provider_webhook_service import replay_provider_webhook_event
from services.numbers.provider_readiness import provider_readiness_rows
from services.numbers.service_map import get_service_display_name, resolve_canonical_service_key
from services.platform.api_auth import ApiAuthContext, require_api_auth
from services.platform.api_rate_limits import (
    ApiRateLimitDecision,
    ApiRateLimitExceeded,
    check_api_rate_limit,
    rate_limit_headers,
    retry_after_seconds,
)
from services.platform.website_auth import require_website_purchase_ready

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

logger = logging.getLogger("numbers_api")

_SUPPORT_CATEGORY_LABELS = {
    "numbers": "Numbers orders",
    "user_balance": "Balance and payments",
}
_SUPPORT_CATEGORIES = tuple((key, _SUPPORT_CATEGORY_LABELS.get(key, key.replace("_", " ").title())) for key in SUPPORT_CATEGORIES)
_MAX_RECHARGE_PROOF_BYTES = 6 * 1024 * 1024


def _text(lang: str, en: str, ar: str) -> str:
    return ar if str(lang or "").lower().startswith("ar") else en


async def health(_request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "status": "healthy",
            "service": "numbers-api",
            "version": "v1",
        },
        headers=dict(_NO_STORE_HEADERS),
    )


async def catalog_bootstrap(_request: web.Request) -> web.Response:
    return web.json_response(numbers_bootstrap_payload(), headers=dict(_NO_STORE_HEADERS))


async def openapi_schema(_request: web.Request) -> web.Response:
    return web.json_response(numbers_openapi_schema(), headers=dict(_NO_STORE_HEADERS))


async def api_docs(_request: web.Request) -> web.Response:
    return web.Response(
        text=render_numbers_api_docs(),
        content_type="text/html",
        headers=dict(_NO_STORE_HEADERS),
    )


def _format_money(value: float) -> str:
    return f"${float(value or 0):.2f}"


def _format_credit_rate(value: float) -> str:
    amount = float(value or 0.0)
    text = f"{amount:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _api_action(
    key: str,
    *,
    enabled: bool,
    endpoint: str,
    method: str = "GET",
    label: str = "",
    reason: str = "",
) -> dict:
    return {
        "key": key,
        "enabled": bool(enabled),
        "label": label or key,
        "endpoint": endpoint,
        "method": method.upper(),
        "reason": "" if enabled else (reason or "disabled"),
    }


async def _api_recharge_per_credit(method: dict) -> float:
    direct = method.get("per_credit")
    if direct not in {None, ""}:
        try:
            value = float(direct)
            if value > 0:
                return value
        except Exception:
            pass
    currency = str(method.get("currency") or "USD").strip().upper()
    if currency == "USD":
        return 1.0
    rate = await get_owner_exchange_rate(currency)
    try:
        value = float(rate)
    except Exception:
        value = 0.0
    return value if value > 0 else 1.0


def _render_recharge_instructions(method: dict, *, rate: float) -> str:
    template = str(method.get("instructions") or "").strip()
    target = str(method.get("target") or method.get("address") or "").strip()
    support = str(method.get("support") or "").strip()
    if template:
        try:
            return template.format(target=target, support=support, rate=_format_credit_rate(rate))
        except Exception:
            return template
    parts = []
    if target:
        parts.append(f"Send payment to {target}.")
    if support:
        parts.append(f"Contact support at {support} after payment.")
    return " ".join(parts)


async def _recharge_methods_payload() -> list[dict]:
    return await shared_recharge_methods_payload("en", methods=await get_owner_payment_methods())


def _iso_datetime(value) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _wallet_activity_kind(reason: object, category: object) -> str:
    reason_text = str(reason or "").strip().lower()
    category_text = str(category or "").strip().lower()
    if category_text == "core_purchase" or reason_text.startswith("purchase_core_"):
        return "numbers_purchase"
    if category_text == "core_refund" or reason_text.startswith("refund_core_"):
        return "numbers_refund"
    if category_text == "recharge_credit" or reason_text == "recharge_request_accepted":
        return "balance_recharge"
    if category_text in {"manual_credit", "manual_adjustment"}:
        return "balance_adjustment"
    return "wallet_activity"


def _wallet_activity_label(kind: str) -> str:
    labels = {
        "numbers_purchase": "Numbers purchase",
        "numbers_refund": "Numbers refund",
        "balance_recharge": "Balance recharge",
        "balance_adjustment": "Balance adjustment",
    }
    return labels.get(kind, "Wallet activity")


def _wallet_activity_payload(entries: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for entry in entries or []:
        try:
            amount = float(entry.get("amount") or 0.0)
        except Exception:
            amount = 0.0
        try:
            balance_after = float(entry.get("balance_after") or 0.0)
        except Exception:
            balance_after = 0.0
        direction = str(entry.get("direction") or "").strip().lower()
        if direction not in {"credit", "debit", "noop"}:
            direction = ""
        kind = _wallet_activity_kind(entry.get("reason"), entry.get("category"))
        sign = "+" if amount > 0 else "-" if amount < 0 else ""
        rows.append(
            {
                "id": str(entry.get("_id") or ""),
                "kind": kind,
                "label": _wallet_activity_label(kind),
                "direction": direction,
                "amount": amount,
                "amount_label": f"{sign}{_format_money(abs(amount))}" if amount else _format_money(0),
                "balance_after": balance_after,
                "balance_label": _format_money(balance_after),
                "created_at": _iso_datetime(entry.get("created_at")),
                "order_id": str(entry.get("order_id") or ""),
            }
        )
    return rows


async def account(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:account:read")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:account:read", limit=60)

    user_doc = await get_user(auth.user_id)
    if not isinstance(user_doc, dict):
        user_doc = {}
    balance = await get_user_wallet_balance(auth.user_id, auth.reseller_id)
    language = str(user_doc.get("language") or "en").strip().lower()
    try:
        recent_entries = await list_user_wallet_entries(auth.user_id, auth.reseller_id, limit=8)
        recent_activity = _wallet_activity_payload(recent_entries)
    except Exception:
        logger.exception("numbers api account wallet activity failed user=%s", auth.user_id)
        recent_activity = []

    return web.json_response(
        {
            "ok": True,
            "user": {
                "id": auth.user_id,
                "username": str(user_doc.get("username") or ""),
                "language": "ar" if language.startswith("ar") else "en",
                "joined_at": _iso_datetime(user_doc.get("created_at")),
            },
            "reseller": {"id": auth.reseller_id},
            "wallet": {
                "balance": float(balance),
                "currency": "USD",
                "balance_label": _format_money(balance),
            },
            "recent_activity": recent_activity,
        },
        headers=_response_headers(rate_limit),
    )


async def recharge_options(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:account:read")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:recharge", limit=60)

    balance = await get_user_wallet_balance(auth.user_id, auth.reseller_id)
    methods = await _recharge_methods_payload()
    return web.json_response(
        {
            "ok": True,
            "wallet": {
                "balance": float(balance),
                "currency": "USD",
                "balance_label": _format_money(balance),
            },
            "methods": methods,
            "actions": {
                "submit_recharge": _api_action(
                    "submit_recharge",
                    enabled=True,
                    endpoint="/api/v1/numbers/recharge/submit",
                    method="POST",
                    label="Submit recharge proof",
                )
            },
            "capabilities": {
                "submit_recharge_proof": True,
                "max_proof_bytes": _MAX_RECHARGE_PROOF_BYTES,
            },
        },
        headers=_response_headers(rate_limit),
    )


async def _parse_recharge_submit_form(request: web.Request) -> tuple[dict[str, str], bytes, str, str]:
    content_type = str(request.headers.get("Content-Type") or "").lower()
    if "multipart/form-data" not in content_type:
        raise web.HTTPBadRequest(text="multipart form required")
    fields: dict[str, str] = {}
    proof_bytes = b""
    proof_filename = ""
    proof_content_type = ""
    reader = await request.multipart()
    async for part in reader:
        name = str(getattr(part, "name", "") or "").strip()
        if not name:
            continue
        filename = str(getattr(part, "filename", "") or "").strip()
        if filename or name == "proof":
            proof_filename = filename or "recharge-proof"
            proof_content_type = str(getattr(part, "headers", {}).get("Content-Type") or "application/octet-stream")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = await part.read_chunk()
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_RECHARGE_PROOF_BYTES:
                    raise web.HTTPRequestEntityTooLarge(max_size=_MAX_RECHARGE_PROOF_BYTES, actual_size=total)
                chunks.append(chunk)
            proof_bytes = b"".join(chunks)
            continue
        fields[name] = (await part.text()).strip()
    return fields, proof_bytes, proof_filename, proof_content_type


async def submit_recharge(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:account:read")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:recharge:submit", limit=20)
    try:
        fields, proof_bytes, proof_filename, proof_content_type = await _parse_recharge_submit_form(request)
    except web.HTTPRequestEntityTooLarge:
        return _json_error("Proof file is too large.", status=413, code="proof_too_large", rate_limit=rate_limit)
    except web.HTTPException:
        raise
    except Exception:
        return _json_error("Could not read the recharge form.", status=400, code="invalid_form", rate_limit=rate_limit)

    lang = str(fields.get("language") or "ar").strip() or "ar"
    user_doc = await get_user(auth.user_id) or {
        "telegram_id": int(auth.user_id),
        "reseller_id": int(auth.reseller_id),
        "language": lang,
    }
    result = await shared_submit_recharge_request(
        auth={"user_id": int(auth.user_id), "reseller_id": int(auth.reseller_id), "user": {}},
        user_doc=user_doc,
        lang=lang,
        fields=fields,
        proof_bytes=proof_bytes,
        proof_filename=proof_filename,
        proof_content_type=proof_content_type,
        source="website",
        source_label="Phantom Website",
        text_fn=_text,
        money_fn=_format_money,
        compact_datetime_fn=lambda value: _iso_datetime(value) or "",
    )
    if not result.get("ok"):
        return _json_error(
            str(result.get("message") or "Recharge request failed."),
            status=400,
            code=str(result.get("code") or "recharge_failed"),
            rate_limit=rate_limit,
        )
    balance = await get_user_wallet_balance(auth.user_id, auth.reseller_id)
    result["wallet"] = {"balance": float(balance), "currency": "USD", "balance_label": _format_money(balance)}
    return web.json_response(result, headers=_response_headers(rate_limit))


async def support_options(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:account:read")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:support", limit=60)

    return web.json_response(
        {
            "ok": True,
            "categories": [{"key": key, "label": label} for key, label in _SUPPORT_CATEGORIES],
            "actions": {
                "submit_ticket": _api_action(
                    "submit_ticket",
                    enabled=False,
                    endpoint="/api/v1/numbers/support/ticket",
                    method="POST",
                    label="Submit support ticket",
                    reason="miniapp_only",
                )
            },
            "capabilities": {
                "submit_ticket": False,
                "reason": "Support ticket replies still depend on Telegram chat threads.",
            },
        },
        headers=_response_headers(rate_limit),
    )


async def quotes(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:quotes")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:quotes", limit=120)

    mode = str(request.query.get("mode") or "temp").strip().lower()
    service = resolve_canonical_service_key(str(request.query.get("service") or ""))
    country = str(request.query.get("country") or "none").strip() or "none"
    state = str(request.query.get("state") or "none").strip() or "none"

    if mode not in {"temp", "rental", "voice"}:
        return _json_error("Unsupported mode.", status=400, code="unsupported_mode", rate_limit=rate_limit)
    if not service:
        return _json_error("Missing service.", status=400, code="missing_service", rate_limit=rate_limit)
    if mode == "voice":
        country = "1"
    elif country != "1":
        state = "none"

    if mode == "rental":
        raw = await get_all_rental_prices(service, country, with_success_rates=False, ignore_balance=True)
        providers = normalize_rental_quote_rows(raw, service=service, country=country, state=state)
    elif mode == "voice":
        raw = await _voice_quote_prices(service, country, state)
        providers = normalize_voice_quote_rows(raw, service=service, country=country, state=state)
    else:
        raw = await get_all_prices(
            service,
            country,
            state,
            ignore_balance=True,
            with_success_rates=False,
            provider_codes=TEMP_QUOTE_PROVIDER_CODES,
        )
        providers = normalize_temp_quote_rows(raw, service=service, country=country, state=state)
    return web.json_response(
        {
            "ok": True,
            "mode": mode,
            "service": {"key": service, "label": get_service_display_name(service) or service},
            "country": country,
            "state": state,
            "providers": providers,
        },
        headers=_response_headers(rate_limit),
    )


async def country_suggestions(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:quotes")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:country-suggestions", limit=60)

    mode = str(request.query.get("mode") or "temp").strip().lower()
    service = resolve_canonical_service_key(str(request.query.get("service") or ""))
    limit = _parse_limit(request, default=10, maximum=20)

    if mode not in {"temp", "rental", "voice"}:
        return _json_error("Unsupported mode.", status=400, code="unsupported_mode", rate_limit=rate_limit)
    if not service:
        return web.json_response(
            {"ok": True, "mode": mode, "service": "", "countries": []},
            headers=_response_headers(rate_limit),
        )

    rows = await country_suggestions_for_service(mode, service, limit)
    return web.json_response(
        {
            "ok": True,
            "mode": mode,
            "service": service,
            "countries": rows,
        },
        headers=_response_headers(rate_limit),
    )


async def _voice_quote_prices(service: str, country: str, state: str) -> dict[str, dict]:
    raw = await get_all_voice_prices(service, country, state, ignore_balance=True)
    if _has_voice_buyable_offer(raw):
        return raw
    if str(service or "").strip().lower() == VOICE_GENERIC_SERVICE:
        return raw

    fallback = await get_all_voice_prices(VOICE_GENERIC_SERVICE, "1", state, ignore_balance=True)
    patched: dict[str, dict] = {}
    for code, info in (fallback or {}).items():
        if not isinstance(info, dict):
            continue
        item = dict(info)
        item["voice_fallback_service"] = True
        item["voice_requested_service"] = str(service or "")
        patched[str(code or "").strip().lower()] = item
    return patched


def _has_voice_buyable_offer(raw: dict[str, dict] | None) -> bool:
    return any(
        voice_provider_offer_is_buyable(str(code or "").strip().lower(), info)
        for code, info in (raw or {}).items()
        if isinstance(info, dict)
    )


def _parse_limit(request: web.Request, *, default: int = 20, maximum: int = 50) -> int:
    try:
        value = int(str(request.query.get("limit") or default))
    except Exception:
        value = default
    return max(1, min(value, maximum))


async def list_orders(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:read")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:read", limit=90)
    mode = str(request.query.get("mode") or "all").strip().lower()
    limit = _parse_limit(request)

    if mode not in {"all", "temp", "voice", "rental"}:
        return _json_error("Unsupported mode.", status=400, code="unsupported_mode", rate_limit=rate_limit)

    rows = []
    if mode in {"all", "temp", "voice"}:
        rows.extend(await list_user_recent_temp_and_voice_orders(auth.user_id, limit=limit))
    if mode in {"all", "rental"}:
        rows.extend(await list_user_rental_orders(auth.user_id, limit=limit))

    if mode == "temp":
        rows = [row for row in rows if str(row.get("number_mode") or "") == "temp"]
    elif mode == "voice":
        rows = [row for row in rows if str(row.get("number_mode") or "") == "voice"]

    rows.sort(key=lambda row: row.get("created_at") or datetime.min, reverse=True)
    rows = rows[:limit]

    return web.json_response(
        {
            "ok": True,
            "mode": mode,
            "orders": [public_order_payload(row) for row in rows],
        },
        headers=_response_headers(rate_limit),
    )


async def get_order_detail(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:read")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:read", limit=90)
    order_id = str(request.match_info.get("order_id") or "").strip()
    order = await get_user_number_order(order_id, auth.user_id, auth.reseller_id)
    if not isinstance(order, dict):
        return _json_error("Order was not found.", status=404, code="order_not_found", rate_limit=rate_limit)
    return web.json_response(
        {
            "ok": True,
            "order": public_order_payload(order),
        },
        headers=_response_headers(rate_limit),
    )


async def refresh_order(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:refresh")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:refresh", limit=60)
    order_id = str(request.match_info.get("order_id") or "").strip()
    order = await get_user_number_order(order_id, auth.user_id, auth.reseller_id)
    if not isinstance(order, dict):
        return _json_error("Order was not found.", status=404, code="order_not_found", rate_limit=rate_limit)
    try:
        result = await refresh_number_order(order)
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


async def resend_order(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:resend")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:resend", limit=30)
    order_id = str(request.match_info.get("order_id") or "").strip()
    order = await get_user_number_order(order_id, auth.user_id, auth.reseller_id)
    if not isinstance(order, dict):
        return _json_error("Order was not found.", status=404, code="order_not_found", rate_limit=rate_limit)
    try:
        result = await request_number_order_resend(order, user_id=auth.user_id, reseller_id=auth.reseller_id)
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


async def replace_order(request: web.Request) -> web.Response:
    return await _replacement_order(request, alternate_provider=False)


async def alternate_provider_order(request: web.Request) -> web.Response:
    return await _replacement_order(request, alternate_provider=True)


async def cancel_order(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:cancel")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:cancel", limit=20)
    order_id = str(request.match_info.get("order_id") or "").strip()
    order = await get_user_number_order(order_id, auth.user_id, auth.reseller_id)
    if not isinstance(order, dict):
        return _json_error("Order was not found.", status=404, code="order_not_found", rate_limit=rate_limit)
    try:
        result = await cancel_number_order(
            order,
            actor_user_id=auth.user_id,
            reason="numbers_api_user_cancel",
            source="numbers_api_cancel",
            allow_provider_terminal_refund=True,
            allow_empty_provider_refund=True,
        )
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


async def _replacement_order(request: web.Request, *, alternate_provider: bool) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:replace")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:replace", limit=20)
    order_id = str(request.match_info.get("order_id") or "").strip()
    order = await get_user_number_order(order_id, auth.user_id, auth.reseller_id)
    if not isinstance(order, dict):
        return _json_error("Order was not found.", status=404, code="order_not_found", rate_limit=rate_limit)
    try:
        body = await request.json()
    except Exception:
        body = {}
    idempotency_key = str(request.headers.get("Idempotency-Key") or (body or {}).get("idempotency_key") or "").strip()
    try:
        result = await request_replacement_order(
            order=order,
            user_id=auth.user_id,
            reseller_id=auth.reseller_id,
            idempotency_key=idempotency_key,
            lang=str((body or {}).get("language") or "en"),
            alternate_provider=alternate_provider,
        )
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


async def download_order_recording(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:read")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:read", limit=90)
    order_id = str(request.match_info.get("order_id") or "").strip()
    order = await get_user_number_order(order_id, auth.user_id, auth.reseller_id)
    if not isinstance(order, dict):
        return _json_error("Order was not found.", status=404, code="order_not_found", rate_limit=rate_limit)
    try:
        data = await download_voice_order_recording(order)
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)

    headers = {
        **_response_headers(rate_limit),
        "Content-Disposition": f'attachment; filename="{data["filename"]}"',
    }
    return web.Response(body=data["content"], content_type=data["content_type"], headers=headers)


async def rental_sms_order(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:rental")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:rental", limit=30)
    order = await _get_scoped_order(request, auth, rate_limit=rate_limit)
    if isinstance(order, web.Response):
        return order
    try:
        result = await rental_sms_state(order)
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


async def finish_rental(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:rental")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:rental", limit=30)
    order = await _get_scoped_order(request, auth, rate_limit=rate_limit)
    if isinstance(order, web.Response):
        return order
    try:
        result = await finish_rental_order(order)
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


async def renew_rental(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:rental")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:rental", limit=30)
    order = await _get_scoped_order(request, auth, rate_limit=rate_limit)
    if isinstance(order, web.Response):
        return order
    try:
        result = await renew_rental_order(
            order=order,
            user_id=auth.user_id,
            idempotency_key=str(request.headers.get("Idempotency-Key") or "").strip(),
        )
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


async def wake_rental(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:rental")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:rental", limit=30)
    order = await _get_scoped_order(request, auth, rate_limit=rate_limit)
    if isinstance(order, web.Response):
        return order
    try:
        result = await wake_rental_order(order)
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


async def rental_notes(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:rental")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:rental", limit=30)
    order = await _get_scoped_order(request, auth, rate_limit=rate_limit)
    if isinstance(order, web.Response):
        return order
    try:
        result = await rental_notes_state(order)
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


async def list_refund_reviews(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:support:review")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:support:review", limit=60)
    include_resolved = str(request.query.get("include_resolved") or "").strip().lower() in {"1", "true", "yes"}
    reseller_id = None if "*" in set(auth.scopes) else auth.reseller_id
    if reseller_id is None and str(request.query.get("reseller_id") or "").strip():
        try:
            reseller_id = int(str(request.query.get("reseller_id") or "0"))
        except Exception:
            return _json_error("Invalid reseller id.", status=400, code="invalid_reseller", rate_limit=rate_limit)
    rows = await list_api_temp_refund_support_reviews(
        limit=_parse_limit(request, default=50, maximum=200),
        reseller_id=reseller_id,
        include_resolved=include_resolved,
    )
    return web.json_response(
        {
            "ok": True,
            "reviews": [_refund_review_payload(row) for row in rows],
        },
        headers=_response_headers(rate_limit),
    )


async def resolve_refund_review(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:support:review")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:support:review", limit=60)
    order_id = str(request.match_info.get("order_id") or "").strip()
    try:
        body = await request.json()
    except Exception:
        body = {}
    resolution = str((body or {}).get("resolution") or "").strip()
    if not resolution:
        return _json_error("Missing resolution.", status=400, code="missing_resolution", rate_limit=rate_limit)
    reseller_id = None if "*" in set(auth.scopes) else auth.reseller_id
    order = await resolve_api_temp_refund_support_review(
        order_id=order_id,
        actor_user_id=auth.user_id,
        reseller_id=reseller_id,
        resolution=resolution,
        notes=str((body or {}).get("notes") or "").strip(),
    )
    if not isinstance(order, dict):
        return _json_error("Review was not found.", status=404, code="review_not_found", rate_limit=rate_limit)
    return web.json_response(
        {
            "ok": True,
            "review": _refund_review_payload(order),
        },
        headers=_response_headers(rate_limit),
    )


async def list_provider_webhook_audit_events(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:support:review")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:support:review", limit=60)
    rows = await list_provider_webhook_events(
        provider=str(request.query.get("provider") or "").strip(),
        status=str(request.query.get("status") or "").strip(),
        limit=_parse_limit(request, default=50, maximum=200),
    )
    return web.json_response({"ok": True, "events": rows}, headers=_response_headers(rate_limit))


async def provider_readiness_status(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:support:review")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:support:review", limit=60)
    include_events = str(request.query.get("include_events") or "1").strip().lower() not in {"0", "false", "no"}
    rows = provider_readiness_rows()
    if include_events:
        enriched = []
        for row in rows:
            provider = str(row.get("provider") or "").strip()
            events = await list_provider_webhook_events(provider=provider, limit=1)
            item = dict(row)
            item["last_webhook_event"] = events[0] if events else None
            item["real_webhook_processed"] = bool(events and str(events[0].get("status") or "") == "processed")
            enriched.append(item)
        rows = enriched
    return web.json_response({"ok": True, "providers": rows}, headers=_response_headers(rate_limit))


async def replay_provider_webhook_audit_event(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:support:review")
    rate_limit = await _check_rate_limit(auth, bucket="numbers:support:review", limit=60)
    event_id = str(request.match_info.get("event_id") or "").strip()
    result = await replay_provider_webhook_event(event_id)
    if not result.get("ok") and str(result.get("reason") or "") == "event_not_found":
        return _json_error("Provider webhook event was not found.", status=404, code="event_not_found", rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


def _refund_review_payload(order: dict) -> dict:
    return {
        "id": str(order.get("_id") or ""),
        "status": str(order.get("temp_refund_support_review_status") or "open"),
        "reason": str(order.get("temp_refund_support_review_reason") or ""),
        "reviewed_at": _iso_datetime(order.get("temp_refund_support_review_at")),
        "resolved_at": _iso_datetime(order.get("temp_refund_support_review_resolved_at")),
        "resolved_by": order.get("temp_refund_support_review_resolved_by"),
        "resolution": str(order.get("temp_refund_support_review_resolution") or ""),
        "notes": str(order.get("temp_refund_support_review_notes") or ""),
        "order": public_order_payload(order),
    }


async def _get_scoped_order(
    request: web.Request,
    auth: ApiAuthContext,
    *,
    rate_limit: ApiRateLimitDecision,
) -> dict | web.Response:
    order_id = str(request.match_info.get("order_id") or "").strip()
    order = await get_user_number_order(order_id, auth.user_id, auth.reseller_id)
    if not isinstance(order, dict):
        return _json_error("Order was not found.", status=404, code="order_not_found", rate_limit=rate_limit)
    return order


def _response_headers(rate_limit: ApiRateLimitDecision | None = None) -> dict[str, str]:
    headers = dict(_NO_STORE_HEADERS)
    if rate_limit is not None:
        headers.update(rate_limit_headers(rate_limit))
    return headers


def _json_error(
    message: str,
    *,
    status: int,
    code: str,
    rate_limit: ApiRateLimitDecision | None = None,
) -> web.Response:
    headers = _response_headers(rate_limit)
    if rate_limit is not None and status == 429:
        headers["Retry-After"] = str(retry_after_seconds(rate_limit))
    return web.json_response(
        {
            "ok": False,
            "code": code,
            "error": message,
            "message": message,
        },
        status=status,
        headers=headers,
    )


async def _check_rate_limit(auth: ApiAuthContext, *, bucket: str, limit: int) -> ApiRateLimitDecision:
    try:
        return await check_api_rate_limit(auth, bucket=bucket, limit=limit)
    except ApiRateLimitExceeded as exc:
        raise web.HTTPTooManyRequests(
            text="rate limit exceeded",
            headers={
                **_response_headers(exc.decision),
                "Retry-After": str(retry_after_seconds(exc.decision)),
            },
        ) from exc


async def create_order(request: web.Request) -> web.Response:
    auth = await require_api_auth(request, "numbers:orders:create")
    await require_website_purchase_ready(request)
    rate_limit = await _check_rate_limit(auth, bucket="numbers:orders:create", limit=30)

    try:
        body = await request.json()
    except Exception:
        body = {}

    quote_token = str((body or {}).get("quote_token") or "").strip()
    if not quote_token:
        return _json_error("Missing quote token.", status=400, code="missing_quote", rate_limit=rate_limit)

    idempotency_key = str(request.headers.get("Idempotency-Key") or (body or {}).get("idempotency_key") or "").strip()
    try:
        result = await create_number_order_from_quote(
            user_id=auth.user_id,
            reseller_id=auth.reseller_id,
            quote_token=quote_token,
            idempotency_key=idempotency_key,
            lang=str((body or {}).get("language") or "en"),
        )
    except NumbersOrderError as exc:
        return _json_error(exc.message, status=exc.status, code=exc.code, rate_limit=rate_limit)
    return web.json_response(result, headers=_response_headers(rate_limit))


def register_numbers_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/v1/numbers/health", health)
    app.router.add_get("/api/v1/numbers/docs", api_docs)
    app.router.add_get("/api/v1/numbers/openapi.json", openapi_schema)
    app.router.add_get("/api/v1/numbers/catalog/bootstrap", catalog_bootstrap)
    app.router.add_get("/api/v1/numbers/country-suggestions", country_suggestions)
    app.router.add_get("/api/v1/numbers/account", account)
    app.router.add_get("/api/v1/numbers/recharge", recharge_options)
    app.router.add_post("/api/v1/numbers/recharge/submit", submit_recharge)
    app.router.add_get("/api/v1/numbers/support", support_options)
    app.router.add_get("/api/v1/numbers/quotes", quotes)
    app.router.add_get("/api/v1/numbers/orders", list_orders)
    app.router.add_get("/api/v1/numbers/orders/{order_id}", get_order_detail)
    app.router.add_post("/api/v1/numbers/orders", create_order)
    app.router.add_post("/api/v1/numbers/orders/{order_id}/refresh", refresh_order)
    app.router.add_post("/api/v1/numbers/orders/{order_id}/resend", resend_order)
    app.router.add_post("/api/v1/numbers/orders/{order_id}/replace", replace_order)
    app.router.add_post("/api/v1/numbers/orders/{order_id}/alternate", alternate_provider_order)
    app.router.add_post("/api/v1/numbers/orders/{order_id}/cancel", cancel_order)
    app.router.add_get("/api/v1/numbers/orders/{order_id}/recording", download_order_recording)
    app.router.add_post("/api/v1/numbers/orders/{order_id}/rental/sms", rental_sms_order)
    app.router.add_post("/api/v1/numbers/orders/{order_id}/rental/finish", finish_rental)
    app.router.add_post("/api/v1/numbers/orders/{order_id}/rental/renew", renew_rental)
    app.router.add_post("/api/v1/numbers/orders/{order_id}/rental/wake", wake_rental)
    app.router.add_post("/api/v1/numbers/orders/{order_id}/rental/notes", rental_notes)
    app.router.add_get("/api/v1/numbers/ops/refund-reviews", list_refund_reviews)
    app.router.add_post("/api/v1/numbers/ops/refund-reviews/{order_id}/resolve", resolve_refund_review)
    app.router.add_get("/api/v1/numbers/ops/provider-readiness", provider_readiness_status)
    app.router.add_get("/api/v1/numbers/ops/provider-webhook-events", list_provider_webhook_audit_events)
    app.router.add_post("/api/v1/numbers/ops/provider-webhook-events/{event_id}/replay", replay_provider_webhook_audit_event)
