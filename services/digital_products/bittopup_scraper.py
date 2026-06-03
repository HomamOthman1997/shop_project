from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

from config import settings
from database.digital_provider_sources_repo import record_price_watch_run, upsert_provider_source
from services.digital_products.fulfillment_rules import (
    MANUAL_TOPUP_MODE,
    game_family_key,
    manual_feature_info,
    offer_compare_key,
)
from services.digital_products.static_taxonomy import detect_service_key_strict, norm_text
from services.numbers.core.session_manager import SessionManager

BITTOPUP_PROVIDER = "bittopup"
BITTOPUP_BASE_URL = "https://bittopup.com"
BITTOPUP_GOODS_SITEMAP_URL = f"{BITTOPUP_BASE_URL}/goods-sitemap.xml"
PARSER_VERSION = "bittopup-html-v1"
_PRICE_WATCH_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class BitTopupOffer:
    source_url: str
    source_ref: str
    product_name: str
    denomination_name: str
    price_usd: float
    old_price_usd: float | None
    discount_percent: float | None
    compare_key: str
    parse_confidence: float
    available: bool = True


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html.unescape(text)
    return " ".join(text.split())


def _slug_from_url(url: str) -> str:
    path = urlparse(str(url or "")).path.strip("/")
    return path.split("/")[-1] if path else ""


def _money(value: Any) -> float:
    try:
        return round(float(str(value).replace(",", "").strip()), 6)
    except Exception:
        return 0.0


def _amount_label(value: str) -> str:
    text = str(value or "").strip()
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")


def _parse_discount(text: str) -> float | None:
    match = re.search(r"-\s*(\d+(?:\.\d+)?)\s*%", str(text or ""))
    if not match:
        return None
    val = _money(match.group(1))
    return val if val > 0 else None


def _extract_product_name(html_text: str, url: str) -> str:
    for pattern in (
        r"<h1[^>]*>\s*([^<]+?)\s*</h1>",
        r'<meta\s+property="og:title"\s+content="([^"]+)"',
        r'<title>\s*([^<]+?)\s*</title>',
    ):
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            name = _strip_tags(match.group(1))
            name = re.sub(r"\s*[-|]\s*(Recharge|Buy|Cheap|Safe|TOPUP.*).*$", "", name, flags=re.IGNORECASE).strip()
            if name:
                return name
    return _slug_from_url(url).replace("-", " ").title()


def _amount_unit_from_text(text: str, product_name: str) -> tuple[str, str]:
    normalized = norm_text(text).replace(",", "")
    unit_patterns = (
        ("uc", r"(\d+(?:\.\d+)?)(?:\s*\+\s*\d+(?:\.\d+)?)?\s*uc\b"),
        ("nc", r"(\d+(?:\.\d+)?)(?:\s*\+\s*\d+(?:\.\d+)?)?\s*nc\b"),
        ("diamond", r"(\d+(?:\.\d+)?)(?:\s*\+\s*\d+(?:\.\d+)?)?\s*diamonds?\b"),
        ("coin", r"(\d+(?:\.\d+)?)(?:\s*\+\s*\d+(?:\.\d+)?)?\s*coins?\b"),
        ("gem", r"(\d+(?:\.\d+)?)(?:\s*\+\s*\d+(?:\.\d+)?)?\s*gems?\b"),
        ("token", r"(\d+(?:\.\d+)?)(?:\s*\+\s*\d+(?:\.\d+)?)?\s*tokens?\b"),
        ("usd", r"\b(\d+(?:\.\d+)?)\s*usd\b"),
    )
    for unit, pattern in unit_patterns:
        bonus_match = re.search(rf"\b(\d+(?:\.\d+)?)\s+\d+(?:\.\d+)?\s*{unit}s?\b", normalized)
        if bonus_match:
            return _amount_label(bonus_match.group(1)), unit
        match = re.search(pattern, normalized)
        if match:
            return _amount_label(match.group(1)), unit
    family = game_family_key("", product_name)
    if family in {"pubg", "new_state"}:
        match = re.search(r"\b(\d+(?:\.\d+)?)\b", normalized)
        if match:
            return _amount_label(match.group(1)), "uc" if family == "pubg" else "nc"
    return "", ""


