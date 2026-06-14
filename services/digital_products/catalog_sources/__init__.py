"""Provider catalog sources for the digital catalog staging importer.

Each provider implements `CatalogSource` (see `base.py`) and is registered in
`registry.py`. The staging importer (`catalog_staging_service`) pulls normalized
offers from every enabled source, applies the catalog rules, and writes them to
the staging store for owner review — never directly to the live catalog.
"""

from services.digital_products.catalog_sources.base import CatalogOffer, CatalogSource, parse_compare_key
from services.digital_products.catalog_sources.registry import enabled_catalog_sources

__all__ = [
    "CatalogOffer",
    "CatalogSource",
    "parse_compare_key",
    "enabled_catalog_sources",
]
