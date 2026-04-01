import asyncio
import json
from pathlib import Path
from typing import Any

from services.numbers.providers.herosms_provider import HeroSMSProvider
from services.numbers.providers.smsman_provider import SMSManProvider
from services.numbers.core.session_manager import SessionManager
from services.numbers.data import smspool_services, telabot_services, textverified_services
from services.numbers.service_families import normalize_service_key


ROOT = Path(__file__).resolve().parents[2]
FULL_MAP_PATH = ROOT / "data" / "full_service_map.json"


def _norm(value: str) -> str:
    return normalize_service_key(value or "")


def _ensure_entry(obj: dict[str, Any], key: str) -> dict[str, Any]:
    entry = obj.setdefault(key, {})
    if not isinstance(entry.get("providers"), dict):
        entry["providers"] = {}
    if not isinstance(entry.get("aliases"), list):
        entry["aliases"] = []
    return entry


def _add_mapping(obj: dict[str, Any], provider: str, service_name: str, code: Any) -> bool:
    key = _norm(service_name)
    if not key:
        return False
    entry = _ensure_entry(obj, key)
    providers = entry["providers"]
    changed = False
    code_s = str(code).strip()
    if code_s and providers.get(provider) != code_s:
        providers[provider] = code_s
        changed = True

    alias = str(service_name).strip().lower()
    if alias and alias not in entry["aliases"]:
        entry["aliases"].append(alias)
        changed = True
    return changed


def _iter_telabot_rows() -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    data = telabot_services.DATA
    if isinstance(data, dict) and isinstance(data.get("message"), list):
        for row in data["message"]:
            if isinstance(row, dict):
                name = str(row.get("name") or "").strip()
                sid = row.get("service_id") or row.get("id") or name
                if name:
                    rows.append((name, sid))
    elif isinstance(data, dict):
        for name, row in data.items():
            if isinstance(row, dict):
                sid = row.get("service_id") or row.get("id") or name
            else:
                sid = name
            name_s = str(name).strip()
            if name_s:
                rows.append((name_s, sid))
    return rows


async def _iter_herosms_rows() -> list[tuple[str, Any]]:
    provider = HeroSMSProvider()
    rows: list[tuple[str, Any]] = []
    try:
        services = await provider.get_services()
    except Exception:
        return rows
    if isinstance(services, list):
        for row in services:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            code = row.get("code") or name
            if name:
                rows.append((name, code))
    return rows


async def _iter_nonvoip_rows() -> list[tuple[str, Any]]:
    provider = SMSManProvider()
    rows: list[tuple[str, Any]] = []
    try:
        services = await provider.list_services(force_refresh=True)
    except Exception:
        return rows
    for row in services:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        sid = row.get("id") or row.get("service_id") or name
        if name:
            rows.append((name, sid))
    return rows


async def main() -> None:
    if not FULL_MAP_PATH.exists():
        raise RuntimeError(f"Missing file: {FULL_MAP_PATH}")

    full_map = json.loads(FULL_MAP_PATH.read_text(encoding="utf-8"))
    if not isinstance(full_map, dict):
        raise RuntimeError("full_service_map.json must be a JSON object")

    changed = 0
    stats: dict[str, int] = {
        "smspool": 0,
        "telabot": 0,
        "textverified": 0,
        "herosms": 0,
        "smsman": 0,
    }

    for row in smspool_services.DATA:
        name = str(row.get("name") or "").strip()
        sid = row.get("ID") or row.get("id") or name
        if name and _add_mapping(full_map, "smspool", name, sid):
            changed += 1
        if name:
            stats["smspool"] += 1

    for name, sid in _iter_telabot_rows():
        if _add_mapping(full_map, "telabot", name, sid):
            changed += 1
        stats["telabot"] += 1

    for row in textverified_services.DATA:
        name = str(row.get("serviceName") or "").strip()
        sid = row.get("serviceName") or name
        if name and _add_mapping(full_map, "textverified", name, sid):
            changed += 1
        if name:
            stats["textverified"] += 1

    for name, code in await _iter_herosms_rows():
        if _add_mapping(full_map, "herosms", name, code):
            changed += 1
        stats["herosms"] += 1

    for name, sid in await _iter_nonvoip_rows():
        if _add_mapping(full_map, "smsman", name, sid):
            changed += 1
        stats["smsman"] += 1

    FULL_MAP_PATH.write_text(json.dumps(full_map, indent=2, ensure_ascii=False), encoding="utf-8")

    coverage: dict[str, int] = {}
    for entry in full_map.values():
        providers = (entry.get("providers") or {})
        for p in providers.keys():
            coverage[p] = coverage.get(p, 0) + 1

    try:
        print(
            json.dumps(
                {
                    "updated_entries": changed,
                    "source_rows": stats,
                    "coverage": coverage,
                    "total_keys": len(full_map),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await SessionManager.close()


if __name__ == "__main__":
    asyncio.run(main())