def _compare_key(product_name: str, denomination_name: str) -> tuple[str, float]:
    manual = manual_feature_info(product_name, denomination_name)
    if manual:
        key = offer_compare_key(
            family_key=manual.get("family_key"),
            region=manual.get("region") or "Global",
            offer_name=denomination_name,
        )
        return key, 0.9 if key else 0.45
    family = game_family_key("", product_name)
    amount, unit = _amount_unit_from_text(denomination_name, product_name)
    if family and amount and unit:
        return f"{family}:global:{amount}:{unit}", 0.86
    section = detect_service_key_strict(f"{product_name} {denomination_name}")
    if section == "store_cards":
        amount, unit = _amount_unit_from_text(denomination_name, product_name)
        if amount and unit == "usd":
            brand = re.sub(r"[^a-z0-9]+", "_", norm_text(product_name)).strip("_")
            region = "usa" if re.search(r"\b(us|usa|united states)\b", norm_text(product_name)) else "global"
            return f"{brand}:{region}:{amount}:usd", 0.78
    return "", 0.0


def parse_bittopup_product_page(html_text: str, *, url: str) -> list[BitTopupOffer]:
    if not html_text or "cf-error" in html_text.lower() or "captcha" in html_text.lower():
        return []
    product_name = _extract_product_name(html_text, url)
    blocks = re.split(r"<h3[^>]*>|###\s*", html_text, flags=re.IGNORECASE)
    offers: list[BitTopupOffer] = []
    seen: set[str] = set()
    for block in blocks:
        text = _strip_tags(block)
        if "USD" not in text:
            continue
        price_match = re.search(r"\bUSD\s*([0-9][0-9,]*(?:\.\d+)?)", text, flags=re.IGNORECASE)
        if not price_match:
            continue
        price = _money(price_match.group(1))
        if price <= 0:
            continue
        denom = text[: price_match.start()].strip(" -|")
        denom = re.sub(r"^Image\s+", "", denom, flags=re.IGNORECASE).strip()
        denom = re.sub(r"\s+-\s+\d+(?:\.\d+)?%\s*$", "", denom).strip()
        if not denom or len(denom) > 120:
            continue
        old_price = None
        old_match = re.search(r"\bUSD\s*[0-9][0-9,]*(?:\.\d+)?\s+USD\s*([0-9][0-9,]*(?:\.\d+)?)", text, flags=re.IGNORECASE)
        if old_match:
            old_price = _money(old_match.group(1))
        compare_key, confidence = _compare_key(product_name, denom)
        discount = _parse_discount(text)
        ref = f"{_slug_from_url(url)}#{re.sub(r'[^a-z0-9]+', '-', norm_text(denom)).strip('-')}"
        if ref in seen:
            continue
        seen.add(ref)
        offers.append(
            BitTopupOffer(
                source_url=url,
                source_ref=ref,
                product_name=product_name,
                denomination_name=denom,
                price_usd=price,
                old_price_usd=old_price if old_price and old_price > price else None,
                discount_percent=discount,
                compare_key=compare_key,
                parse_confidence=confidence,
            )
        )
    return offers


def parse_bittopup_sitemap(xml_text: str, *, limit: int = 0) -> list[str]:
    urls: list[str] = []
    try:
        root = ElementTree.fromstring(xml_text)
    except Exception:
        return []
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    for loc in root.findall(".//sm:loc", ns):
        url = str(loc.text or "").strip()
        if not url:
            continue
        if not url.startswith(BITTOPUP_BASE_URL):
            continue
        path = urlparse(url).path.strip("/")
        if not path or path in {"", "direct-topup", "game", "card"}:
            continue
        if any(part in path for part in ("/", "article", "reviews", "sitemap")):
            continue
        urls.append(url)
        if limit and len(urls) >= int(limit):
            break
    return urls


