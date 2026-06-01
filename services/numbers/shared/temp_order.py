import html
import re
from datetime import UTC, datetime
from typing import Any

from services.numbers.data.countries import COUNTRIES_LIST
from utils.provider_alias import provider_public_id
from utils.translations import t

TEMP_WAIT_TIMEOUT_SEC = 900
TEMP_PROVIDER_SAFETY_BUFFER_SEC = 60
TEMP_CANCEL_AFTER_SEC = 180
TEMP_REFRESH_COOLDOWN_SEC = 60
TEMP_REFUND_RETRY_WINDOW_SEC = 900
TEMP_REUSE_WARRANTY_FALLBACK_SEC = 900
TEMP_REUSE_WARRANTY_SEC_BY_PROVIDER: dict[str, int] = {}
TEMP_POLL_INTERVALS = {
    "nonvoip": 6,
    "smspool": 8,
    "textverified": 8,
    "herosms": 7,
    "telabot": 10,
}

_COUNTRY_NAME_BY_CODE = {
    str(item.get("code") or "").strip(): str(item.get("name") or "").strip()
    for item in COUNTRIES_LIST
    if str(item.get("code") or "").strip()
}

_TEMP_WARRANTY_SECONDS_KEYS = (
    "reuse_warranty_sec",
    "warranty_sec",
    "expires_in",
    "expiresin",
    "expires_in_seconds",
    "expiresinseconds",
    "expiration_seconds",
    "ttl",
    "ttl_sec",
    "time_to_live",
    "valid_for_sec",
    "validforsec",
)
_TEMP_WARRANTY_EPOCH_KEYS = (
    "expires_at",
    "expiresat",
    "expiration_at",
    "expirationat",
    "valid_until",
    "validuntil",
    "expire_at",
    "expireat",
)
_TEMP_WARRANTY_TEXT_KEYS = (
    "reuse_warranty",
    "warranty",
    "valid_for",
    "expires_in_human",
)
_EXPECTED_PROVIDER_FAILURE_MARKERS = (
    "out of stock",
    "unavailable",
    "insufficient balance",
    "balance_error",
    "no numbers",
    "not enough balance",
    "service not available",
    "no free phones",
    "temporarily unavailable",
)


def _country_display_name(country_value: Any, *, country_name: str | None = None) -> str:
    direct_name = str(country_name or "").strip()
    if direct_name:
        return direct_name
    raw = str(country_value or "").strip()
    if not raw:
        return "-"
    code = "".join(ch for ch in raw if ch.isdigit())
    if code and code in _COUNTRY_NAME_BY_CODE:
        return _COUNTRY_NAME_BY_CODE[code]
    return raw


def _split_number_for_copy(raw_number: str | None, country_code: str | None) -> tuple[str | None, str]:
    raw = str(raw_number or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit()) or raw
    cc = "".join(ch for ch in str(country_code or "").strip() if ch.isdigit())
    if cc and 1 <= len(cc) <= 4 and isinstance(digits, str) and digits:
        if digits.startswith(cc) and len(digits) > len(cc):
            local_digits = digits[len(cc):]
        else:
            local_digits = digits
        if local_digits:
            return cc, local_digits
    return None, raw if raw else str(digits)


def _format_number_for_copy_html(raw_number: str | None, country_code: str | None) -> str:
    cc, local = _split_number_for_copy(raw_number, country_code)
    if cc:
        return f"+{cc} <code>{html.escape(local)}</code>"
    return f"<code>{html.escape(local)}</code>"


def _format_number_for_copy_text(raw_number: str | None, country_code: str | None) -> str:
    cc, local = _split_number_for_copy(raw_number, country_code)
    if cc:
        return f"+{cc} {local}"
    return local


