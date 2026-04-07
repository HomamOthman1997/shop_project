import asyncio
import hashlib
import json
import os
import re
import time
from collections import defaultdict, deque
from typing import Any

from aiogram import Router, types
from rapidfuzz import fuzz

from services.numbers.core.session_manager import SessionManager
from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.data.states_us import STATES_LIST
from services.numbers.data import tv_area_codes
from services.numbers import service_map as service_registry
from services.numbers.service_map import SERVICE_MAP
from services.numbers.service_icons import (
    get_generic_service_icon_url,
    get_no_icon_url,
    resolve_country_icon_url,
    resolve_service_icon_url,
    resolve_state_icon_url,
)
from utils.translations import t

router = Router()

USAGE_PATHS = [
    os.path.join(os.path.dirname(__file__), "../../../data/usage_stats.json"),
    os.path.join(os.path.dirname(__file__), "../../../data/usage.json"),
]

_search_hits = defaultdict(lambda: deque(maxlen=10))
_search_last_seen: dict[int, float] = {}
_search_last_gc_at: float = 0.0
_SEARCH_HITS_USER_TTL_SEC = 900
_SEARCH_HITS_GC_EVERY_SEC = 60
_countries_cache: list[dict[str, Any]] = []
_countries_cached_at: float = 0.0
_countries_ttl_sec: int = 3600
_countries_lock = asyncio.Lock()
_ANY_COUNTRY_CODE = "any"
_SERVICE_NOT_LISTED_KEY = "servicenotlisted"
_TV_ALLOWED_STATES = set(tv_area_codes.DATA.keys())
_DEFAULT_QUICK_COUNTRY_ISO = ("US", "GB", "DE", "FR")
_INLINE_RESULT_ICON_VERSION = "ic2"
_INLINE_CACHE_TIME_SEC = 12


def _load_usage():
    for path in USAGE_PATHS:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}


USAGE_DATA = _load_usage()


def _usage(key: str) -> int:
    return int(USAGE_DATA.get(key.lower(), 0))


def _throttled(user_id: int, limit: int = 3, window_seconds: int = 1) -> bool:
    global _search_last_gc_at
    now = time.time()
    _search_last_seen[user_id] = now
    if now - _search_last_gc_at >= _SEARCH_HITS_GC_EVERY_SEC:
        stale_before = now - _SEARCH_HITS_USER_TTL_SEC
        stale_users = [uid for uid, ts in _search_last_seen.items() if ts < stale_before]
        for uid in stale_users:
            _search_last_seen.pop(uid, None)
            _search_hits.pop(uid, None)
        _search_last_gc_at = now
    bucket = _search_hits[user_id]
    while bucket and (now - bucket[0]) > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


def _boost_sort(items, key_func, query, usage_func, limit=50):
    scored = []
    q = (query or "").strip().lower()
    for item in items:
        name = key_func(item).lower()
        score = fuzz.partial_ratio(q, name) if q else 0
        scored.append((score, usage_func(name), item))
    scored.sort(key=lambda x: (-x[0], -x[1], key_func(x[2]).lower()))
    return [x[2] for x in scored[:limit]]


def _safe_result_id(prefix: str, source: str) -> str:
    digest = hashlib.blake2s((source or "").encode("utf-8"), digest_size=12).hexdigest()
    return f"{prefix}_{digest}"


