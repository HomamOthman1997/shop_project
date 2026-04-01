import hashlib
from difflib import SequenceMatcher

from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest

from services.numbers.core.session_manager import SessionManager
from services.numbers.data.countries import COUNTRIES_LIST
from services.numbers.data.states_us import STATES_LIST
from services.numbers.service_icons import (
    get_generic_service_icon_url,
    resolve_country_icon_url,
    resolve_state_icon_url,
)
from services.proxies.catalog_cache import build_index, decode_token, encode_token, get_offers_cache
from utils.translations import t

router = Router()

_COUNTRY_NAME_TO_ISO: dict[str, str] = {}
_US_STATE_NAME_TO_CODE: dict[str, str] = {}
_US_STATE_ALIAS_TO_CODE: dict[str, str] = {}
for item in COUNTRIES_LIST:
    iso = str(item.get("iso") or "").strip().upper()
    name = str(item.get("name") or "").strip()
    if not iso or not name:
        continue
    _COUNTRY_NAME_TO_ISO[name.lower()] = iso
    _COUNTRY_NAME_TO_ISO[iso.lower()] = iso
    if iso == "US":
        _COUNTRY_NAME_TO_ISO["usa"] = "US"
        _COUNTRY_NAME_TO_ISO["united states"] = "US"
        _COUNTRY_NAME_TO_ISO["united states of america"] = "US"
    if iso == "GB":
        _COUNTRY_NAME_TO_ISO["uk"] = "GB"
        _COUNTRY_NAME_TO_ISO["united kingdom"] = "GB"

for item in STATES_LIST:
    code = str(item.get("code") or "").strip().upper()
    name = str(item.get("name") or "").strip()
    if code and name:
        _US_STATE_NAME_TO_CODE[name.lower()] = code
        _US_STATE_ALIAS_TO_CODE[name.lower()] = code
        for alias in item.get("aliases") or []:
            alias_text = str(alias or "").strip().lower()
            if alias_text:
                _US_STATE_ALIAS_TO_CODE[alias_text] = code


def _iso_to_flag(iso: str | None) -> str:
    code = str(iso or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)


def _proxy_country_iso(country: str) -> str:
    raw = str(country or "").strip()
    if not raw or raw.lower() == "any":
        return ""
    return _COUNTRY_NAME_TO_ISO.get(raw.lower(), "")


def _proxy_country_title(country: str) -> str:
    raw = str(country or "").strip()
    if not raw or raw.lower() == "any":
        return "Any Country"
    iso = _proxy_country_iso(raw)
    flag = _iso_to_flag(iso)
    return f"{raw.title()} {flag}".strip() if flag else raw.title()


def _proxy_state_code(country: str, value: str) -> str:
    if _proxy_country_iso(country) != "US":
        return ""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    direct = _US_STATE_NAME_TO_CODE.get(raw) or _US_STATE_ALIAS_TO_CODE.get(raw)
    if direct:
        return direct
    best_code = ""
    best_score = 0.0
    for alias, code in _US_STATE_ALIAS_TO_CODE.items():
        score = SequenceMatcher(None, raw, alias).ratio()
        if score > best_score:
            best_score = score
            best_code = code
    return best_code if best_score >= 0.88 else ""


def _contains(haystack: str, needle: str) -> bool:
    if not needle:
        return True
    return needle.lower() in haystack.lower()


def _safe_result_id(prefix: str, *parts: str) -> str:
    raw = "|".join([prefix, *[str(p or "") for p in parts]])
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:28]
    return f"{prefix}_{digest}"


def _non_any_values(values: list[str] | None) -> list[str]:
    return [
        str(value or "").strip()
        for value in (values or [])
        if str(value or "").strip() and str(value or "").strip().lower() != "any"
    ]


def _match_index_key(mapping: dict, wanted: str) -> str:
    raw = str(wanted or "").strip()
    if not raw:
        return ""
    if raw in mapping:
        return raw
    raw_lc = raw.lower()
    for key in mapping.keys():
        if str(key or "").strip().lower() == raw_lc:
            return str(key)
    return raw


def _article(
    result_id: str,
    title: str,
    desc: str,
    command_text: str,
    *,
    thumb_url: str | None = None,
) -> types.InlineQueryResultArticle:
    return types.InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=desc,
        input_message_content=types.InputTextMessageContent(message_text=command_text),
        thumbnail_url=thumb_url,
    )


async def _safe_inline_answer(
    inline_query: types.InlineQuery,
    results: list[types.InlineQueryResultArticle],
    *,
    cache_time: int = 1,
    is_personal: bool = True,
) -> None:
    try:
        await inline_query.answer(results, cache_time=cache_time, is_personal=is_personal)
    except TelegramBadRequest as exc:
        err = str(exc).lower()
        if "query is too old" in err or "query id is invalid" in err or "response timeout expired" in err:
            return
        raise


def _parse_locator_and_search(rest: str) -> tuple[str, str]:
    raw = str(rest or "").strip()
    if not raw:
        return "", ""
    if raw.startswith('"'):
        end = raw.find('"', 1)
        if end != -1:
            locator = raw[1:end].strip()
            search_term = raw[end + 1 :].strip()
            return locator, search_term
    parts = raw.split(" ", 1)
    locator = parts[0].strip()
    search_term = parts[1].strip() if len(parts) > 1 else ""
    return locator, search_term