async def _fetch_text(url: str, *, timeout_sec: float = 25.0) -> str:
    session = await SessionManager.get_session()
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": "Mozilla/5.0 compatible; PhantomDigitalPriceWatch/1.0",
    }
    async with session.get(url, headers=headers, timeout=float(timeout_sec)) as resp:
        if int(resp.status) != 200:
            return ""
        return await resp.text()


async def scrape_bittopup_offers(*, max_pages: int | None = None) -> tuple[list[BitTopupOffer], dict[str, Any], list[str]]:
    limit = max(1, int(max_pages if max_pages is not None else getattr(settings, "digital_bittopup_max_pages", 80) or 80))
    timeout = max(5.0, float(getattr(settings, "digital_bittopup_request_timeout_sec", 25.0) or 25.0))
    errors: list[str] = []
    sitemap = await _fetch_text(BITTOPUP_GOODS_SITEMAP_URL, timeout_sec=timeout)
    urls = parse_bittopup_sitemap(sitemap, limit=limit)
    offers: list[BitTopupOffer] = []
    for url in urls:
        try:
            page = await _fetch_text(url, timeout_sec=timeout)
            parsed = parse_bittopup_product_page(page, url=url)
            offers.extend(parsed)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    stats = {"pages_checked": len(urls), "offers_seen": len(offers)}
    return offers, stats, errors


async def _run_bittopup_price_watch_unlocked(*, max_pages: int | None = None) -> dict[str, Any]:
    started = datetime.now(UTC)
    stats = {
        "pages_checked": 0,
        "offers_seen": 0,
        "active": 0,
        "under_review": 0,
        "unmapped": 0,
        "disabled": 0,
        "invalid": 0,
    }
    status = "success"
    errors: list[str] = []
    try:
        offers, scrape_stats, errors = await scrape_bittopup_offers(max_pages=max_pages)
        stats.update(scrape_stats)
        guardrail = max(0.0, float(getattr(settings, "digital_bittopup_price_guardrail_percent", 10.0) or 10.0))
        for offer in offers:
            res = await upsert_provider_source(
                provider=BITTOPUP_PROVIDER,
                source_ref=offer.source_ref,
                compare_key=offer.compare_key,
                source_url=offer.source_url,
                source_product_name=offer.product_name,
                source_denomination_name=offer.denomination_name,
                active_price=None,
                observed_price=offer.price_usd,
                available=offer.available,
                fulfillment_mode=MANUAL_TOPUP_MODE,
                parse_confidence=offer.parse_confidence,
                parser_version=PARSER_VERSION,
                source_payload={
                    "old_price_usd": offer.old_price_usd,
                    "discount_percent": offer.discount_percent,
                },
                max_auto_change_percent=guardrail,
            )
            key = str(res.get("status") or "invalid")
            stats[key] = int(stats.get(key) or 0) + 1
    except Exception as exc:
        status = "failed"
        errors.append(str(exc))
    finished = datetime.now(UTC)
    await record_price_watch_run(
        provider=BITTOPUP_PROVIDER,
        started_at=started,
        finished_at=finished,
        status=status,
        stats=stats,
        errors=errors,
    )
    return {"provider": BITTOPUP_PROVIDER, "status": status, **stats, "errors": len(errors)}


async def run_bittopup_price_watch(*, max_pages: int | None = None) -> dict[str, Any]:
    if _PRICE_WATCH_LOCK.locked():
        return {
            "provider": BITTOPUP_PROVIDER,
            "status": "skipped",
            "reason": "already_running",
            "pages_checked": 0,
            "offers_seen": 0,
            "active": 0,
            "under_review": 0,
            "unmapped": 0,
            "disabled": 0,
            "invalid": 0,
            "errors": 0,
        }
    async with _PRICE_WATCH_LOCK:
        return await _run_bittopup_price_watch_unlocked(max_pages=max_pages)
