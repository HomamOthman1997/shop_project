from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.digital_products.custom_catalog import FAMILY_TABLE
from services.digital_products.fulfillment_rules import game_default_unit, offer_compare_key, offer_region_label
from services.digital_products.g2bulk_client import G2BulkClient
from services.digital_products.mangerr_client import MangerrClient
from services.digital_products.static_taxonomy import guess_family

_KNOWN_GAMES = {
    str(row.get("key") or "").strip(): str(row.get("label") or "").strip()
    for row in FAMILY_TABLE.get("games", ())
    if str(row.get("key") or "").strip()
}


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _norm(value)).strip("_")


def _best_id(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _price(row: dict[str, Any]) -> float:
    for key in ("price", "amount", "unit_price", "buyer_price", "sell_price", "base_price"):
        try:
            value = float(row.get(key) or 0.0)
        except Exception:
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _first_number(value: Any) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)", str(value or "").replace(",", ""))
    return str(match.group(1)) if match else ""


def _api_error_summary(data: Any) -> str:
    if not isinstance(data, dict):
        return str(data or "unknown error")[:300]
    parts = [
        str(data.get("title") or "").strip(),
        str(data.get("detail") or "").strip(),
        str(data.get("msg") or data.get("error") or "").strip(),
    ]
    return " | ".join(part for part in parts if part)[:500] or "unknown error"


def infer_game_family(
    category_name: str,
    product_name: str,
    *,
    game_aliases: dict[str, tuple[str, str]] | None = None,
    allow_unknown: bool = False,
) -> tuple[str, str]:
    text = f"{category_name or ''} {product_name or ''}".strip()
    normalized_text = _norm(text)
    normalized_category = _norm(category_name)
    family_key, family_label = guess_family("games", category_name or product_name, [product_name])
    if family_key in _KNOWN_GAMES:
        return family_key, _KNOWN_GAMES[family_key] or family_label

    for alias, mapped in sorted(dict(game_aliases or {}).items(), key=lambda row: -len(row[0])):
        if normalized_category == alias or (
            len(alias) >= 5 and re.search(rf"(^|[^a-z0-9]){re.escape(alias)}([^a-z0-9]|$)", normalized_text)
        ):
            return mapped

    # Mangerr's product feed can expose PUBG packs only as "UC 60".
    if re.search(r"(^|[^a-z0-9])uc([^a-z0-9]|$)", normalized_text):
        return "pubg", _KNOWN_GAMES.get("pubg", "PUBG")
    if allow_unknown:
        label = str(category_name or product_name or "").strip()
        key = _slug(label)
        if key:
            return key, label
    return "", ""


def _package_variant(text: str) -> str:
    normalized = _norm(text)
    tags: list[str] = []
    rules: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("weekly", ("weekly", "week")),
        ("monthly", ("monthly", "month")),
        ("prime", ("prime",)),
        ("plus", ("plus", "+")),
        ("pass", ("pass", "elite")),
        ("membership", ("membership",)),
        ("bundle", ("bundle", "pack")),
    )
    for label, tokens in rules:
        if any(token in normalized for token in tokens):
            tags.append(label)
    return "-".join(tags) or "amount"


def package_compare_key(*, family_key: str, family_label: str, category_name: str, product_name: str) -> str:
    text = f"{product_name or ''} {category_name or ''}".strip()
    region = offer_region_label(text, default="Global")
    compare_key = offer_compare_key(
        family_key=family_key,
        region=region,
        offer_name=text,
        default_unit=game_default_unit(family_key, family_label),
    )
    if compare_key:
        return compare_key
    amount = _first_number(product_name) or _first_number(category_name)
    if not amount:
        return ""
    return f"{_slug(family_key)}:{_slug(region) or 'global'}:{amount}:{_package_variant(text)}"


@dataclass(frozen=True)
class GameProduct:
    provider: str
    product_id: str
    game_key: str
    game_name: str
    package_name: str
    category_name: str
    compare_key: str
    price: float
    available: bool
    params: tuple[str, ...] = ()


