import json
import os
from functools import lru_cache
from typing import Any, Dict, Iterable

from services.numbers.service_families import (
    CANONICAL_SERVICE_KEYS,
    DISPLAY_NAME_OVERRIDES,
    SERVICE_FAMILY_GROUPS,
    normalize_service_key,
)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_FULL_SERVICE_MAP_CANDIDATES = [
    os.path.normpath(os.path.join(os.path.dirname(__file__), "data", "full_service_map.json")),
    os.path.normpath(os.path.join(os.path.dirname(__file__), "data", "service_map.json")),
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "full_service_map.json")),
]


def _norm_name(value: str) -> str:
    return normalize_service_key(value)


def _load_display_names() -> Dict[str, str]:
    names: Dict[str, str] = {}

    try:
        from services.numbers.data import smspool_services

        for item in smspool_services.DATA:
            service = item.get("name", "")
            norm = _norm_name(service)
            if norm:
                names[norm] = service
    except ImportError:
        try:
            with open(os.path.join(_DATA_DIR, "smspool_services.json"), encoding="utf-8") as f:
                for item in json.load(f):
                    service = item.get("name", "")
                    norm = _norm_name(service)
                    if norm:
                        names[norm] = service
        except FileNotFoundError:
            pass

    try:
        from services.numbers.data import telabot_services

        data = telabot_services.DATA
        if isinstance(data, dict) and "message" in data:
            for item in data.get("message", []):
                service = item.get("name", "")
                norm = _norm_name(service)
                if norm:
                    names.setdefault(norm, service)
        elif isinstance(data, dict):
            for service_name in data:
                norm = _norm_name(service_name)
                names.setdefault(norm, service_name)
    except ImportError:
        try:
            with open(os.path.join(_DATA_DIR, "telabot_services.json"), encoding="utf-8") as f:
                data = json.load(f)
                for service_name in data:
                    norm = _norm_name(service_name)
                    names.setdefault(norm, service_name)
        except FileNotFoundError:
            pass

    try:
        from services.numbers.data import textverified_services

        for item in textverified_services.DATA:
            service = item.get("serviceName", "")
            norm = _norm_name(service)
            names.setdefault(norm, service)
    except ImportError:
        try:
            with open(os.path.join(_DATA_DIR, "textverified_services.json"), encoding="utf-8") as f:
                for item in json.load(f):
                    service = item.get("serviceName", "")
                    norm = _norm_name(service)
                    names.setdefault(norm, service)
        except FileNotFoundError:
            pass

    try:
        from services.numbers.data import pvadeals_services

        for item in pvadeals_services.DATA:
            service = item.get("name", "")
            norm = _norm_name(service)
            if norm:
                names.setdefault(norm, service)
    except ImportError:
        try:
            with open(os.path.join(_DATA_DIR, "pvadeals_services.json"), encoding="utf-8") as f:
                for item in json.load(f):
                    service = item.get("name", "")
                    norm = _norm_name(service)
                    if norm:
                        names.setdefault(norm, service)
        except FileNotFoundError:
            pass

    return names


def _load_provider_catalog_names(provider_code: str) -> Dict[str, str]:
    names: Dict[str, str] = {}
    if provider_code != "pvadeals":
        return names
    try:
        from services.numbers.data import pvadeals_services

        items = pvadeals_services.DATA
    except ImportError:
        try:
            with open(os.path.join(_DATA_DIR, "pvadeals_services.json"), encoding="utf-8") as f:
                items = json.load(f)
        except FileNotFoundError:
            items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        service = str(item.get("name") or "").strip()
        norm = _norm_name(service)
        if norm:
            names.setdefault(norm, service)
    return names


def _inject_provider_catalog_mappings(result: Dict[str, Any], provider_code: str) -> None:
    provider_names = _load_provider_catalog_names(provider_code)
    if not provider_names:
        return
    for key, entry in result.items():
        if not isinstance(entry, dict):
            continue
        providers = entry.setdefault("providers", {})
        if providers.get(provider_code):
            continue
        candidates = [key, entry.get("display_name")]
        matched_value = None
        for candidate in candidates:
            norm = _norm_name(str(candidate or ""))
            if not norm:
                continue
            matched_value = provider_names.get(norm)
            if matched_value:
                break
        if matched_value:
            providers[provider_code] = matched_value


