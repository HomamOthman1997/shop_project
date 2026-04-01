import base64
from collections import defaultdict
from datetime import UTC, datetime

_OFFERS_CACHE: list[dict] = []
_OFFERS_CACHE_AT: datetime | None = None


def set_offers_cache(offers: list[dict]) -> None:
    global _OFFERS_CACHE, _OFFERS_CACHE_AT
    _OFFERS_CACHE = list(offers or [])
    _OFFERS_CACHE_AT = datetime.now(UTC)


def get_offers_cache() -> list[dict]:
    return list(_OFFERS_CACHE)


def get_offers_cache_timestamp() -> datetime | None:
    return _OFFERS_CACHE_AT


def _norm(value: str | None) -> str:
    return (value or "").strip()


def build_index(offers: list[dict]) -> dict:
    countries: set[str] = set()
    states_by_country: dict[str, set[str]] = defaultdict(set)
    cities_by_country: dict[str, set[str]] = defaultdict(set)
    cities_by_country_state: dict[tuple[str, str], set[str]] = defaultdict(set)
    providers: set[str] = set()
    periods: set[str] = set()

    for offer in offers:
        country = _norm(offer.get("country")) or "Any"
        state = _norm(offer.get("state")) or "Any"
        city = _norm(offer.get("city")) or "Any"
        provider = _norm(offer.get("provider")) or "Any"
        period = _norm(offer.get("period")) or "Any"
        countries.add(country)
        states_by_country[country].add(state)
        cities_by_country[country].add(city)
        cities_by_country_state[(country, state)].add(city)
        providers.add(provider)
        periods.add(period)

    return {
        "countries": sorted(countries),
        "states_by_country": {k: sorted(v) for k, v in states_by_country.items()},
        "cities_by_country": {k: sorted(v) for k, v in cities_by_country.items()},
        "cities_by_country_state": {k: sorted(v) for k, v in cities_by_country_state.items()},
        "providers": sorted(providers),
        "periods": sorted(periods),
    }


def encode_token(value: str) -> str:
    raw = (value or "").encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_token(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return ""
    padding = "=" * ((4 - len(t) % 4) % 4)
    return base64.urlsafe_b64decode((t + padding).encode("ascii")).decode("utf-8", errors="ignore")


def filter_offers(
    offers: list[dict],
    *,
    country: str | None = None,
    state: str | None = None,
    city: str | None = None,
    provider: str | None = None,
    carrier: str | None = None,
    period: str | None = None,
) -> list[dict]:
    c = _norm(country)
    s = _norm(state)
    ci = _norm(city)
    p = _norm(provider)
    ca = _norm(carrier)
    pe = _norm(period)

    out = []
    for offer in offers:
        oc = _norm(offer.get("country")) or "Any"
        os = _norm(offer.get("state")) or "Any"
        oci = _norm(offer.get("city")) or "Any"
        op = _norm(offer.get("provider")) or "Any"
        oca = _norm(offer.get("carrier")) or op
        ope = _norm(offer.get("period")) or "Any"

        if c and c != "Any" and oc not in {c, "Any"}:
            continue
        if s and s != "Any" and os not in {s, "Any"}:
            continue
        if ci and ci != "Any" and oci not in {ci, "Any"}:
            continue
        if p and p != "Any" and op != p:
            continue
        if ca and ca != "Any" and oca != ca:
            continue
        if pe and pe != "Any" and ope != pe:
            continue
        out.append(offer)
    return out