def normalize_mangerr_product(
    row: dict[str, Any],
    *,
    game_aliases: dict[str, tuple[str, str]] | None = None,
) -> GameProduct | None:
    name = str(row.get("name") or "").strip()
    category_name = str(row.get("category_name") or "").strip()
    game_key, game_name = infer_game_family(category_name, name, game_aliases=game_aliases)
    if not game_key:
        return None
    product_id = _best_id(row, "id", "product_id", "ID")
    compare_key = package_compare_key(
        family_key=game_key,
        family_label=game_name,
        category_name=category_name,
        product_name=name,
    )
    if not product_id or not compare_key:
        return None
    return GameProduct(
        provider="mangerr",
        product_id=product_id,
        game_key=game_key,
        game_name=game_name,
        package_name=name,
        category_name=category_name,
        compare_key=compare_key,
        price=_price(row),
        available=bool(row.get("available")),
        params=tuple(str(item).strip() for item in list(row.get("params") or []) if str(item).strip()),
    )


def normalize_g2bulk_product(game: dict[str, Any], row: dict[str, Any], index: int = 0) -> GameProduct | None:
    game_name_raw = str(game.get("name") or game.get("title") or game.get("game_name") or "").strip()
    game_key, game_name = infer_game_family(game_name_raw, game_name_raw, allow_unknown=True)
    if not game_key:
        return None
    package_name = str(row.get("name") or row.get("title") or row.get("product_name") or "").strip()
    product_id = _best_id(row, "id", "product_id", "ID") or (
        f"{_best_id(game, 'code', 'game_code', 'id', 'game_id')}_{index + 1}"
    )
    compare_key = package_compare_key(
        family_key=game_key,
        family_label=game_name,
        category_name=game_name_raw,
        product_name=package_name,
    )
    if not product_id or not compare_key:
        return None
    return GameProduct(
        provider="g2bulk",
        product_id=product_id,
        game_key=game_key,
        game_name=game_name,
        package_name=package_name,
        category_name=game_name_raw,
        compare_key=compare_key,
        price=_price(row),
        available=True,
    )


async def _load_g2bulk_products(
    client: G2BulkClient,
    *,
    concurrency: int = 8,
) -> tuple[list[dict[str, Any]], list[GameProduct]]:
    games = await client.get_games()
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def load_game(game: dict[str, Any]) -> list[GameProduct]:
        game_id = _best_id(game, "code", "game_code", "id", "game_id", "ID")
        if not game_id:
            return []
        async with semaphore:
            rows = await client.get_game_catalogue(game_id)
        normalized: list[GameProduct] = []
        for index, row in enumerate(rows):
            item = normalize_g2bulk_product(game, row, index)
            if item and item.price > 0:
                normalized.append(item)
        return normalized

    batches = await asyncio.gather(*(load_game(game) for game in games))
    return games, [item for batch in batches for item in batch]


def _cheapest_by_key(rows: list[GameProduct]) -> dict[str, GameProduct]:
    result: dict[str, GameProduct] = {}
    for row in rows:
        if not row.available or row.price <= 0 or not row.compare_key:
            continue
        current = result.get(row.compare_key)
        if current is None or row.price < current.price:
            result[row.compare_key] = row
    return result


def compare_products(g2bulk_rows: list[GameProduct], mangerr_rows: list[GameProduct]) -> dict[str, Any]:
    g2_index = _cheapest_by_key(g2bulk_rows)
    mangerr_index = _cheapest_by_key(mangerr_rows)
    shared_keys = sorted(set(g2_index).intersection(mangerr_index))
    matches: list[dict[str, Any]] = []
    for key in shared_keys:
        g2 = g2_index[key]
        mangerr = mangerr_index[key]
        cheaper = "mangerr" if mangerr.price < g2.price else ("g2bulk" if g2.price < mangerr.price else "equal")
        matches.append(
            {
                "compare_key": key,
                "game_key": g2.game_key,
                "game_name": g2.game_name,
                "g2bulk_id": g2.product_id,
                "g2bulk_name": g2.package_name,
                "g2bulk_price": round(g2.price, 6),
                "mangerr_id": mangerr.product_id,
                "mangerr_name": mangerr.package_name,
                "mangerr_price": round(mangerr.price, 6),
                "cheaper_provider": cheaper,
                "price_difference": round(abs(g2.price - mangerr.price), 6),
                "mangerr_params": list(mangerr.params),
            }
        )
    matches.sort(key=lambda row: (str(row["game_name"]), str(row["compare_key"])))
    return {
        "matches": matches,
        "unmatched_g2bulk": [asdict(g2_index[key]) for key in sorted(set(g2_index).difference(mangerr_index))],
        "unmatched_mangerr": [asdict(mangerr_index[key]) for key in sorted(set(mangerr_index).difference(g2_index))],
    }


