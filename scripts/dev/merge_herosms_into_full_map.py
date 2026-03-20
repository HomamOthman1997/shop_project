import asyncio
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv


def normalize(value: str) -> str:
    return (
        str(value or "")
        .lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
        .replace(".", "")
        .replace("(", "")
        .replace(")", "")
        .replace("[", "")
        .replace("]", "")
        .replace("&", "")
        .replace("'", "")
        .replace('"', "")
        .strip()
    )


def split_tokens(value: str) -> list[str]:
    raw = str(value or "")
    parts = re.split(r"[,\+/\|\;\(\)\[\]\-]", raw)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        out.extend([x for x in p.split() if x.strip()])
    return out


STOPWORDS = {
    "any",
    "other",
    "app",
    "official",
    "global",
    "live",
    "online",
    "bank",
    "wallet",
}


def _best_fuzzy(norm_name: str, norm_to_key: dict[str, str]) -> str | None:
    best_key = None
    best_score = 0.0
    for norm_key, original_key in norm_to_key.items():
        score = SequenceMatcher(None, norm_name, norm_key).ratio()
        if score > best_score:
            best_score = score
            best_key = original_key
    if best_score >= 0.93:
        return best_key
    return None


async def fetch_herosms_services(base_url: str, api_key: str) -> list[dict[str, Any]]:
    params = {"action": "getServicesList", "api_key": api_key}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(base_url, params=params) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"HeroSMS getServicesList failed status={resp.status} body={text[:240]}")
            try:
                data = await resp.json(content_type=None)
            except Exception as exc:
                raise RuntimeError(f"HeroSMS returned invalid JSON: {text[:240]}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("HeroSMS response is not a JSON object")
    services = data.get("services")
    if not isinstance(services, list):
        raise RuntimeError(f"HeroSMS services payload missing list: keys={list(data.keys())}")
    return [x for x in services if isinstance(x, dict)]


def merge_herosms(full_map: dict[str, Any], herosms_services: list[dict[str, Any]]) -> dict[str, int]:
    norm_to_key: dict[str, str] = {}
    for key in full_map.keys():
        norm_to_key[normalize(key)] = key

    mapped_existing = 0
    created_new = 0
    conflicts = 0
    skipped = 0

    for item in herosms_services:
        code = str(item.get("code") or "").strip()
        name = str(item.get("name") or "").strip()
        if not code or not name:
            skipped += 1
            continue

        norm_full = normalize(name)
        token_norms: list[str] = []
        for token in split_tokens(name):
            nt = normalize(token)
            if not nt:
                continue
            if len(nt) < 4:
                continue
            if nt in STOPWORDS:
                continue
            token_norms.append(nt)

        target_keys: set[str] = set()
        if norm_full in norm_to_key:
            target_keys.add(norm_to_key[norm_full])

        for t in token_norms:
            if t in norm_to_key:
                target_keys.add(norm_to_key[t])

        if not target_keys:
            fuzzy = _best_fuzzy(norm_full, norm_to_key)
            if fuzzy:
                target_keys.add(fuzzy)

        if not target_keys:
            new_key = norm_full or normalize(code)
            if new_key not in full_map:
                full_map[new_key] = {"providers": {}}
                norm_to_key[normalize(new_key)] = new_key
                created_new += 1
            target_keys.add(new_key)

        for key in target_keys:
            entry = full_map.setdefault(key, {"providers": {}})
            providers = entry.setdefault("providers", {})
            prev = providers.get("herosms")
            if prev and str(prev) != code:
                conflicts += 1
                continue
            if not prev:
                mapped_existing += 1
            providers["herosms"] = code

            aliases = entry.get("aliases")
            if not isinstance(aliases, list):
                aliases = []
                entry["aliases"] = aliases
            alias_set = {str(a).strip().lower() for a in aliases if str(a).strip()}

            for a in [name] + split_tokens(name):
                a_clean = str(a).strip().lower()
                if not a_clean:
                    continue
                if len(a_clean) < 3:
                    continue
                if a_clean in alias_set:
                    continue
                aliases.append(a_clean)
                alias_set.add(a_clean)

    return {
        "mapped_existing": mapped_existing,
        "created_new": created_new,
        "conflicts": conflicts,
        "skipped": skipped,
    }


async def main() -> None:
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")

    base_url = (os.getenv("HEROSMS_BASE_URL") or "").strip()
    api_key = (os.getenv("HEROSMS_KEY") or "").strip()
    if not base_url:
        raise RuntimeError("HEROSMS_BASE_URL is missing in .env")
    if not api_key:
        raise RuntimeError("HEROSMS_KEY is missing in .env")

    full_map_path = root / "data" / "full_service_map.json"
    if not full_map_path.exists():
        raise RuntimeError(f"full_service_map.json not found: {full_map_path}")

    with full_map_path.open("r", encoding="utf-8") as f:
        full_map = json.load(f)
    if not isinstance(full_map, dict):
        raise RuntimeError("full_service_map.json content is not an object")

    services = await fetch_herosms_services(base_url, api_key)
    stats = merge_herosms(full_map, services)

    with full_map_path.open("w", encoding="utf-8") as f:
        json.dump(full_map, f, indent=2, ensure_ascii=False)

    total_with_herosms = 0
    for v in full_map.values():
        providers = (v or {}).get("providers") or {}
        if "herosms" in providers:
            total_with_herosms += 1

    print(
        json.dumps(
            {
                "herosms_services_fetched": len(services),
                "stats": stats,
                "full_map_total_keys": len(full_map),
                "full_map_keys_with_herosms": total_with_herosms,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