def _bool_text(value: bool, lang: str) -> str:
    return t(lang, "yes") if bool(value) else t(lang, "no")


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_utc_datetime(value) -> datetime | None:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _coerce_utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _to_utc_datetime(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _to_utc_datetime(parsed)


def _seconds_between(later: datetime | None, earlier: datetime | None) -> int | None:
    later_dt = _to_utc_datetime(later)
    earlier_dt = _to_utc_datetime(earlier)
    if not later_dt or not earlier_dt:
        return None
    return int((later_dt - earlier_dt).total_seconds())


def _seconds_left_until(value: datetime | None) -> int:
    target = _to_utc_datetime(value)
    if not target:
        return 0
    return max(0, int((target - _utc_now()).total_seconds()))


def _format_wait_time_short(seconds: int) -> str:
    sec = max(0, int(seconds or 0))
    minutes = (sec + 59) // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m" if mins else f"{hours}h"


def _provider_default_reuse_warranty_sec(provider_code: str | None) -> int:
    code = str(provider_code or "").strip().lower()
    return int(TEMP_REUSE_WARRANTY_SEC_BY_PROVIDER.get(code, TEMP_REUSE_WARRANTY_FALLBACK_SEC))


def _normalize_warranty_sec(value: int | float | None) -> int | None:
    if value is None:
        return None
    sec = _as_int(value, 0)
    if sec <= 0:
        return None
    return max(60, min(sec, 7 * 24 * 3600))


def _seconds_until_timestamp(raw_value, now_ts: float) -> int | None:
    if raw_value in (None, ""):
        return None
    ts_value: float | None = None
    if isinstance(raw_value, (int, float)):
        ts_value = float(raw_value)
    elif isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return None
        if re.fullmatch(r"-?\d+(\.\d+)?", text):
            try:
                ts_value = float(text)
            except ValueError:
                ts_value = None
        else:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                ts_value = parsed.timestamp()
            except ValueError:
                ts_value = None
    if ts_value is None:
        return None
    if ts_value > 10_000_000_000:
        ts_value = ts_value / 1000.0
    delta = int(ts_value - now_ts)
    if delta <= 0:
        return None
    return delta


def _seconds_from_text(raw_value) -> int | None:
    text = str(raw_value or "").strip().lower()
    if not text:
        return None
    patterns = (
        (r"(\d+)\s*(?:seconds?|secs?|s)\b", 1),
        (r"(\d+)\s*(?:minutes?|mins?|m)\b", 60),
        (r"(\d+)\s*(?:hours?|hrs?|h)\b", 3600),
        (r"(\d+)\s*(?:days?|d)\b", 24 * 3600),
    )
    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            value = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value * multiplier
    return None


def _extract_explicit_reuse_warranty_sec(payload) -> int | None:
    if payload in (None, ""):
        return None
    now_ts = _utc_now().timestamp()
    queue = [payload]
    seen: set[int] = set()

    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            current_id = id(current)
            if current_id in seen:
                continue
            seen.add(current_id)
            for key, value in current.items():
                key_norm = str(key or "").strip().lower()
                if key_norm in _TEMP_WARRANTY_SECONDS_KEYS:
                    sec = _normalize_warranty_sec(_as_int(value, 0))
                    if sec:
                        return sec
                if key_norm in _TEMP_WARRANTY_EPOCH_KEYS:
                    sec = _normalize_warranty_sec(_seconds_until_timestamp(value, now_ts))
                    if sec:
                        return sec
                if key_norm in _TEMP_WARRANTY_TEXT_KEYS:
                    sec = _normalize_warranty_sec(_seconds_from_text(value))
                    if sec:
                        return sec
                if isinstance(value, (dict, list)):
                    queue.append(value)
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)):
                    queue.append(item)

    return None


def _resolve_reuse_warranty_sec(provider_code: str | None, buy_response: dict | None = None) -> int:
    return _provider_default_reuse_warranty_sec(provider_code)


