from __future__ import annotations

from services.digital_products.catalog_sources.base import CatalogSource
from services.digital_products.catalog_sources.g2bulk_source import G2BulkCatalogSource
from services.digital_products.catalog_sources.mangerr_source import MangerrCatalogSource

# Every known catalog source, by provider code. To add a provider: implement the
# CatalogSource protocol in a new module and add it to this map.
_ALL_SOURCES: dict[str, type[CatalogSource]] = {
    "g2bulk": G2BulkCatalogSource,
    "mangerr": MangerrCatalogSource,
    # BitTopup and Za3em are intentionally NOT registered: Mangerr now covers
    # their products with auto fulfilment, so they are dropped from catalog
    # sourcing. Re-add a class + entry here to bring a provider back.
}

# Providers active in the staging importer by default. Overridable via settings
# (`digital_catalog_source_providers` = comma list or list).
_DEFAULT_ENABLED: tuple[str, ...] = ("g2bulk", "mangerr")


def enabled_catalog_sources() -> list[CatalogSource]:
    """Instantiate the catalog sources enabled for the staging importer."""
    from config import settings

    configured = getattr(settings, "digital_catalog_source_providers", None)
    if configured:
        raw = configured if isinstance(configured, (list, tuple)) else str(configured).split(",")
        codes = [str(code).strip().lower() for code in raw if str(code).strip()]
    else:
        codes = list(_DEFAULT_ENABLED)

    sources: list[CatalogSource] = []
    for code in codes:
        source_cls = _ALL_SOURCES.get(code)
        if source_cls is not None:
            sources.append(source_cls())
    return sources