@router.inline_query(lambda iq: (iq.query or "").strip().lower().startswith("proxy"))
async def proxy_inline_search(inline_query: types.InlineQuery):
    query = (inline_query.query or "").strip()
    q_lower = query.lower()
    offers = get_offers_cache()
    index = build_index(offers)

    if not offers:
        return await _safe_inline_answer(
            inline_query,
            [
                _article(
                    "proxy_empty",
                    "Open Proxies Menu First",
                    "Open the proxies section once to load provider catalog.",
                    "/start",
                )
            ]
        )

    results: list[types.InlineQueryResultArticle] = []

    if q_lower.startswith("proxy country"):
        search_term = query[len("proxy country") :].strip()
        session = await SessionManager.get_session()
        for country in index["countries"]:
            if _contains(country, search_term):
                token = encode_token(country)
                iso = _proxy_country_iso(country)
                thumb_url = (
                    get_generic_service_icon_url("Globe")
                    if not iso
                    else await resolve_country_icon_url(iso, country, session)
                )
                results.append(
                    _article(
                        _safe_result_id("pc", token),
                        _proxy_country_title(country),
                        f"Code: {iso}" if iso else "Code: Any",
                        f"/proxy_country_{token}",
                        thumb_url=thumb_url,
                    )
                )

    elif q_lower.startswith("proxy state"):
        rest = query[len("proxy state") :].strip()
        if rest:
            country_locator, search_term = _parse_locator_and_search(rest)
            country = decode_token(country_locator) or country_locator
            matched_country = _match_index_key(index["states_by_country"], country)
            country_tok = encode_token(matched_country or country)
            states = _non_any_values(index["states_by_country"].get(matched_country, []))
            city_fallback = _non_any_values(index["cities_by_country"].get(matched_country, []))
            location_values = states or city_fallback
            session = await SessionManager.get_session()
            for location in location_values:
                if _contains(location, search_term):
                    st_tok = encode_token(location)
                    state_code = _proxy_state_code(matched_country or country, location)
                    thumb_url = (
                        await resolve_state_icon_url(state_code, location, session)
                        if state_code
                        else get_generic_service_icon_url(location or "State")
                    )
                    results.append(
                        _article(
                            _safe_result_id("ps", country_tok, st_tok),
                            str(location or "").strip().title(),
                            f"Code: {state_code}" if state_code else _proxy_country_title(matched_country or country),
                            f"/proxy_state_{country_tok}~{st_tok}",
                            thumb_url=thumb_url,
                        )
                    )

    elif q_lower.startswith("proxy city"):
        rest = query[len("proxy city") :].strip()
        if rest:
            locator_raw, search_term = _parse_locator_and_search(rest)

            # Legacy format: country:state
            if ":" in locator_raw:
                country_part, state_part = locator_raw.split(":", 1)
                country = decode_token(country_part) or country_part
                matched_country = _match_index_key(index["states_by_country"], country)
                state = decode_token(state_part) or state_part
                matched_state = state
                for candidate in index["states_by_country"].get(matched_country, []):
                    if str(candidate or "").strip().lower() == str(state or "").strip().lower():
                        matched_state = candidate
                        break
                country_tok = encode_token(matched_country or country)
                state_tok = encode_token(matched_state or state)
                cities = index["cities_by_country_state"].get((matched_country or country, matched_state or state), [])
                session = await SessionManager.get_session()
                for city in cities:
                    if _contains(city, search_term):
                        city_tok = encode_token(city)
                        state_code = _proxy_state_code(matched_country or country, matched_state or state)
                        thumb_url = (
                            await resolve_state_icon_url(state_code, matched_state or state, session)
                            if state_code
                            else get_generic_service_icon_url(city or "City")
                        )
                        results.append(
                            _article(
                                _safe_result_id("pci_legacy", country_tok, state_tok, city_tok),
                                str(city or "").strip().title(),
                                f"Code: {state_code}" if state_code else f"{(matched_country or country).title()} / {(matched_state or state).title()}",
                                f"/proxy_city_{country_tok}~{state_tok}~{city_tok}",
                                thumb_url=thumb_url,
                            )
                        )
            else:
                # New default flow: country -> city (state optional)
                country = decode_token(locator_raw) or locator_raw
                matched_country = _match_index_key(index.get("states_by_country", {}), country)
                country_tok = encode_token(matched_country or country)
                cities = _non_any_values(index.get("cities_by_country", {}).get(matched_country, []))
                fallback_states = _non_any_values(index.get("states_by_country", {}).get(matched_country, []))
                candidates = cities or fallback_states
                session = await SessionManager.get_session()
                for city in candidates:
                    if _contains(city, search_term):
                        city_tok = encode_token(city)
                        state_code = _proxy_state_code(matched_country or country, city)
                        thumb_url = (
                            await resolve_state_icon_url(state_code, city, session)
                            if state_code
                            else get_generic_service_icon_url(city or "City")
                        )
                        results.append(
                            _article(
                            _safe_result_id("pci", country_tok, city_tok),
                            str(city or "").strip().title(),
                            f"Code: {state_code}" if state_code else _proxy_country_title(matched_country or country),
                            f"/proxy_city_{country_tok}~{city_tok}",
                            thumb_url=thumb_url,
                        )
                    )

    await _safe_inline_answer(inline_query, results[:50])