def _dedupe_aliases(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        s = _norm_name(str(value or ""))
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _merge_service_family(result: Dict[str, Any], canonical_key: str, member_keys: list[str] | tuple[str, ...]) -> None:
    canonical = _norm_name(canonical_key)
    members = [_norm_name(member) for member in member_keys if _norm_name(member)]
    family = [canonical] + [member for member in members if member != canonical]

    existing_keys = [key for key in family if key in result]
    if not existing_keys:
        return

    canonical_entry = result.get(canonical)
    if not canonical_entry:
        seed_key = existing_keys[0]
        seed = result.get(seed_key) or {}
        canonical_entry = {
            "display_name": seed.get("display_name", canonical.replace("_", " ").title()),
            "providers": dict(seed.get("providers") or {}),
            "aliases": list(seed.get("aliases") or []),
        }
        result[canonical] = canonical_entry
        if seed_key != canonical:
            del result[seed_key]

    providers = canonical_entry.setdefault("providers", {})
    aliases = list(canonical_entry.get("aliases") or [])
    aliases.extend(family)

    for member in family:
        if member == canonical:
            continue
        member_entry = result.get(member)
        if not member_entry:
            continue
        for provider_code, service_code in (member_entry.get("providers") or {}).items():
            providers.setdefault(provider_code, service_code)
        aliases.extend(list(member_entry.get("aliases") or []))
        del result[member]

    canonical_entry["aliases"] = _dedupe_aliases(aliases)


def _merge_service_families(result: Dict[str, Any]) -> None:
    for canonical, members in SERVICE_FAMILY_GROUPS.items():
        _merge_service_family(result, canonical, members)


def _merge_google_gmail(result: Dict[str, Any]) -> None:
    _merge_service_family(
        result,
        "gmail",
        ("google", "googlegmail", "googlechat", "googleplay", "googlesend"),
    )
    if "gmail" in result:
        result["gmail"]["display_name"] = "Gmail / Google"


@lru_cache(maxsize=1)
def _load_map() -> Dict[str, Any]:
    full = None
    best_len = -1
    for path in _FULL_SERVICE_MAP_CANDIDATES:
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict) and len(loaded) > best_len:
                    full = loaded
                    best_len = len(loaded)
        except FileNotFoundError:
            continue

    if not full:
        return {}

    display_names = _load_display_names()
    result: Dict[str, Any] = {}
    for key, info in full.items():
        normalized_key = _norm_name(key)
        aliases = list(info.get("aliases", []) or [])
        aliases.extend([key, normalized_key])
        providers = dict(info.get("providers") or {})
        display_name = display_names.get(normalized_key, key.replace("_", " ").title())

        current = result.get(normalized_key)
        if not current:
            result[normalized_key] = {
                "display_name": display_name,
                "providers": providers,
                "aliases": _dedupe_aliases(aliases),
            }
            continue

        existing_providers = current.setdefault("providers", {})
        for provider_code, service_code in providers.items():
            existing_providers.setdefault(provider_code, service_code)
        current_aliases = list(current.get("aliases") or [])
        current["aliases"] = _dedupe_aliases(current_aliases + aliases)
        if not current.get("display_name"):
            current["display_name"] = display_name

    _merge_service_families(result)
    for key, display_name in DISPLAY_NAME_OVERRIDES.items():
        if key in result:
            result[key]["display_name"] = display_name
    _inject_provider_catalog_mappings(result, "pvadeals")

    return result


SERVICE_MAP = _load_map()


def resolve_canonical_service_key(service_key: str) -> str:
    normalized_key = _norm_name(service_key)
    if not normalized_key:
        return ""
    return CANONICAL_SERVICE_KEYS.get(normalized_key, normalized_key)


def get_service_entry(service_key: str) -> dict[str, Any] | None:
    canonical = resolve_canonical_service_key(service_key)
    if not canonical:
        return None
    entry = SERVICE_MAP.get(canonical)
    if not isinstance(entry, dict):
        return None
    return entry


def get_service_display_name(service_key: str) -> str | None:
    canonical = resolve_canonical_service_key(service_key)
    override = DISPLAY_NAME_OVERRIDES.get(canonical)
    if override:
        return str(override)
    entry = get_service_entry(service_key)
    if not entry:
        return None
    name = entry.get("display_name")
    if name is None:
        return None
    return str(name)


def get_service_aliases(service_key: str) -> tuple[str, ...]:
    entry = get_service_entry(service_key)
    if not entry:
        return tuple()
    aliases = _dedupe_aliases(list(entry.get("aliases") or []))
    return tuple(aliases)


def get_service_provider_map(service_key: str) -> dict[str, Any]:
    entry = get_service_entry(service_key)
    if not entry:
        return {}
    providers = entry.get("providers") or {}
    if not isinstance(providers, dict):
        return {}
    return dict(providers)


def iter_service_entries() -> list[tuple[str, dict[str, Any]]]:
    return [
        (str(key), dict(value))
        for key, value in SERVICE_MAP.items()
        if isinstance(key, str) and isinstance(value, dict)
    ]


def list_service_keys() -> list[str]:
    return sorted(SERVICE_MAP.keys())


def get_service_search_tokens(service_key: str) -> tuple[str, ...]:
    canonical = resolve_canonical_service_key(service_key)
    if not canonical:
        return tuple()
    entry = get_service_entry(canonical)
    if not entry:
        return tuple()
    tokens: list[Any] = [canonical, entry.get("display_name")]
    tokens.extend(list(entry.get("aliases") or []))
    return tuple(_dedupe_aliases(tokens))


def find_service_keys_by_alias(value: str) -> tuple[str, ...]:
    needle = _norm_name(value)
    if not needle:
        return tuple()
    direct = resolve_canonical_service_key(needle)
    matches: list[str] = []
    if direct and direct in SERVICE_MAP:
        matches.append(direct)
    for key, entry in SERVICE_MAP.items():
        aliases = _dedupe_aliases(list(entry.get("aliases") or []))
        if needle in aliases and key not in matches:
            matches.append(key)
    return tuple(matches)


def get_provider_service_name(service_key: str, provider_code: str) -> str:
    entry = get_service_entry(service_key)
    if entry:
        return entry.get("providers", {}).get(provider_code, service_key)
    return service_key