def _g2bulk_game_aliases(games: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    aliases: dict[str, tuple[str, str]] = {}
    for game in games:
        name = str(game.get("name") or game.get("title") or game.get("game_name") or "").strip()
        family = infer_game_family(name, name, allow_unknown=True)
        if not family[0]:
            continue
        for value in (name, _best_id(game, "code", "game_code")):
            alias = _norm(value)
            if alias:
                aliases[alias] = family
    return aliases


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "game_name",
        "compare_key",
        "g2bulk_id",
        "g2bulk_name",
        "g2bulk_price",
        "mangerr_id",
        "mangerr_name",
        "mangerr_price",
        "cheaper_provider",
        "price_difference",
        "mangerr_params",
    ]
    with path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            payload = {key: row.get(key) for key in columns}
            payload["mangerr_params"] = " | ".join(row.get("mangerr_params") or [])
            writer.writerow(payload)


async def build_report(*, concurrency: int = 8) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    mangerr_client = MangerrClient()
    g2bulk_client = G2BulkClient()
    if not mangerr_client.configured():
        raise RuntimeError("Mangerr API is not configured.")
    if not g2bulk_client.configured():
        raise RuntimeError("G2Bulk API is not configured.")

    mangerr_status, mangerr_payload = await mangerr_client.get_products_response()
    if mangerr_status != 200 or not isinstance(mangerr_payload, list):
        raise RuntimeError(f"Mangerr products request failed (HTTP {mangerr_status}): {_api_error_summary(mangerr_payload)}")
    mangerr_raw = [row for row in mangerr_payload if isinstance(row, dict)]
    g2_games, g2_rows = await _load_g2bulk_products(g2bulk_client, concurrency=concurrency)
    game_aliases = _g2bulk_game_aliases(g2_games)
    mangerr_rows = [
        item
        for row in mangerr_raw
        if (item := normalize_mangerr_product(row, game_aliases=game_aliases)) is not None and item.price > 0
    ]
    comparison = compare_products(g2_rows, mangerr_rows)
    matches = list(comparison["matches"])
    summary = {
        "mangerr_products_total": len(mangerr_raw),
        "mangerr_game_products_classified": len(mangerr_rows),
        "mangerr_products_unclassified": len(mangerr_raw) - len(mangerr_rows),
        "g2bulk_games_total": len(g2_games),
        "g2bulk_game_products_classified": len(g2_rows),
        "matched_products": len(matches),
        "mangerr_cheaper": sum(1 for row in matches if row.get("cheaper_provider") == "mangerr"),
        "g2bulk_cheaper": sum(1 for row in matches if row.get("cheaper_provider") == "g2bulk"),
        "equal_price": sum(1 for row in matches if row.get("cheaper_provider") == "equal"),
        "unmatched_mangerr": len(comparison["unmatched_mangerr"]),
        "unmatched_g2bulk": len(comparison["unmatched_g2bulk"]),
    }
    return {"summary": summary, **comparison}, mangerr_raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull Mangerr products and compare classified game prices with G2Bulk.")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--out-json", default="data/mangerr_g2bulk_game_comparison.json")
    parser.add_argument("--out-csv", default="data/mangerr_g2bulk_game_comparison.csv")
    parser.add_argument("--raw-mangerr-json", default="data/mangerr_products_raw.json")
    args = parser.parse_args()

    try:
        report, mangerr_raw = asyncio.run(build_report(concurrency=max(1, int(args.concurrency))))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    out_json = Path(args.out_json)
    out_csv = Path(args.out_csv)
    raw_json = Path(args.raw_mangerr_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    raw_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_json.write_text(json.dumps(mangerr_raw, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(list(report["matches"]), out_csv)
    print(
        json.dumps(
            {
                **dict(report["summary"]),
                "report_json": str(out_json),
                "report_csv": str(out_csv),
                "raw_mangerr_json": str(raw_json),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
