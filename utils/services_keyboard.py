import json
import os
import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from services.numbers.service_map import get_service_display_name, list_service_keys, resolve_canonical_service_key

MAX_TOP_SERVICES = 10
SERVICES_PER_ROW = 2
BASE_DIR = os.path.dirname(__file__)
TOP_FILE = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "top_services.json"))
USAGE_FILE = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "usage_stats.json"))
DEFAULT_TOP_SERVICES = [
    "telegram",
    "whatsapp",
    "gmail",
    "facebook",
    "instagram",
    "tiktok",
    "discord",
    "twitter",
    "amazon",
]
MAX_CALLBACK_DATA_LEN = 64
_FLOW_SERVICE_PREFIX = "flow:service:"


def _service_callback_data(service: str) -> str | None:
    value = f"{_FLOW_SERVICE_PREFIX}{service}"
    if len(value.encode("utf-8")) > MAX_CALLBACK_DATA_LEN:
        return None
    return value

def _canonical_service(service: str) -> str:
    return resolve_canonical_service_key(service)


def _service_label(service: str) -> str:
    label = get_service_display_name(service)
    if label:
        cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", str(label)).strip()
        return re.sub(r"\s{2,}", " ", cleaned) or str(label)
    normalized = (service or "").replace("_", " ").strip()
    normalized = re.sub(r"\s*\([^)]*\)\s*", " ", normalized).strip()
    normalized = re.sub(r"\s{2,}", " ", normalized)
    return normalized.title() if normalized else service


def load_full_services():
    return list_service_keys()


def load_top_services():
    try:
        with open(TOP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return list(data.keys())[:MAX_TOP_SERVICES]
            if isinstance(data, list):
                return data[:MAX_TOP_SERVICES]
    except Exception:
        pass

    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            usage = json.load(f)
            if isinstance(usage, dict):
                ranked = sorted(usage.items(), key=lambda x: x[1], reverse=True)
                return [k for k, _ in ranked[:MAX_TOP_SERVICES]]
    except Exception:
        pass

    return []


def build_services_keyboard() -> InlineKeyboardMarkup:
    full_services = load_full_services()
    available = {_canonical_service(s) for s in full_services}
    top_services: list[str] = []
    seen: set[str] = set()

    def _push(service: str) -> None:
        canonical = _canonical_service(service)
        if canonical not in available:
            return
        if canonical in seen:
            return
        if _service_callback_data(canonical) is None:
            return
        seen.add(canonical)
        top_services.append(canonical)

    for service in load_top_services():
        _push(service)

    if len(top_services) < MAX_TOP_SERVICES:
        for service in DEFAULT_TOP_SERVICES:
            _push(service)
            if len(top_services) >= MAX_TOP_SERVICES:
                break

    if len(top_services) < MAX_TOP_SERVICES:
        for service in full_services:
            _push(service)
            if len(top_services) >= MAX_TOP_SERVICES:
                break

    rows = []
    for i in range(0, len(top_services), SERVICES_PER_ROW):
        chunk = top_services[i : i + SERVICES_PER_ROW]
        row = [
            InlineKeyboardButton(
                text=_service_label(service),
                callback_data=cb_data,
            )
            for service in chunk
            for cb_data in [_service_callback_data(service)]
            if cb_data
        ]
        if row:
            rows.append(row)

    return InlineKeyboardMarkup(inline_keyboard=rows)