def _warranty_minutes_text_value(warranty_sec: int | None) -> int:
    sec = _normalize_warranty_sec(warranty_sec)
    if not sec:
        sec = TEMP_REUSE_WARRANTY_FALLBACK_SEC
    return max(1, (int(sec) + 59) // 60)


def _order_reuse_warranty_sec(order: dict | None) -> int:
    order = order or {}
    sec = _normalize_warranty_sec(_as_int(order.get("temp_reuse_warranty_sec"), 0))
    if sec:
        return sec

    created_at = _to_utc_datetime(order.get("created_at"))
    warranty_until = _to_utc_datetime(order.get("temp_reuse_warranty_until"))
    if created_at and warranty_until:
        derived = _normalize_warranty_sec(int((warranty_until - created_at).total_seconds()))
        if derived:
            return derived

    fallback = _provider_default_reuse_warranty_sec(order.get("provider"))
    return int(_normalize_warranty_sec(fallback) or TEMP_REUSE_WARRANTY_FALLBACK_SEC)


def _temp_reuse_policy_text(lang: str, warranty_sec: int | None) -> str:
    minutes = _warranty_minutes_text_value(warranty_sec)
    line_1 = t(lang, "temp_reuse_warranty_line").format(minutes=minutes)
    line_2 = t(lang, "temp_reuse_resend_note")
    line_3 = t(lang, "temp_reuse_cost_note")
    return f"{line_1}\n{line_2}\n{line_3}"


def _temp_waiting_text(
    *,
    lang: str,
    provider_code: str,
    number: str,
    country_code: str | None,
    interval_sec: int,
    elapsed_sec: int = 0,
    reuse_warranty_sec: int | None = None,
    service_name: str | None = None,
) -> str:
    provider_public = provider_public_id(provider_code)
    provider_label = provider_public
    if provider_public.upper().startswith("S") and provider_public[1:].isdigit():
        provider_label = f"Server{provider_public[1:]}"

    raw_number = str(number or "").strip()
    digits = "".join(ch for ch in raw_number if ch.isdigit()) or raw_number
    cc = "".join(ch for ch in str(country_code or "").strip() if ch.isdigit())
    if cc and 1 <= len(cc) <= 4 and isinstance(digits, str) and digits:
        if digits.startswith(cc) and len(digits) > len(cc):
            local_digits = digits[len(cc):]
        else:
            local_digits = digits
        pretty_number = f"+{cc} {local_digits}".strip()
    else:
        pretty_number = raw_number if raw_number else str(digits)

    shown_elapsed = min(max(0, int(elapsed_sec or 0)), TEMP_CANCEL_AFTER_SEC)
    refresh_count = max(0, int(shown_elapsed // 30))
    number_mono = _format_number_for_copy_html(pretty_number, country_code)
    text = t(lang, "temp_waiting_code").format(
        provider=provider_label,
        number=number_mono,
        refreshes=refresh_count,
    )
    details = [
        text,
        f"{t(lang, 'country_label')}: {_country_display_name(country_code)}",
    ]
    if service_name:
        details.append(f"{t(lang, 'service_label')}: {html.escape(str(service_name))}")
    if _normalize_warranty_sec(reuse_warranty_sec) and int(elapsed_sec or 0) >= int(_normalize_warranty_sec(reuse_warranty_sec) or 0):
        details.append(t(lang, "temp_reuse_expired"))
    else:
        details.append(_temp_reuse_policy_text(lang, reuse_warranty_sec))
    return "\n".join(details)


def _temp_code_received_text(lang: str, code: str, order: dict | None = None) -> str:
    order = order or {}
    number_value = _format_number_for_copy_html(
        str(order.get("provider_number") or "").strip(),
        str(order.get("temp_country") or "").strip(),
    )
    service_value = str(order.get("temp_service_key") or order.get("service_id") or "-")
    return "\n".join(
        [
            f"📱 {t(lang, 'number_label')}: {number_value}",
            f"🧩 {t(lang, 'service_label')}: {html.escape(service_value)}",
            f"{t(lang, 'country_label')}: {_country_display_name(order.get('temp_country'))}",
            f"{t(lang, 'provider_label')}: {provider_public_id(str(order.get('provider') or ''))}",
            _temp_reuse_policy_text(lang, _order_reuse_warranty_sec(order)),
        ]
    )


def _poll_interval_for_provider(provider_code: str) -> int:
    return int(TEMP_POLL_INTERVALS.get(str(provider_code or "").lower(), 8))


def _parse_provider_dt(raw_value) -> datetime | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    candidates = (
        text,
        text.replace("Z", "+00:00"),
        text.replace(" ", "T"),
        text.replace(" ", "T").replace("Z", "+00:00"),
    )
    for item in candidates:
        try:
            dt = datetime.fromisoformat(item)
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            continue
    return None


def _extract_provider_wait_timeout_sec(buy_res: dict | None) -> int | None:
    if not isinstance(buy_res, dict):
        return None
    raw = buy_res.get("raw")
    if not isinstance(raw, dict):
        return None
    started = _parse_provider_dt(raw.get("activationTime"))
    ended = _parse_provider_dt(raw.get("activationEndTime"))
    if not started or not ended:
        return None
    duration = int((ended - started).total_seconds())
    if duration <= 0:
        return None
    return max(60, duration - TEMP_PROVIDER_SAFETY_BUFFER_SEC)


def _order_temp_timeout_sec(order: dict | None) -> int:
    if not isinstance(order, dict):
        return TEMP_WAIT_TIMEOUT_SEC
    try:
        sec = int(order.get("temp_wait_timeout_sec") or 0)
    except (TypeError, ValueError):
        sec = 0
    return sec if sec > 0 else TEMP_WAIT_TIMEOUT_SEC


def _temp_elapsed_sec(order: dict, now: datetime | None = None) -> int:
    now_dt = _to_utc_datetime(now) or _utc_now()
    started_at = _to_utc_datetime(order.get("temp_wait_started_at") or order.get("created_at")) or now_dt
    return max(0, int((now_dt - started_at).total_seconds()))


def _temp_refresh_cooldown_left(order: dict, now: datetime | None = None) -> int:
    now_dt = _to_utc_datetime(now) or _utc_now()
    last_refresh = _to_utc_datetime(order.get("temp_last_refresh_at"))
    if not last_refresh:
        return 0
    delta = int((now_dt - last_refresh).total_seconds())
    return max(0, TEMP_REFRESH_COOLDOWN_SEC - delta)


def _is_temp_order_active_for_trust_gate(order: dict | None, now: datetime | None = None) -> bool:
    order = order or {}
    state = str(order.get("temp_wait_state") or "").strip().lower()
    if state not in {"waiting", "waiting_for_call", "waiting_for_recording", "code_received", "call_received", "refund_pending"}:
        return False

    elapsed = _temp_elapsed_sec(order, now=now)
    timeout_sec = _order_temp_timeout_sec(order)
    reuse_warranty_sec = _order_reuse_warranty_sec(order)

    if state in {"code_received", "call_received"}:
        return elapsed < max(timeout_sec, reuse_warranty_sec)

    if state == "refund_pending":
        return elapsed < max(timeout_sec, TEMP_REFUND_RETRY_WINDOW_SEC)

    return elapsed < timeout_sec


def _safe_code_text(value: str) -> str:
    return str(value or "").strip().replace("\n", " ")[:200]


def _clean_provider_error_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _provider_error_text(raw) -> str:
    if isinstance(raw, dict):
        for key in ("errorDescription", "message", "error", "detail"):
            cleaned = _clean_provider_error_text(raw.get(key))
            if cleaned:
                return cleaned
        pools = raw.get("pools")
        if isinstance(pools, dict):
            parts: list[str] = []
            for pool_name, pool_info in pools.items():
                if isinstance(pool_info, dict):
                    msg = _clean_provider_error_text(pool_info.get("message"))
                    if msg:
                        parts.append(f"{pool_name}: {msg}")
            if parts:
                return " | ".join(parts)
        return _clean_provider_error_text(str(raw)) or "provider_error"
    cleaned = _clean_provider_error_text(raw)
    return cleaned or "provider_error"


def _is_expected_provider_failure(raw) -> bool:
    text = _provider_error_text(raw).lower()
    if not text:
        return False
    return any(marker in text for marker in _EXPECTED_PROVIDER_FAILURE_MARKERS)


def _extract_new_sms_code(messages: list, seen_codes: set[str]) -> str | None:
    for raw in messages or []:
        code = _safe_code_text(str(raw))
        if not code:
            continue
        if code in seen_codes:
            continue
        return code
    return None


def _temp_order_has_received_code(order: dict | None) -> bool:
    order = order or {}
    if _as_int(order.get("temp_codes_count"), 0) > 0:
        return True
    if order.get("temp_first_sms_at"):
        return True
    if str(order.get("temp_last_code") or "").strip():
        return True
    codes = order.get("temp_codes") or []
    if isinstance(codes, list):
        for code in codes:
            if str(code or "").strip():
                return True
    return False


def _is_retryable_provider_cancel(raw: Any) -> bool:
    text = _provider_error_text(raw).lower()
    if not text:
        return False
    return (
        "early_cancel_denied" in text
        or "early cancel denied" in text
        or "try again later" in text
        or "wait" in text
    )
