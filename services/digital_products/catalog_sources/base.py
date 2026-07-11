from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class CatalogOffer:
    """One normalized package offer pulled from a provider, ready for staging.

    `price_usd` is the raw provider cost. The staging importer applies the
    catalog markup and stores the sale price separately.
    """

    provider: str
    ref_id: str
    source_key: str          # stable per-product key for live upsert idempotency, e.g. "game:pubgm:264"
    service_key: str         # section, e.g. "games", "chat_apps", "store_cards"
    family_key: str          # e.g. "pubg"
    family_name: str
    sub_category: str        # rule 4 split, e.g. "topup" / "passes" / "specials" / region label
    region: str              # normalized lowercase region from compare_key, e.g. "global", "usa"
    compare_key: str         # identity layer, e.g. "pubg:global:8100:uc" ("" if unmappable)
    unit_kind: str           # e.g. "uc", "diamond", "usd"
    package_name: str
    price_usd: float
    requires_server: bool = False
    input_fields: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CatalogSource(Protocol):
    """A provider that can enumerate its full catalog as normalized offers.

    To add a provider: implement this protocol in a new module under
    `catalog_sources/` and register it in `registry.py`. Implementations must be
    resilient — a provider that is down/erroring should return an empty list (or
    raise) without breaking sibling sources; the importer isolates each source.
    """

    provider_code: str

    async def fetch_offers(self) -> list[CatalogOffer]:
        ...


def parse_compare_key(compare_key: str) -> tuple[str, str, str, str]:
    """Split a compare_key like 'pubg:global:8100:uc' into (family, region, amount, unit).

    Missing trailing parts come back as empty strings.
    """
    parts = [part.strip() for part in str(compare_key or "").split(":")]
    parts += [""] * (4 - len(parts))
    return parts[0], parts[1], parts[2], parts[3]