def _country_aliases(values: list[str] | tuple[str, ...] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in (values or []):
        token = str(value or "").strip()
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _strip_prefix_tokens(text: str, token: str) -> str:
    source = (text or "").strip()
    prefix = token.strip().lower()
    while source.lower().startswith(prefix):
        source = source[len(prefix):].lstrip()
    return source


def _normalize_search_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _ordered_match(query: str, text: str) -> bool:
    q = _normalize_search_text(query)
    t = _normalize_search_text(text)
    if not q:
        return True
    return q in t


def _service_search_tokens(key: str, info: dict[str, Any]) -> list[str]:
    if SERVICE_MAP is service_registry.SERVICE_MAP:
        registry_tokens = list(service_registry.get_service_search_tokens(key))
        if registry_tokens:
            return registry_tokens
    tokens: list[str] = []
    display_name = str(info.get("display_name", key) or "").strip()
    if display_name:
        tokens.append(display_name)
    canonical = str(key or "").strip()
    if canonical:
        tokens.append(canonical)
    for alias in info.get("aliases") or []:
        alias_text = str(alias or "").strip()
        if alias_text:
            tokens.append(alias_text)
    seen: set[str] = set()
    deduped: list[str] = []
    for token in tokens:
        norm = _normalize_search_text(token)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        deduped.append(token)
    return deduped


def _service_items() -> list[tuple[str, dict[str, Any]]]:
    if SERVICE_MAP is service_registry.SERVICE_MAP:
        return service_registry.iter_service_entries()
    return [
        (str(key), dict(info))
        for key, info in SERVICE_MAP.items()
        if isinstance(key, str) and isinstance(info, dict)
    ]


def _iso_to_flag(iso: str | None) -> str:
    code = (iso or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    base = ord("A")
    return "".join(chr(0x1F1E6 + (ord(ch) - base)) for ch in code)


def _country_inline_title(item: dict[str, Any], query: str = "") -> str:
    iso = str(item.get("iso") or "").strip().upper()
    name = str(item.get("name") or "").strip()
    normalized_query = _normalize_search_text(query)
    if iso == "US" and normalized_query in {"us", "usa"}:
        flag = _iso_to_flag(iso)
        return f"USA {flag}".strip()
    return name or iso or str(item.get("code") or "").strip()


def _state_inline_title(code: str, name: str) -> str:
    return str(name or "").strip()


def _repair_mojibake_text(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("âš¡", "⚡")
    if not any(ch in text for ch in ("Ã", "Â", "Ø", "Ù", "â")):
        return text
    try:
        repaired = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore").strip()
    except Exception:
        return text
    if repaired and not any(ch in repaired for ch in ("Ã", "Â", "Ø", "Ù", "â")):
        return repaired
    return text


def _normalize_country_row(row: dict[str, Any]) -> dict[str, Any] | None:
    code = _repair_mojibake_text(str(row.get("code") or "")).strip()
    name = _repair_mojibake_text(str(row.get("name") or "")).strip()
    iso = _repair_mojibake_text(str(row.get("iso") or "")).strip().upper()
    if not code or not name:
        return None
    aliases_raw = row.get("aliases") if isinstance(row.get("aliases"), list) else None
    aliases = _country_aliases([_repair_mojibake_text(str(x or "")) for x in (aliases_raw or [])])
    if iso and iso.lower() not in {a.lower() for a in aliases}:
        aliases.append(iso)
    if name.lower() not in {a.lower() for a in aliases}:
        aliases.append(name)
    return {
        "code": code,
        "iso": iso,
        "name": name,
        "aliases": aliases,
    }


def _base_countries() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in COUNTRIES_LIST:
        normalized = _normalize_country_row(row)
        if normalized:
            items.append(normalized)
    return items


def _merge_countries(primary: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for row in primary:
        by_code[str(row.get("code"))] = dict(row)

    for row in extra:
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        if code not in by_code:
            by_code[code] = dict(row)
            continue
        current = by_code[code]
        if not current.get("iso") and row.get("iso"):
            current["iso"] = row["iso"]
        aliases = _country_aliases(list(current.get("aliases") or []) + list(row.get("aliases") or []))
        current["aliases"] = aliases
        if not current.get("name") and row.get("name"):
            current["name"] = row["name"]
        by_code[code] = current

    merged = list(by_code.values())
    merged.sort(key=lambda x: str(x.get("name") or "").lower())
    return merged


async def _fetch_smspool_countries() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        session = await SessionManager.get_session()
        async with session.get("https://api.smspool.net/country/retrieve_all", timeout=20) as resp:
            if resp.status != 200:
                return out
            data = await resp.json(content_type=None)
            if not isinstance(data, list):
                return out
            for row in data:
                if not isinstance(row, dict):
                    continue
                code = _repair_mojibake_text(str(row.get("ID") or row.get("id") or "")).strip()
                name = _repair_mojibake_text(str(row.get("name") or "")).strip()
                iso = _repair_mojibake_text(str(row.get("short_name") or row.get("iso") or "")).strip().upper()
                aliases = [
                    name,
                    iso,
                    _repair_mojibake_text(str(row.get("cc") or "")).strip(),
                    _repair_mojibake_text(str(row.get("region") or "")).strip(),
                ]
                normalized = _normalize_country_row(
                    {
                        "code": code,
                        "iso": iso,
                        "name": name,
                        "aliases": aliases,
                    }
                )
                if normalized:
                    out.append(normalized)
    except Exception:
        return out
    return out


async def _get_search_countries() -> list[dict[str, Any]]:
    global _countries_cache, _countries_cached_at
    now = time.time()
    if _countries_cache and (now - _countries_cached_at) < _countries_ttl_sec:
        return list(_countries_cache)

    async with _countries_lock:
        now = time.time()
        if _countries_cache and (now - _countries_cached_at) < _countries_ttl_sec:
            return list(_countries_cache)
        base = _base_countries()
        dynamic = await _fetch_smspool_countries()
        merged = _merge_countries(base, dynamic)
        _countries_cache = merged
        _countries_cached_at = now
        return list(_countries_cache)


def _country_text_blob(item: dict[str, Any]) -> str:
    parts = [
        str(item.get("name") or ""),
        str(item.get("iso") or ""),
        str(item.get("code") or ""),
    ] + list(item.get("aliases") or [])
    return " ".join(p for p in parts if p).lower()


def _search_countries(items: list[dict[str, Any]], query: str, limit: int = 50) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    q_norm = _normalize_search_text(q)
    scored: list[tuple[float, int, str, dict[str, Any]]] = []
    for item in items:
        name = str(item.get("name") or "")
        blob = _country_text_blob(item)
        if q_norm and not _ordered_match(q, blob):
            continue
        if q:
            score = max(
                float(fuzz.partial_ratio(q, blob)),
                float(fuzz.partial_ratio(q, name.lower())),
            )
        else:
            score = 0.0
        usage = _usage(name) + _usage(str(item.get("iso") or ""))
        scored.append((score, usage, name.lower(), item))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [x[3] for x in scored[:limit]]


def _country_usage_score(item: dict[str, Any]) -> int:
    name = str(item.get("name") or "")
    iso = str(item.get("iso") or "").upper()
    code = str(item.get("code") or "")
    aliases = [str(x) for x in (item.get("aliases") or []) if str(x).strip()]
    total = _usage(name) + _usage(iso) + _usage(code)
    for alias in aliases:
        total += _usage(alias)
    return int(total)


def _state_usage_score(item: dict[str, Any]) -> int:
    name = str(item.get("name") or "")
    code = str(item.get("code") or "").upper()
    return int(_usage(name) + _usage(code))


def _top_quick_countries(items: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    by_iso: dict[str, dict[str, Any]] = {}
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for item in items:
        iso = str(item.get("iso") or "").upper()
        if iso:
            by_iso[iso] = item
        score = _country_usage_score(item)
        scored.append((score, str(item.get("name") or "").lower(), item))

    picked: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    scored.sort(key=lambda x: (-x[0], x[1]))
    has_usage = any(score > 0 for score, _, _ in scored)
    if has_usage:
        for score, _, item in scored:
            if score <= 0:
                break
            code = str(item.get("code") or "")
            if not code or code in seen_codes:
                continue
            picked.append(item)
            seen_codes.add(code)
            if len(picked) >= limit:
                return picked

    for iso in _DEFAULT_QUICK_COUNTRY_ISO:
        item = by_iso.get(iso)
        if not item:
            continue
        code = str(item.get("code") or "")
        if not code or code in seen_codes:
            continue
        picked.append(item)
        seen_codes.add(code)
        if len(picked) >= limit:
            return picked

    for _, _, item in scored:
        code = str(item.get("code") or "")
        if not code or code in seen_codes:
            continue
        picked.append(item)
        seen_codes.add(code)
        if len(picked) >= limit:
            break
    return picked


@router.inline_query(
    lambda iq: not (
        (iq.query or "").strip().lower().startswith("proxy")
        or (iq.query or "").strip().lower().startswith("game")
    )
)
async def handle_smart_search(inline_query: types.InlineQuery):
    query = (inline_query.query or "").strip().lower()
    max_results = 50

    requester = getattr(inline_query, "from_user", None)
    requester_id = getattr(requester, "id", 0)
    if requester_id and _throttled(requester_id):
        return await inline_query.answer([], cache_time=_INLINE_CACHE_TIME_SEC, is_personal=True)

    results = []
    if query.startswith("country"):
        query = _strip_prefix_tokens(query, "country")
    if query.startswith("service"):
        search_text = _strip_prefix_tokens(query, "service")
        items = _service_items()
        normalized_query = _normalize_search_text(search_text)
        scored_items: list[tuple[int, int, str, tuple[str, dict[str, Any]]]] = []
        for item in items:
            key, info = item
            label = str(info.get("display_name", key))
            search_tokens = _service_search_tokens(key, info)
            if normalized_query:
                if not any(_ordered_match(normalized_query, token) for token in search_tokens):
                    continue
                token_norms = [_normalize_search_text(token) for token in search_tokens]
                rank = 2 if any(token.startswith(normalized_query) for token in token_norms) else 1
            else:
                rank = 0
            score = _usage(label) + _usage(key)
            scored_items.append((rank, score, label.lower(), item))

        scored_items.sort(key=lambda x: (-x[0], -x[1], x[2]))
        top = scored_items[: (50 if search_text else 20)]
        top_rows: list[tuple[str, str]] = []
        for _, _, _, (key, info) in top:
            if not key:
                continue
            display_name = str(info.get("display_name", key))
            top_rows.append((key, display_name))

        icon_urls: list[str] = []
        if top_rows:
            session = await SessionManager.get_session()
            icon_urls = await asyncio.gather(
                *(resolve_service_icon_url(key, display_name, session) for key, display_name in top_rows),
                return_exceptions=True,
            )

        for idx, (key, display_name) in enumerate(top_rows):
            thumb = icon_urls[idx] if idx < len(icon_urls) and isinstance(icon_urls[idx], str) else get_no_icon_url()
            results.append(
                types.InlineQueryResultArticle(
                    id=_safe_result_id("ser", f"{key}:{_INLINE_RESULT_ICON_VERSION}"),
                    title=display_name,
                    thumbnail_url=thumb,
                    input_message_content=types.InputTextMessageContent(message_text=f"/select_service_{key}"),
                )
            )
        if search_text and not results:
            results.append(
                types.InlineQueryResultArticle(
                    id=_safe_result_id("ser", f"{_SERVICE_NOT_LISTED_KEY}_fallback:{_INLINE_RESULT_ICON_VERSION}"),
                    title="Service Not Listed",
                    thumbnail_url=get_no_icon_url(),
                    input_message_content=types.InputTextMessageContent(
                        message_text=f"/select_service_{_SERVICE_NOT_LISTED_KEY}"
                    ),
                )
            )
    elif query.startswith("tvstate"):
        search_text = _strip_prefix_tokens(query, "tvstate")
        filtered_states = [row for row in STATES_LIST if str(row.get("code") or "").upper() in _TV_ALLOWED_STATES]
        usage_by_name = {str(row.get("name") or ""): _state_usage_score(row) for row in filtered_states}
        sorted_items = _boost_sort(
            filtered_states,
            key_func=lambda x: x["name"],
            query=search_text,
            usage_func=lambda name: int(usage_by_name.get(str(name), 0)),
            limit=50,
        )
        state_rows: list[tuple[str, str, str]] = []
        for item in sorted_items:
            code = str(item["code"]).upper()
            name = item["name"]
            area_code = str(tv_area_codes.DATA.get(code) or "").strip()
            state_rows.append((code, name, area_code))
        session = await SessionManager.get_session()
        thumbs = await asyncio.gather(
            *(resolve_state_icon_url(code, name, session) for code, name, _ in state_rows),
            return_exceptions=True,
        )
        for idx, (code, name, area_code) in enumerate(state_rows):
            thumb = thumbs[idx] if idx < len(thumbs) and isinstance(thumbs[idx], str) else get_no_icon_url()
            results.append(
                types.InlineQueryResultArticle(
                    id=_safe_result_id("tvs", f"{code}:{_INLINE_RESULT_ICON_VERSION}"),
                    title=_state_inline_title(code, name),
                    thumbnail_url=thumb,
                    input_message_content=types.InputTextMessageContent(message_text=f"/select_state_{code}"),
                )
            )
    elif query.startswith("state"):
        search_text = query.replace("state", "", 1).strip()
        session = await SessionManager.get_session()
        any_thumb = await resolve_state_icon_url("US", "Any State", session)
        results.append(
            types.InlineQueryResultArticle(
                id=_safe_result_id("st_any", f"none:{_INLINE_RESULT_ICON_VERSION}"),
                title=f"{_iso_to_flag('US')} {t('en', 'state_any')}".strip(),
                thumbnail_url=any_thumb,
                input_message_content=types.InputTextMessageContent(message_text="/select_state_none"),
            )
        )
        usage_by_name = {str(row.get("name") or ""): _state_usage_score(row) for row in STATES_LIST}
        sorted_items = _boost_sort(
            STATES_LIST,
            key_func=lambda x: x["name"],
            query=search_text,
            usage_func=lambda name: int(usage_by_name.get(str(name), 0)),
            limit=50,
        )
        state_rows: list[tuple[str, str]] = []
        for item in sorted_items:
            code = item["code"]
            name = item["name"]
            state_rows.append((str(code), str(name)))
        thumbs = await asyncio.gather(
            *(resolve_state_icon_url(code, name, session) for code, name in state_rows),
            return_exceptions=True,
        )
        for idx, (code, name) in enumerate(state_rows):
            thumb = thumbs[idx] if idx < len(thumbs) and isinstance(thumbs[idx], str) else get_no_icon_url()
            results.append(
                types.InlineQueryResultArticle(
                    id=_safe_result_id("st", f"{code}:{_INLINE_RESULT_ICON_VERSION}"),
                    title=_state_inline_title(code, name),
                    thumbnail_url=thumb,
                    input_message_content=types.InputTextMessageContent(message_text=f"/select_state_{code}"),
                )
            )
    else:
        countries = await _get_search_countries()
        any_country_thumb = get_generic_service_icon_url("Globe")
        results.append(
            types.InlineQueryResultArticle(
                id=_safe_result_id("cnt", f"{_ANY_COUNTRY_CODE}:{_INLINE_RESULT_ICON_VERSION}"),
                title=t("en", "inline_any_country"),
                thumbnail_url=any_country_thumb,
                input_message_content=types.InputTextMessageContent(
                    message_text=f"/select_country_{_ANY_COUNTRY_CODE}"
                ),
            )
        )
        session = await SessionManager.get_session()
        quick_countries = _top_quick_countries(countries, limit=4)
        quick_codes: set[str] = set()
        quick_rows: list[tuple[str, str, str, str]] = []
        for item in quick_countries:
            code = str(item.get("code") or "")
            if not code:
                continue
            quick_codes.add(code)
            name = str(item.get("name") or code)
            iso = str(item.get("iso") or "").upper()
            title = _country_inline_title(item, query)
            quick_rows.append((code, name, iso, title))
        quick_thumbs = await asyncio.gather(
            *(resolve_country_icon_url(iso, name, session) for code, name, iso, title in quick_rows),
            return_exceptions=True,
        )
        for idx, (code, _, _, title) in enumerate(quick_rows):
            thumb = quick_thumbs[idx] if idx < len(quick_thumbs) and isinstance(quick_thumbs[idx], str) else get_no_icon_url()
            results.append(
                types.InlineQueryResultArticle(
                    id=_safe_result_id("cnt_quick", f"{code}:{_INLINE_RESULT_ICON_VERSION}"),
                    title=title,
                    thumbnail_url=thumb,
                    input_message_content=types.InputTextMessageContent(message_text=f"/select_country_{code}"),
                )
            )
        sorted_items = _search_countries(
            countries,
            query=query,
            limit=49 if query else 49,
        )
        country_rows: list[tuple[str, str, str, str]] = []
        for item in sorted_items:
            code = item["code"]
            if not query and code in quick_codes:
                continue
            name = item["name"]
            iso = str(item.get("iso") or "").upper()
            title = _country_inline_title(item, query)
            country_rows.append((str(code), name, iso, title))
        thumbs = await asyncio.gather(
            *(resolve_country_icon_url(iso, name, session) for code, name, iso, title in country_rows),
            return_exceptions=True,
        )
        for idx, (code, _, _, title) in enumerate(country_rows):
            thumb = thumbs[idx] if idx < len(thumbs) and isinstance(thumbs[idx], str) else get_no_icon_url()
            results.append(
                types.InlineQueryResultArticle(
                    id=_safe_result_id("cnt", f"{code}:{_INLINE_RESULT_ICON_VERSION}"),
                    title=title,
                    thumbnail_url=thumb,
                    input_message_content=types.InputTextMessageContent(message_text=f"/select_country_{code}"),
                )
            )

    unique_results = []
    seen_ids: set[str] = set()
    for item in results:
        rid = str(getattr(item, "id", "")).strip()
        if not rid or rid in seen_ids:
            continue
        seen_ids.add(rid)
        unique_results.append(item)

    await inline_query.answer(
        unique_results[:max_results],
        cache_time=_INLINE_CACHE_TIME_SEC,
        is_personal=True,
    )

