from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from config import settings
from services.digital_products.catalog_service import get_catalog_snapshot, get_game_topups


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _first_number(text: str) -> int | None:
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _service_key_from_g2_name(text: str) -> str | None:
    name = _norm(text)
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("pubg", ("pubg", "pubgm", "uc")),
        ("mlbb", ("mobile legends", "mlbb", "diamond")),
        ("free_fire", ("free fire",)),
        ("hok", ("honor of kings", "honor of king", "hok")),
        ("steam", ("steam",)),
        ("itunes", ("itunes", "apple")),
        ("playstation", ("playstation", "psn")),
        ("xbox", ("xbox",)),
        ("nintendo", ("nintendo",)),
        ("roblox", ("roblox",)),
        ("razer", ("razer",)),
        ("discord", ("discord",)),
        ("imo", ("imo",)),
        ("jawaker", ("jawaker",)),
        ("yalla_ludo", ("yalla ludo",)),
    ]
    for key, tokens in rules:
        if any(token in name for token in tokens):
            return key
    return None


def _service_key_from_za3em_text(text: str) -> str | None:
    name = _norm(text)
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("pubg", ("pubg", "ببجي", "شدة", "شدات", "uc")),
        ("mlbb", ("mobile legend", "mobile legends", "موبايل ليجند", "mlbb")),
        ("free_fire", ("free fire", "فري فاير")),
        ("hok", ("honor of king", "honor of kings", "hok")),
        ("steam", ("steam",)),
        ("itunes", ("itunes", "ايتونز")),
        ("playstation", ("playstation", "بلاي ستيشن", "psn")),
        ("xbox", ("xbox",)),
        ("nintendo", ("nintendo",)),
        ("roblox", ("robلوكس", "roblox", "روبلوكس")),
        ("razer", ("razer", "ريزر")),
        ("discord", ("discord", "ديسكورد")),
        ("imo", ("imo",)),
        ("jawaker", ("jawaker", "جواكر")),
        ("yalla_ludo", ("yalla ludo", "يلا لودو")),
    ]
    for key, tokens in rules:
        if any(token in name for token in tokens):
            return key
    return None


def _display_service_name(key: str) -> str:
    labels = {
        "pubg": "PUBG",
        "mlbb": "Mobile Legends",
        "free_fire": "Free Fire",
        "hok": "Honor of Kings",
        "steam": "Steam",
        "itunes": "iTunes",
        "playstation": "PlayStation",
        "xbox": "Xbox",
        "nintendo": "Nintendo",
        "roblox": "Roblox",
        "razer": "Razer",
        "discord": "Discord",
        "imo": "IMO",
        "jawaker": "Jawaker",
        "yalla_ludo": "Yalla Ludo",
    }
    return labels.get(key, key)


@dataclass
class Row:
    provider: str
    source: str
    service_key: str
    amount_key: int
    item_id: str
    name: str
    price: float
    available: bool
    variant_key: str


def _extract_currency_variant(text: str) -> str:
    n = _norm(text)
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("usd", (" usd", "us$", "$", "دولار", "امريكي", "usa", "us ")),
        ("sar", ("sar", "ريال", "سعود", "ksa")),
        ("eur", ("eur", "€", "euro", "الماني", "germany", "german")),
        ("hkd", ("hkd",)),
        ("myr", ("myr",)),
        ("try", ("try", "turkey", "turkish", "تركي", "تركية")),
        ("uae", ("uae", "emirati", "اماراتي")),
        ("europe", ("europe", "eu", "اوربي")),
        ("canada", ("canada", "كندي")),
        ("global", ("global", "عالمي")),
    ]
    for key, tokens in rules:
        if any(token in n for token in tokens):
            return key
    return "generic"


