import re
import os
from typing import Any
from urllib.parse import quote_plus


# Curated domains for common global services to maximize icon hit-rate.
SERVICE_ICON_DOMAINS: dict[str, str] = {
    "gmail": "gmail.com",
    "google": "google.com",
    "telegram": "telegram.org",
    "paypal": "paypal.com",
    "facebook": "facebook.com",
    "instagram": "instagram.com",
    "whatsapp": "whatsapp.com",
    "twitter": "x.com",
    "x": "x.com",
    "tiktok": "tiktok.com",
    "amazon": "amazon.com",
    "apple": "apple.com",
    "microsoft": "microsoft.com",
    "outlook": "outlook.com",
    "icloud": "icloud.com",
    "netflix": "netflix.com",
    "uber": "uber.com",
    "airbnb": "airbnb.com",
    "discord": "discord.com",
    "linkedin": "linkedin.com",
    "snapchat": "snapchat.com",
    "reddit": "reddit.com",
    "line": "line.me",
    "wechat": "wechat.com",
    "yahoo": "yahoo.com",
    "steam": "steampowered.com",
    "epicgames": "epicgames.com",
    "openai": "openai.com",
    "chatgpt": "chatgpt.com",
    "coinbase": "coinbase.com",
    "binance": "binance.com",
    "wise": "wise.com",
    "revolut": "revolut.com",
    "ebay": "ebay.com",
    "booking": "booking.com",
    "spotify": "spotify.com",
    "youtube": "youtube.com",
    "pinterest": "pinterest.com",
    "roblox": "roblox.com",
    "twitch": "twitch.tv",
    "github": "github.com",
    "gitlab": "gitlab.com",
    "skype": "skype.com",
    "zoom": "zoom.us",
    "doordash": "doordash.com",
    "aliexpress": "aliexpress.com",
    "alibaba": "alibaba.com",
    "shein": "shein.com",
    "temu": "temu.com",
    "swagbucks": "swagbucks.com",
    "cashapp": "cash.app",
    "venmo": "venmo.com",
    "webull": "webull.com",
    "robinhood": "robinhood.com",
    "samsung": "samsung.com",
}

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_ICON_RESOLVE_CACHE: dict[str, str] = {}
_COUNTRY_ICON_CACHE: dict[str, str] = {}
_STATE_ICON_CACHE: dict[str, str] = {}
_STRICT_ICON_PROBE = str(os.getenv("INLINE_ICON_STRICT_FALLBACK", "0")).strip().lower() in {"1", "true", "yes", "on"}


def _norm_token(value: str) -> str:
    return _NON_ALNUM_RE.sub("", (value or "").strip().lower())


def _guess_domain(service_key: str, display_name: str) -> str:
    key_norm = _norm_token(service_key)
    if key_norm in SERVICE_ICON_DOMAINS:
        return SERVICE_ICON_DOMAINS[key_norm]

    # Try display-name first token as lightweight heuristic.
    first_word = re.split(r"[\s/|,_-]+", (display_name or "").strip().lower())[0]
    first_norm = _norm_token(first_word)
    if first_norm in SERVICE_ICON_DOMAINS:
        return SERVICE_ICON_DOMAINS[first_norm]

    # Generic fallback: many brands use .com for the main site.
    if key_norm:
        return f"{key_norm}.com"
    return "example.com"


def get_service_icon_url(service_key: str, display_name: str) -> str:
    domain = _guess_domain(service_key, display_name)
    # Primary provider (direct URL without extra redirect hop).
    return (
        "https://t2.gstatic.com/faviconV2?"
        f"client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://{quote_plus(domain)}&size=128"
    )


def get_generic_service_icon_url(display_name: str) -> str:
    # Stable fallback avatar icon when brand icon is unavailable.
    label = (display_name or "Service").strip()
    return f"https://ui-avatars.com/api/?name={quote_plus(label)}&size=128&background=0D253F&color=ffffff&bold=true"


def _secondary_service_icon_url(service_key: str, display_name: str) -> str:
    domain = _guess_domain(service_key, display_name)
    return f"https://logo.clearbit.com/{quote_plus(domain)}"


def _third_service_icon_url(service_key: str, display_name: str) -> str:
    domain = _guess_domain(service_key, display_name)
    return f"https://icons.duckduckgo.com/ip3/{quote_plus(domain)}.ico"


def get_no_icon_url() -> str:
    return get_generic_service_icon_url("No Icon")


