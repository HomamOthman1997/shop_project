import hashlib

from aiogram import Router, types

from services.proxies.catalog_cache import build_index, decode_token, encode_token, get_offers_cache

router = Router()


def _contains(haystack: str, needle: str) -> bool:
    if not needle:
        return True
    return needle.lower() in haystack.lower()


def _safe_result_id(prefix: str, *parts: str) -> str:
    raw = "|".join([prefix, *[str(p or "") for p in parts]])
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:28]
    return f"{prefix}_{digest}"


def _article(result_id: str, title: str, desc: str, command_text: str) -> types.InlineQueryResultArticle:
    return types.InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=desc,
        input_message_content=types.InputTextMessageContent(message_text=command_text),
    )


@router.inline_query(lambda iq: (iq.query or "").strip().lower().startswith("proxy"))
async def proxy_inline_search(inline_query: types.InlineQuery):
    query = (inline_query.query or "").strip()
    q_lower = query.lower()
    offers = get_offers_cache()
    index = build_index(offers)

    if not offers:
        return await inline_query.answer(
            [
                _article(
                    "proxy_empty",
                    "Open Proxies Menu First",
                    "Open the proxies section once to load provider catalog.",
                    "/start",
                )
            ],
            cache_time=1,
            is_personal=True,
        )

    results: list[types.InlineQueryResultArticle] = []

    if q_lower.startswith("proxy country"):
        search_term = query[len("proxy country") :].strip()
        for country in index["countries"]:
            if _contains(country, search_term):
                token = encode_token(country)
                results.append(
                    _article(
                        _safe_result_id("pc", token),
                        f"Country: {country}",
                        "Tap to select country",
                        f"/proxy_country_{token}",
                    )
                )

    elif q_lower.startswith("proxy state"):
        rest = query[len("proxy state") :].strip()
        if rest:
            parts = rest.split(" ", 1)
            country_tok = parts[0]
            search_term = parts[1].strip() if len(parts) > 1 else ""
            country = decode_token(country_tok)
            states = index["states_by_country"].get(country, [])
            for state in states:
                if _contains(state, search_term):
                    st_tok = encode_token(state)
                    results.append(
                        _article(
                            _safe_result_id("ps", country_tok, st_tok),
                            f"State: {state}",
                            f"Country: {country}",
                            f"/proxy_state_{country_tok}~{st_tok}",
                        )
                    )

    elif q_lower.startswith("proxy city"):
        rest = query[len("proxy city") :].strip()
        if rest:
            parts = rest.split(" ", 1)
            locator_tok = parts[0]
            search_term = parts[1].strip() if len(parts) > 1 else ""

            # Legacy format: country:state
            if ":" in locator_tok:
                country_tok, state_tok = locator_tok.split(":", 1)
                country = decode_token(country_tok)
                state = decode_token(state_tok)
                cities = index["cities_by_country_state"].get((country, state), [])
                for city in cities:
                    if _contains(city, search_term):
                        city_tok = encode_token(city)
                        results.append(
                            _article(
                                _safe_result_id("pci_legacy", country_tok, state_tok, city_tok),
                                f"City: {city}",
                                f"{country} / {state}",
                                f"/proxy_city_{country_tok}~{state_tok}~{city_tok}",
                            )
                        )
            else:
                # New default flow: country -> city (state optional)
                country_tok = locator_tok
                country = decode_token(country_tok)
                cities = index.get("cities_by_country", {}).get(country, [])
                for city in cities:
                    if _contains(city, search_term):
                        city_tok = encode_token(city)
                        results.append(
                            _article(
                                _safe_result_id("pci", country_tok, city_tok),
                                f"City: {city}",
                                f"Country: {country}",
                                f"/proxy_city_{country_tok}~{city_tok}",
                            )
                        )

    await inline_query.answer(results[:50], cache_time=1, is_personal=True)