def _extract_game_variant(service_key: str, text: str) -> str:
    n = _norm(text)
    compact = re.sub(r"[\s,]+", "", n)
    tags: list[str] = []
    if any(k in n for k in ("month", "months", "شهر", "شهور")):
        tags.append("month")
    if any(k in n for k in ("weekly", "اسبوع", "week")):
        tags.append("weekly")
    if any(k in n for k in ("prime", "برايم")):
        tags.append("prime")
    if any(k in n for k in ("plus", "بلس", "+")):
        tags.append("plus")
    if any(k in n for k in ("normal", "ordinary", "عادي")):
        tags.append("normal")
    if any(k in n for k in ("pass", "elite", "باس")):
        tags.append("pass")
    if any(k in n for k in ("pack", "bundle", "حزمة")):
        tags.append("pack")
    if any(k in n for k in ("discount", "خصم")):
        tags.append("discount")
    if service_key in {"pubg", "mlbb", "free_fire", "hok"} and any(
        k in n for k in ("uc", "شدة", "شدات", "diamond", "diamonds", "جواهر")
    ):
        tags.append("topup")
    if service_key in {"pubg", "mlbb", "free_fire", "hok"} and compact.isdigit():
        tags.append("topup")
    if not tags:
        return "generic"
    return "|".join(sorted(set(tags)))


def _variant_key(service_key: str, text: str) -> str:
    if service_key in {"pubg", "mlbb", "free_fire", "hok"}:
        return _extract_game_variant(service_key, text)
    return _extract_currency_variant(text)


async def _load_g2_rows() -> list[Row]:
    snapshot = await get_catalog_snapshot(force=True)
    rows: list[Row] = []

    # Gift cards / vouchers catalog
    for cat_id, items in (snapshot.get("products_by_category") or {}).items():
        for item in list(items or []):
            full_name = f"{item.get('name') or ''} {item.get('clean_name') or ''}"
            key = _service_key_from_g2_name(full_name)
            if not key:
                continue
            amount = _first_number(str(item.get("clean_name") or item.get("name") or ""))
            if not amount:
                continue
            rows.append(
                Row(
                    provider="g2bulk",
                    source="gift",
                    service_key=key,
                    amount_key=amount,
                    item_id=str(item.get("id") or ""),
                    name=str(item.get("clean_name") or item.get("name") or "").strip(),
                    price=float(item.get("price") or 0.0),
                    available=int(item.get("stock") or 0) > 0,
                    variant_key=_variant_key(key, str(item.get("clean_name") or item.get("name") or "")),
                )
            )

    # Games topups
    for game in list(snapshot.get("games") or []):
        game_id = str(game.get("id") or "").strip()
        game_name = str(game.get("name") or "").strip()
        if not game_id:
            continue
        key = _service_key_from_g2_name(f"{game_id} {game_name}")
        if not key:
            continue
        topups = await get_game_topups(game_id)
        for item in list(topups or []):
            display = str(item.get("clean_name") or item.get("name") or "").strip()
            amount = _first_number(display)
            if not amount:
                continue
            rows.append(
                Row(
                    provider="g2bulk",
                    source="game",
                    service_key=key,
                    amount_key=amount,
                    item_id=str(item.get("id") or ""),
                    name=display,
                    price=float(item.get("price") or 0.0),
                    available=True,
                    variant_key=_variant_key(key, display),
                )
            )

    return rows


def _load_za3em_rows(token: str) -> list[Row]:
    resp = requests.get(
        "https://api.za3em-card.com/client/api/products",
        headers={"api-token": token},
        timeout=45,
    )
    resp.raise_for_status()
    payload = resp.json()
    rows: list[Row] = []
    for item in list(payload or []):
        name = str(item.get("name") or "").strip()
        cat = str(item.get("category_name") or "").strip()
        key = _service_key_from_za3em_text(f"{name} {cat}")
        if not key:
            continue
        amount = _first_number(name) or _first_number(cat)
        if not amount:
            continue
        rows.append(
            Row(
                provider="za3em",
                source=str(item.get("product_type") or "product"),
                service_key=key,
                amount_key=amount,
                item_id=str(item.get("id") or ""),
                name=name,
                price=float(item.get("price") or 0.0),
                available=bool(item.get("available")),
                variant_key=_variant_key(key, f"{name} {cat}"),
            )
        )
    return rows