def get_service_icon_candidates(service_key: str, display_name: str) -> list[str]:
    return [
        get_service_icon_url(service_key, display_name),
        _secondary_service_icon_url(service_key, display_name),
        _third_service_icon_url(service_key, display_name),
        get_no_icon_url(),
    ]


async def _is_image_url_alive(url: str, session: Any) -> bool:
    try:
        async with session.get(url, timeout=2) as resp:
            if resp.status != 200:
                return False
            ctype = str(resp.headers.get("Content-Type", "")).lower()
            if "image" not in ctype and "icon" not in ctype:
                return False
            return True
    except Exception:
        return False


async def resolve_service_icon_url(service_key: str, display_name: str, session: Any) -> str:
    cache_key = f"{_norm_token(service_key)}::{_norm_token(display_name)}"
    cached = _ICON_RESOLVE_CACHE.get(cache_key)
    if cached:
        return cached

    candidates = get_service_icon_candidates(service_key, display_name)
    if not _STRICT_ICON_PROBE:
        chosen = candidates[0]
        _ICON_RESOLVE_CACHE[cache_key] = chosen
        return chosen

    # Probe first three providers. Last one is guaranteed static fallback.
    for idx, url in enumerate(candidates):
        if idx < 3:
            if not await _is_image_url_alive(url, session):
                continue
        _ICON_RESOLVE_CACHE[cache_key] = url
        return url

    # Safety fallback.
    fallback = get_no_icon_url()
    _ICON_RESOLVE_CACHE[cache_key] = fallback
    return fallback


def _country_icon_candidates(iso_code: str, country_name: str) -> list[str]:
    iso = (iso_code or "").strip().lower()
    if iso and len(iso) == 2 and iso.isalpha():
        return [
            f"https://flagcdn.com/w80/{quote_plus(iso)}.png",
            f"https://countryflagsapi.netlify.app/flag/{quote_plus(iso)}.svg",
            get_no_icon_url(),
        ]
    return [
        (
            "https://t2.gstatic.com/faviconV2?"
            f"client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://{quote_plus(country_name)}&size=128"
        ),
        f"https://logo.clearbit.com/{quote_plus(country_name)}.com",
        get_no_icon_url(),
    ]


async def resolve_country_icon_url(iso_code: str, country_name: str, session: Any) -> str:
    cache_key = f"{(iso_code or '').strip().upper()}::{_norm_token(country_name)}"
    cached = _COUNTRY_ICON_CACHE.get(cache_key)
    if cached:
        return cached

    candidates = _country_icon_candidates(iso_code, country_name)
    if not _STRICT_ICON_PROBE:
        chosen = candidates[0]
        _COUNTRY_ICON_CACHE[cache_key] = chosen
        return chosen

    for idx, url in enumerate(candidates):
        if idx < 2 and not await _is_image_url_alive(url, session):
            continue
        _COUNTRY_ICON_CACHE[cache_key] = url
        return url
    fallback = get_no_icon_url()
    _COUNTRY_ICON_CACHE[cache_key] = fallback
    return fallback


def _state_icon_candidates(state_code: str, state_name: str) -> list[str]:
    code = (state_code or "").strip().lower()
    code_label = (state_code or "").strip().upper() or "ST"
    gov_domain = f"{quote_plus(code)}.gov" if code else quote_plus(state_name)
    return [
        (
            "https://ui-avatars.com/api/"
            f"?name={quote_plus(code_label)}&size=128&background=0B3D66&color=EAF2FF&bold=true&rounded=false"
        ),
        (
            "https://t2.gstatic.com/faviconV2?"
            f"client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://{gov_domain}&size=128"
        ),
        f"https://logo.clearbit.com/{gov_domain}",
        get_no_icon_url(),
    ]


async def resolve_state_icon_url(state_code: str, state_name: str, session: Any) -> str:
    cache_key = f"{(state_code or '').strip().upper()}::{_norm_token(state_name)}"
    cached = _STATE_ICON_CACHE.get(cache_key)
    if cached:
        return cached

    candidates = _state_icon_candidates(state_code, state_name)
    if not _STRICT_ICON_PROBE:
        chosen = candidates[0]
        _STATE_ICON_CACHE[cache_key] = chosen
        return chosen

    for idx, url in enumerate(candidates):
        if idx < 2 and not await _is_image_url_alive(url, session):
            continue
        _STATE_ICON_CACHE[cache_key] = url
        return url
    fallback = get_no_icon_url()
    _STATE_ICON_CACHE[cache_key] = fallback
    return fallback