def _best_match_for_key(
    g2_rows: list[Row],
    za_rows: list[Row],
) -> list[dict[str, Any]]:
    index: dict[tuple[str, int], list[Row]] = {}
    for row in za_rows:
        if not row.available:
            continue
        index.setdefault((row.service_key, row.amount_key), []).append(row)

    compared: list[dict[str, Any]] = []
    for g2 in g2_rows:
        candidates = index.get((g2.service_key, g2.amount_key)) or []
        if not candidates:
            continue
        filtered = [
            row
            for row in candidates
            if row.variant_key == g2.variant_key or row.variant_key == "generic" or g2.variant_key == "generic"
        ]
        if filtered:
            candidates = filtered
        elif g2.variant_key != "generic":
            continue
        # prefer closest lexical name, then cheaper
        scored: list[tuple[float, Row]] = []
        g2n = _norm(g2.name)
        g2_tokens = set(g2n.split())
        for cand in candidates:
            zn = _norm(cand.name)
            z_tokens = set(zn.split())
            common = len(g2_tokens.intersection(z_tokens))
            score = common / max(1.0, float(len(g2_tokens.union(z_tokens))))
            scored.append((score, cand))
        scored.sort(key=lambda x: (-x[0], x[1].price))
        best_score, best = scored[0]
        if best_score < 0.18 and g2.variant_key == "generic":
            continue
        compared.append(
            {
                "service_key": g2.service_key,
                "service_name": _display_service_name(g2.service_key),
                "amount_key": g2.amount_key,
                "g2_id": g2.item_id,
                "g2_name": g2.name,
                "g2_price_raw": round(g2.price, 6),
                "za3em_id": best.item_id,
                "za3em_name": best.name,
                "za3em_price_raw": round(best.price, 6),
                "cheaper_provider": "za3em" if best.price < g2.price else ("g2bulk" if g2.price < best.price else "equal"),
                "price_diff_abs": round(abs(g2.price - best.price), 6),
                "match_confidence": round(best_score, 4),
                "g2_source": g2.source,
                "za3em_source": best.source,
                "g2_variant": g2.variant_key,
                "za3em_variant": best.variant_key,
            }
        )
    compared.sort(key=lambda r: (r["service_name"], r["amount_key"], r["g2_price_raw"]))
    return compared


def _write_outputs(rows: list[dict[str, Any]], out_csv: Path, out_json: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "service_name",
        "service_key",
        "amount_key",
        "g2_id",
        "g2_name",
        "g2_price_raw",
        "za3em_id",
        "za3em_name",
        "za3em_price_raw",
        "cheaper_provider",
        "price_diff_abs",
        "match_confidence",
        "g2_source",
        "za3em_source",
        "g2_variant",
        "za3em_variant",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in columns})

    summary: dict[str, Any] = {
        "generated_rows": len(rows),
        "counts_by_cheaper": {
            "za3em": sum(1 for r in rows if r.get("cheaper_provider") == "za3em"),
            "g2bulk": sum(1 for r in rows if r.get("cheaper_provider") == "g2bulk"),
            "equal": sum(1 for r in rows if r.get("cheaper_provider") == "equal"),
        },
        "services": sorted(set(str(r.get("service_key")) for r in rows)),
    }
    out_json.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


async def _run(token: str, out_csv: Path, out_json: Path) -> dict[str, Any]:
    g2_rows = await _load_g2_rows()
    za_rows = _load_za3em_rows(token)
    compared = _best_match_for_key(g2_rows, za_rows)
    _write_outputs(compared, out_csv, out_json)
    return {
        "g2_rows_scannable": len(g2_rows),
        "za3em_rows_scannable": len(za_rows),
        "compared_rows": len(compared),
        "za3em_cheaper": sum(1 for r in compared if r.get("cheaper_provider") == "za3em"),
        "g2bulk_cheaper": sum(1 for r in compared if r.get("cheaper_provider") == "g2bulk"),
        "equal": sum(1 for r in compared if r.get("cheaper_provider") == "equal"),
        "csv_path": str(out_csv),
        "json_path": str(out_json),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare shared digital products raw prices between G2Bulk and Za3em.")
    parser.add_argument("--za3em-token", default="", help="Za3em api-token header value.")
    parser.add_argument("--out-csv", default="data/shared_services_price_report.csv")
    parser.add_argument("--out-json", default="data/shared_services_price_report.json")
    args = parser.parse_args()

    token = str(args.za3em_token or "").strip()
    if not token:
        token = str(getattr(settings, "za3em_api_token", "") or "").strip()
    if not token:
        raise SystemExit("Missing Za3em token. Pass --za3em-token.")

    result = asyncio.run(_run(token, Path(args.out_csv), Path(args.out_json)))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
