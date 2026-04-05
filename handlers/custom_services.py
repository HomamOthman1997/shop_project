from __future__ import annotations

import html
import json
import logging
import re

from aiogram import Bot, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove

from config import OWNER_ID, settings
from database.bots_repo import get_reseller_id_for_bot
from database.custom_services_repo import (
    claim_endpoint_inventory,
    create_preorder_request,
    create_endpoint,
    create_folder,
    deactivate_node,
    ensure_root_node,
    get_next_pending_preorder,
    get_pending_preorder_position,
    get_preorder_request,
    get_node,
    list_children,
    mark_preorder_fulfilling,
    mark_preorder_fulfilled,
    move_node_in_parent,
    rename_node,
    reset_preorder_to_pending,
    release_endpoint_stock,
    reserve_endpoint_stock,
    set_endpoint_preorder_enabled,
    set_endpoint_inventory,
    update_node_display_text,
    update_endpoint,
    update_endpoint_product_info,
)
from database.financial_ledger import create_order_v3
from database.mongo import db
from database.orders_repo import update_order_details, update_order_status
from database.user_repo import get_user, get_user_reseller_for_bot, set_user_reseller_for_bot
from utils.bot_menu_context import is_main_bot, menu_for_current_bot
from utils.financial_manager import FinancialManager
from utils.loading_sticker import send_loading_sticker
from utils.permissions import is_reseller
from utils.reseller_setup_guard import get_reseller_setup_status, render_reseller_setup_notice
from utils.translations import t
from utils.user_money import format_usd

router = Router()
logger = logging.getLogger('custom_services')

_CANCEL_INPUTS = {"/cancel", "cancel", "الغاء", "إلغاء"}
_CATALOG_CUSTOM = "custom"
_CATALOG_ID_INFO = "id_info"
_FINANCIAL_CUSTOM = "custom"
_FINANCIAL_CORE = "core"
_CUSTOM_GRID_COLUMNS = 3
_MAX_FOLDER_CHILDREN = 9
_ID_INFO_ARCHIVED = True

def _is_services_trigger(text: str | None) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False

    lowered = raw.lower()
    exact_texts = {
        t("en", "btn_services"),
        t("ar", "btn_services"),
        "services",
        "الخدمات",
        "/services",
        "/custom",
        "/custom_services",
    }
    if raw in exact_texts or lowered in exact_texts:
        return True

    return "كوستوم" in raw or "custom services" in lowered


def _is_id_info_trigger(text: str | None) -> bool:
    if _ID_INFO_ARCHIVED:
        return False
    raw = (text or "").strip()
    if not raw:
        return False

    lowered = raw.lower()
    exact_texts = {
        t("en", "btn_id_info"),
        t("ar", "btn_id_info"),
        "id info",
        "id-info",
        "id_info",
        "/id_info",
        "/idinfo",
    }
    if raw in exact_texts or lowered in exact_texts:
        return True

    compact = lowered.replace(" ", "").replace("-", "").replace("_", "")
    return "idinfo" in compact or "اي دي" in raw or "ايدي" in raw



def _catalog_type_from_node(node: dict | None) -> str:
    raw = str((node or {}).get("catalog_type") or "").strip().lower()
    if raw in {"id_info", "idinfo", "id-info", "id info"}:
        return _CATALOG_ID_INFO
    return _CATALOG_CUSTOM


def _catalog_title(catalog_type: str) -> str:
    return "ID INFO" if catalog_type == _CATALOG_ID_INFO else t("en", "custom_services_title")


def _catalog_financial_mode(catalog_type: str) -> str:
    return _FINANCIAL_CUSTOM


def _builder_help_text(lang: str) -> str:
    if str(lang or "").lower().startswith("ar"):
        return (
            "دليل سريع للبيلدر:\n"
            "1) افتح مجلد ثم اضغط إضافة لإضافة مجلد/خدمة.\n"
            "2) استخدم إعادة التسمية/التحريك لترتيب الكتالوج.\n"
            "3) افتح الخدمة لتعديل النص/الملف والسعر والمخزون.\n"
            "4) جرب شراء الخدمة للتأكد من المخرجات قبل النشر."
        )
    return (
        "Builder quick guide:\n"
        "1) Open a folder then press Add to create folder/endpoint.\n"
        "2) Use rename/move to organize the catalog.\n"
        "3) Open endpoint to edit delivery text/file, price, and stock.\n"
        "4) Test-buy endpoint before publishing."
    )


def _services_landing_text(lang: str, *, owner_builder_available: bool) -> str:
    key = "services_landing_owner_text" if owner_builder_available else "services_landing_text"
    return t(lang, key)


def _services_landing_kb(lang: str, *, show_builder: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=t(lang, "services_open_catalog_button"), callback_data="cstm:entry:catalog")]
    ]
    if show_builder:
        rows.append([InlineKeyboardButton(text=t(lang, "services_open_builder_button"), callback_data="cstm:entry:builder")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="cstm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _is_cancel_input(text: str | None) -> bool:
    return (text or "").strip().lower() in _CANCEL_INPUTS


def _normalize_stock_block(block: str) -> str:
    lines = [line.strip() for line in str(block or "").splitlines() if line.strip()]
    normalized: list[str] = []
    label_map = {
        "الايميل": "Email",
        "email": "Email",
        "كلمة السر": "Password",
        "password": "Password",
        "الريكفري": "Recovery",
        "recovery": "Recovery",
    }
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
        elif "：" in line:
            key, value = line.split("：", 1)
        else:
            normalized.append(line)
            continue
        canonical = label_map.get(key.strip().lower())
        if canonical:
            normalized.append(f"{canonical}: {value.strip()}")
        else:
            normalized.append(f"{key.strip()}: {value.strip()}")
    return "\n".join(normalized).strip()


def _is_probable_ssn_table(text: str) -> bool:
    lowered = str(text or "").lower()
    return "|" in lowered and "ssn" in lowered and "dob" in lowered and "email" in lowered


def _is_probable_ssn_spaced_table(text: str) -> bool:
    lines = [line.strip().lower() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    header = lines[0]
    return all(token in header for token in ("first", "last", "address", "city", "zip", "dob", "ssn"))


def _is_probable_ssn_block(text: str) -> bool:
    lowered = str(text or "").lower()
    return (
        "account information" in lowered
        or "primary email:" in lowered
        or "mail pass:" in lowered
        or "\nssn:" in lowered
    )


def _is_probable_ssn_json(text: str) -> bool:
    stripped = str(text or "").strip()
    return (
        stripped.startswith("{")
        and '"ssn"' in stripped.lower()
        and ('"first_name"' in stripped.lower() or '"last_name"' in stripped.lower())
    )


def _normalize_gender(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered in {"m", "male"}:
        return "Male (m)"
    if lowered in {"f", "female"}:
        return "Female (f)"
    return raw


def _clean_structured_value(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.lower() in {"null", "none", "n/a", "na"}:
        return ""
    return re.sub(r"\s+", " ", raw).strip()


def _format_birthdate(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        year, month, day = raw.split("-")
        return f"{int(month)}/{int(day)}/{int(year)}"
    return raw


def _format_ssn(value: str) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 9:
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    raw = str(value or "").strip()
    return raw or None


def _format_phone(value: str) -> str | None:
    raw = _clean_structured_value(value)
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"{digits[:3]} {digits[3:6]}-{digits[6:]}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"{digits[1:4]} {digits[4:7]}-{digits[7:]}"
    return raw


def _parse_pipe_delimited_ssn_rows(text: str) -> list[str]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return []
    header_idx = next((idx for idx, line in enumerate(lines) if "|" in line and "ssn" in line.lower() and "dob" in line.lower()), -1)
    if header_idx < 0:
        return []
    headers = [part.strip().lower() for part in lines[header_idx].split("|")]
    records: list[str] = []
    for line in lines[header_idx + 1:]:
        if "|" not in line:
            continue
        values = [part.strip() for part in line.split("|")]
        if len(values) < 3:
            continue
        row = {headers[idx]: values[idx] if idx < len(values) else "" for idx in range(len(headers))}
        dob_value = str(row.get("dob", "") or row.get("dob (year-month-day)", "")).strip()
        fields = {
            "SSN": _format_ssn(row.get("ssn", "")) or "",
            "Birthdate": _format_birthdate(dob_value) or "",
            "Last Name": _clean_structured_value(str(row.get("lastname") or "")),
            "First Name": _clean_structured_value(str(row.get("firstname") or "")),
            "Middle Name": _clean_structured_value(str(row.get("middle") or "")),
            "Address": _clean_structured_value(str(row.get("address") or "")),
            "City": _clean_structured_value(str(row.get("city") or "")),
            "State": _clean_structured_value(str(row.get("state") or "")).upper(),
            "Zip": _clean_structured_value(str(row.get("zip") or "")),
            "Phone": _format_phone(str(row.get("phone") or "")) or "",
            "Email": _clean_structured_value(str(row.get("email") or "")),
            "Driver License": _clean_structured_value(str(row.get("driver license") or "")),
            "Issuing State": _clean_structured_value(str(row.get("iss_state") or "")).upper(),
        }
        rendered = _render_ssn_record(fields)
        if rendered:
            records.append(rendered)
    return records


def _parse_spaced_ssn_rows(text: str) -> list[str]:
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    header_parts = [part.strip().lower() for part in re.split(r"\s{2,}", lines[0].strip()) if part.strip()]
    expected = ["first", "last", "address", "city", "st", "zip", "dob", "ssn"]
    if header_parts[: len(expected)] != expected:
        return []

    records: list[str] = []
    for raw_line in lines[1:]:
        parts = [part.strip() for part in re.split(r"\s{2,}", raw_line.strip()) if part.strip()]
        if len(parts) < 8:
            continue
        row = dict(zip(expected, parts[-8:], strict=False))
        first_tokens = str(row.get("first") or "").split()
        fields = {
            "SSN": _format_ssn(row.get("ssn", "")) or "",
            "Birthdate": _format_birthdate(row.get("dob", "")) or "",
            "Last Name": _clean_structured_value(str(row.get("last") or "")),
            "First Name": first_tokens[0] if first_tokens else "",
            "Middle Name": _clean_structured_value(" ".join(first_tokens[1:])) if len(first_tokens) > 1 else "",
            "Address": _clean_structured_value(str(row.get("address") or "")),
            "City": _clean_structured_value(str(row.get("city") or "")),
            "State": _clean_structured_value(str(row.get("st") or "")).upper(),
            "Zip": _clean_structured_value(str(row.get("zip") or "")),
        }
        rendered = _render_ssn_record(fields)
        if rendered:
            records.append(rendered)
    return records


def _split_numbered_blocks(text: str) -> list[str]:
    chunks = [chunk.strip() for chunk in re.split(r"(?im)^\s*Number:\s*\d+\s*$", str(text or "")) if chunk.strip()]
    return chunks


def _looks_like_state_token(token: str) -> bool:
    raw = str(token or "").strip()
    return bool(re.fullmatch(r"[A-Za-z]{2}", raw))


def _looks_like_phone_token(token: str) -> bool:
    digits = re.sub(r"\D", "", str(token or ""))
    return 10 <= len(digits) <= 11


def _looks_like_zip_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d{5}(?:-\d{4})?", str(token or "").strip()))


def _looks_like_dob_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", str(token or "").strip()))


def _normalize_inline_ssn_payload(value: str) -> dict[str, str]:
    tokens = [tok for tok in re.split(r"\s+", str(value or "").strip()) if tok]
    if not tokens:
        return {}
    if tokens and tokens[-1].upper() in {"USA", "US"}:
        tokens = tokens[:-1]
    if len(tokens) < 7:
        return {}
    phone = tokens.pop() if tokens and _looks_like_phone_token(tokens[-1]) else ""
    ssn = tokens.pop() if tokens and re.fullmatch(r"\d{9}", tokens[-1]) else ""
    dob = tokens.pop() if tokens and _looks_like_dob_token(tokens[-1]) else ""
    zip_code = tokens.pop() if tokens and _looks_like_zip_token(tokens[-1]) else ""
    state = tokens.pop() if tokens and _looks_like_state_token(tokens[-1]) else ""
    if not all([phone, ssn, dob, zip_code, state]):
        return {}

    addr_start = next((idx for idx, token in enumerate(tokens) if re.search(r"\d", token)), -1)
    if addr_start <= 0:
        return {
            "Birthdate": _format_birthdate(dob) or dob,
            "Phone": phone,
            "SSN": _format_ssn(ssn) or ssn,
            "State": state,
            "Zip": zip_code,
        }

    street_suffixes = {"st", "street", "rd", "road", "ave", "avenue", "dr", "drive", "ct", "court", "ln", "lane", "blvd", "way", "apt", "unit", "f11", "se", "sw", "ne", "nw"}
    city_tokens: list[str] = []
    tail = tokens[addr_start:]
    while tail:
        candidate = tail[-1]
        lowered = candidate.lower()
        if city_tokens and (re.search(r"\d", candidate) or lowered in street_suffixes):
            break
        if re.search(r"\d", candidate) and not city_tokens:
            break
        city_tokens.insert(0, tail.pop())
        if len(city_tokens) >= 2:
            break
    name_tokens = tokens[:addr_start]
    address_tokens = tail
    first_name = name_tokens[0] if name_tokens else ""
    last_name = name_tokens[-1] if len(name_tokens) >= 2 else ""
    middle_name = " ".join(name_tokens[1:-1]).strip() if len(name_tokens) > 2 else ""
    return {
        "SSN": _format_ssn(ssn) or ssn,
        "Birthdate": _format_birthdate(dob) or dob,
        "First Name": _clean_structured_value(first_name),
        "Middle Name": _clean_structured_value(middle_name),
        "Last Name": _clean_structured_value(last_name),
        "Address": _clean_structured_value(" ".join(address_tokens)),
        "City": _clean_structured_value(" ".join(city_tokens)),
        "State": _clean_structured_value(state).upper(),
        "Zip": _clean_structured_value(zip_code),
        "Phone": _format_phone(phone) or phone,
    }


def _render_ssn_record(fields: dict[str, str]) -> str:
    ordered_keys = [
        "SSN",
        "Gender",
        "Birthdate",
        "Maiden Name",
        "Last Name",
        "First Name",
        "Middle Name",
        "Address",
        "City",
        "State",
        "Zip",
        "Phone",
        "Email",
        "Recovery Email",
        "Mail Password",
        "Bank Password",
        "Driver License",
        "Issuing State",
        "CC Type",
        "CCN",
        "CVV",
        "Expiration Date",
    ]
    lines = [f"{key}: {str(fields[key]).strip()}" for key in ordered_keys if str(fields.get(key) or "").strip()]
    return "\n\n".join(lines).strip()


def _parse_ssn_json_records(text: str) -> list[str]:
    stripped = str(text or "").strip()
    candidates: list[dict[str, object]] = []
    try:
        loaded = json.loads(stripped)
        if isinstance(loaded, list):
            candidates.extend(item for item in loaded if isinstance(item, dict))
        elif isinstance(loaded, dict):
            candidates.append(loaded)
    except json.JSONDecodeError:
        for block in re.split(r"\n\s*\n", stripped):
            candidate = block.strip().rstrip(",")
            if not candidate.startswith("{"):
                continue
            try:
                loaded = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict):
                candidates.append(loaded)

    records: list[str] = []
    for row in candidates:
        address = " ".join(
            part.strip()
            for part in [str(row.get("addr1") or ""), str(row.get("addr2") or "")]
            if part and str(part).strip()
        ).strip()
        fields = {
            "SSN": _format_ssn(str(row.get("ssn") or "")) or "",
            "Gender": _normalize_gender(str(row.get("gender") or "")) or "",
            "Birthdate": _format_birthdate(str(row.get("dob") or "")) or "",
            "Last Name": _clean_structured_value(str(row.get("last_name") or "")),
            "First Name": _clean_structured_value(str(row.get("first_name") or "")),
            "Middle Name": _clean_structured_value(str(row.get("middle_name") or "")),
            "Address": _clean_structured_value(address),
            "City": _clean_structured_value(str(row.get("city") or "")),
            "State": _clean_structured_value(str(row.get("state") or "")).upper(),
            "Zip": _clean_structured_value(str(row.get("zip") or "")),
            "Phone": _format_phone(str(row.get("phone") or "")) or "",
            "Email": _clean_structured_value(str(row.get("email") or "")),
            "Driver License": _clean_structured_value(str(row.get("driver_license") or row.get("driver license") or "")),
            "Issuing State": _clean_structured_value(str(row.get("iss_state") or "")).upper(),
        }
        rendered = _render_ssn_record(fields)
        if rendered:
            records.append(rendered)
    return records


def _parse_ssn_blocks(text: str) -> list[str]:
    records: list[str] = []
    for block in _split_numbered_blocks(text):
        fields: dict[str, str] = {}
        for raw_line in [line.strip() for line in str(block or "").splitlines() if line.strip()]:
            if raw_line.lower() == "account information":
                continue
            if ":" not in raw_line:
                continue
            key, value = raw_line.split(":", 1)
            label = key.strip().lower()
            data = value.strip()
            if label in {"primary email", "email"}:
                fields["Email"] = data
            elif label in {"recovary email", "recovery email"}:
                fields["Recovery Email"] = data
            elif label == "mail pass":
                fields["Mail Password"] = data
            elif label == "bank pass":
                fields["Bank Password"] = data
            elif label == "gender":
                gender = _normalize_gender(data)
                if gender:
                    fields["Gender"] = gender
            elif label == "ssn":
                parsed = _normalize_inline_ssn_payload(data)
                if parsed:
                    fields.update({k: v for k, v in parsed.items() if v})
                else:
                    ssn = _format_ssn(data)
                    if ssn:
                        fields["SSN"] = ssn
            else:
                fields[key.strip()] = data
        rendered = _render_ssn_record(fields)
        if rendered:
            records.append(rendered)
    return records


def _parse_generic_inventory_payload(text: str) -> list[str]:
    raw = html.unescape(str(text or "").strip())
    if not raw:
        return []

    normalized = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    normalized = re.sub(r"(?is)</?(div|span|label|p|textarea|body|html)[^>]*>", "\n", normalized)
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()

    blocks = []
    for block in re.split(r"(?:\n\s*={3,}\s*\n|={3,})", normalized):
        item = _normalize_stock_block(block)
        if item:
            blocks.append(item)
    if blocks:
        labeled_blocks = sum(
            1
            for block in blocks
            if any(line.startswith(("Email:", "Password:", "Recovery:")) for line in block.splitlines())
        )
        single_email_blocks = all(
            sum(1 for line in block.splitlines() if line.lower().startswith("email:")) <= 1
            for block in blocks
        )
        if labeled_blocks == len(blocks) and single_email_blocks:
            return blocks

    labeled_groups: list[str] = []
    current_group: list[str] = []
    label_pattern = re.compile(r"^(Email|Password|Recovery)\s*:", re.IGNORECASE)
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            if current_group:
                labeled_groups.append("\n".join(current_group))
                current_group = []
            continue
        if label_pattern.match(line):
            normalized_line = line
            if ":" in normalized_line:
                key, value = normalized_line.split(":", 1)
                normalized_line = f"{key.strip().title()}: {value.strip()}"
            if normalized_line.lower().startswith("email:") and current_group:
                labeled_groups.append("\n".join(current_group))
                current_group = []
            current_group.append(normalized_line)
            if len(current_group) >= 3:
                labels = {row.split(":", 1)[0].strip().lower() for row in current_group if ":" in row}
                if {"email", "password", "recovery"}.issubset(labels):
                    labeled_groups.append("\n".join(current_group))
                    current_group = []
            continue
        if current_group:
            current_group.append(line)
    if current_group:
        labeled_groups.append("\n".join(current_group))
    if labeled_groups and all(any(item.startswith(prefix) for prefix in ("Email:", "Password:", "Recovery:")) for block in labeled_groups for item in block.splitlines()):
        return [block.strip() for block in labeled_groups if block.strip()]

    return [line.strip() for line in normalized.splitlines() if line.strip()]


def _parse_inventory_payload(text: str, *, ssn_mode: bool = True) -> list[str]:
    raw = html.unescape(str(text or "").strip())
    if not raw:
        return []

    if ssn_mode and _is_probable_ssn_json(raw):
        parsed_json = _parse_ssn_json_records(raw)
        if parsed_json:
            return parsed_json

    if ssn_mode and _is_probable_ssn_table(raw):
        parsed_rows = _parse_pipe_delimited_ssn_rows(raw)
        if parsed_rows:
            return parsed_rows

    if ssn_mode and _is_probable_ssn_spaced_table(raw):
        parsed_rows = _parse_spaced_ssn_rows(raw)
        if parsed_rows:
            return parsed_rows

    if ssn_mode and _is_probable_ssn_block(raw):
        parsed_blocks = _parse_ssn_blocks(raw)
        if parsed_blocks:
            return parsed_blocks

    return _parse_generic_inventory_payload(raw)


def _is_ssn_stock_context(endpoint: dict | None, parent_node: dict | None = None) -> bool:
    parts = [
        str((endpoint or {}).get("name") or ""),
        str((parent_node or {}).get("name") or ""),
    ]
    return "ssn" in " ".join(parts).lower()


async def _is_ssn_stock_endpoint(endpoint: dict | None, reseller_id: int) -> bool:
    current = endpoint
    parent = None
    visited: set[str] = set()
    while current:
        if _is_ssn_stock_context(current, parent):
            return True
        parent_id = current.get("parent_id")
        if not parent_id:
            return False
        parent_key = str(parent_id)
        if parent_key in visited:
            return False
        visited.add(parent_key)
        parent = await get_node(parent_id, reseller_id=reseller_id)
        current = parent
    return False


def _ssn_missing_field_warnings(items: list[str]) -> list[str]:
    warnings: list[str] = []
    required_labels = ["SSN:", "Birthdate:", "Last Name:", "First Name:", "Address:", "City:", "State:", "Zip:"]
    for idx, item in enumerate(items, start=1):
        missing = [label.rstrip(":") for label in required_labels if label not in str(item or "")]
        if missing:
            warnings.append(f"Record {idx} is incomplete: missing {', '.join(missing)}")
    return warnings


def _parse_inventory_submission(text: str, *, ssn_mode: bool) -> tuple[list[str], str, list[str]]:
    raw_payload = html.unescape(str(text or "").strip())
    if not raw_payload:
        return [], "", []
    items = _parse_inventory_payload(raw_payload, ssn_mode=ssn_mode)
    warnings = _ssn_missing_field_warnings(items) if ssn_mode else []
    return items, raw_payload, warnings


def _stock_preview_text(items: list[str], warnings: list[str]) -> str:
    preview_items = [str(item or "").strip() for item in items[:2] if str(item or "").strip()]
    lines = [f"Parsed stock items: {len(items)}"]
    if warnings:
        lines.append(f"Warnings: {len(warnings)}")
    if preview_items:
        lines.extend(["", "Preview:", "", "\n\n=================\n\n".join(preview_items)])
        if len(items) > len(preview_items):
            lines.extend(["", f"... and {len(items) - len(preview_items)} more"])
    if warnings:
        lines.extend(["", "Warnings:"])
        for warning in warnings[:5]:
            lines.append(f"- {warning}")
        if len(warnings) > 5:
            lines.append(f"- ... and {len(warnings) - 5} more")
    lines.extend(["", "Save this stock?"])
    return "\n".join(lines).strip()


async def _safe_edit_text(
    message: types.Message,
    text: str,
    *,
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        error_text = str(exc).lower()
        if "message is not modified" in error_text:
            return
        if "message can't be edited" in error_text or "message cant be edited" in error_text:
            await message.answer(text, reply_markup=reply_markup)
            return
        raise


async def _user_lang(user_id: int) -> str:
    user = await get_user(int(user_id))
    return str((user or {}).get("language") or "en")


async def _is_current_bot_reseller(user_id: int, bot: Bot) -> bool:
    bot_id = (await bot.get_me()).id
    return await is_reseller(user_id, bot_id=bot_id)


async def _resolve_user_reseller(user_id: int, bot_id: int) -> int | None:
    if await is_main_bot(bot_id):
        return int(user_id)
    reseller_id = await get_user_reseller_for_bot(user_id, bot_id)
    if reseller_id:
        return int(reseller_id)
    inferred = await get_reseller_id_for_bot(bot_id)
    if inferred:
        await set_user_reseller_for_bot(user_id, bot_id, int(inferred))
        return int(inferred)
    return None


async def _resolve_catalog_owner_id(user_id: int, bot_id: int) -> int | None:
    if await is_main_bot(bot_id):
        owner_id = int(OWNER_ID or 0)
        return owner_id if owner_id > 0 else None
    return await _resolve_user_reseller(user_id, bot_id)


def _custom_services_admin_ids() -> set[int]:
    raw = str(getattr(settings, "custom_services_admin_ids", "") or "").strip()
    if not raw:
        return set()
    ids: set[int] = set()
    for chunk in raw.split(","):
        token = str(chunk or "").strip()
        if not token:
            continue
        try:
            value = int(token)
        except Exception:
            continue
        if value > 0:
            ids.add(value)
    return ids


async def _custom_services_access_level(user_id: int, bot: Bot) -> str:
    if await _is_current_bot_reseller(user_id, bot):
        return "full"
    if await is_main_bot((await bot.get_me()).id):
        if int(user_id) == int(OWNER_ID):
            return "full"
        if int(user_id) in _custom_services_admin_ids():
            return "ops"
    return "none"


async def _can_open_builder_catalog(user_id: int, bot: Bot) -> bool:
    return (await _custom_services_access_level(user_id, bot)) in {"full", "ops"}


async def _can_manage_builder(user_id: int, bot: Bot) -> bool:
    return (await _custom_services_access_level(user_id, bot)) in {"full", "ops"}


async def _can_manage_builder_structure(user_id: int, bot: Bot) -> bool:
    return (await _custom_services_access_level(user_id, bot)) == "full"


async def _can_toggle_preorder(user_id: int, bot: Bot) -> bool:
    return (await _custom_services_access_level(user_id, bot)) in {"full", "ops"} and await is_main_bot((await bot.get_me()).id)


def _state_catalog_owner_id(data: dict | None) -> int | None:
    try:
        value = int((data or {}).get("custom_catalog_owner_id") or 0)
    except Exception:
        return None
    return value if value > 0 else None


async def _builder_catalog_owner_id(user_id: int, bot: Bot, data: dict | None = None) -> int | None:
    state_owner_id = _state_catalog_owner_id(data)
    if state_owner_id:
        return state_owner_id
    access_level = await _custom_services_access_level(user_id, bot)
    if access_level == "none":
        return None
    if await is_main_bot((await bot.get_me()).id):
        owner_id = int(OWNER_ID or 0)
        return owner_id if owner_id > 0 else None
    return int(user_id)


def _endpoint_ready_for_sale(endpoint: dict | None) -> bool:
    node = endpoint or {}
    delivery_type = str(node.get("delivery_type") or "").strip().lower()
    if delivery_type == "inventory":
        return bool(list(node.get("inventory_items") or [])) and int(node.get("available_qty") or 0) > 0
    if delivery_type == "text":
        return bool(str(node.get("delivery_text") or "").strip())
    if delivery_type in {"photo", "document"}:
        return bool(str(node.get("delivery_file_id") or "").strip())
    return False


def _endpoint_preorder_enabled(endpoint: dict | None) -> bool:
    return bool((endpoint or {}).get("preorder_enabled"))


def _public_available_qty(endpoint: dict | None) -> int:
    node = endpoint or {}
    delivery_type = str(node.get("delivery_type") or "").strip().lower()
    if delivery_type == "inventory":
        return len([item for item in list(node.get("inventory_items") or []) if str(item or "").strip()])
    if _endpoint_ready_for_sale(node):
        return max(0, int(node.get("available_qty") or 0))
    return 0


def _public_endpoint_text(endpoint: dict, *, catalog_title: str, lang: str) -> str:
    name = str(endpoint.get("name") or "").strip()
    price = float(endpoint.get("price", 0) or 0)
    available = _public_available_qty(endpoint)
    product_info = str(endpoint.get("product_info_text") or "").strip()
    lines = [
        catalog_title,
        "",
        f"{t(lang, 'name_plain')}: {name}",
        f"{t(lang, 'price_label')}: {format_usd(price)}",
        f"{t(lang, 'available_plain')}: {available}",
    ]
    if product_info:
        lines.extend(["", product_info])
    elif available <= 0 and not _endpoint_preorder_enabled(endpoint):
        lines.extend(["", t(lang, "custom_service_unavailable")])
    return "\n".join(lines).strip()


async def _can_use_preorder(endpoint: dict | None, bot: Bot) -> bool:
    if not endpoint or not _endpoint_preorder_enabled(endpoint):
        return False
    bot_id = (await bot.get_me()).id
    return await is_main_bot(bot_id)


def _support_bridge_token() -> str:
    return str(getattr(settings, "bot_admin_token", "") or "").strip()


async def _platform_bridge_bot() -> Bot:
    token = _support_bridge_token()
    if not token:
        raise TelegramBadRequest(method="sendMessage", message="platform bridge bot is not configured")
    return Bot(token=token, timeout=30)


def _owner_preorder_queue_kb(preorder_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Fulfill FIFO", callback_data=f"custom_preorder:fulfill:{preorder_id}")],
        ]
    )


async def _notify_owner_preorder_created(
    *,
    preorder: dict,
    endpoint: dict,
    buyer_user: dict | None,
) -> None:
    target = await db.system_settings.find_one({"_id": "owner_notifications"}) or {}
    target_chat_id = target.get("chat_id")
    if not isinstance(target_chat_id, int):
        logger.warning("Custom preorder owner topic not configured preorder=%s", preorder.get("_id"))
        return

    username = "@" + str(buyer_user.get("username") or "").strip() if buyer_user and buyer_user.get("username") else "-"
    queue_position = await get_pending_preorder_position(preorder["_id"])
    text = (
        "Custom Service Preorder\n\n"
        f"Queue ID: {preorder['_id']}\n"
        f"Service: {str(preorder.get('service_name') or endpoint.get('name') or '-')}\n"
        f"Queue position: {queue_position}\n"
        f"User ID: {int(preorder.get('buyer_user_id') or 0)}\n"
        f"Username: {username}\n"
        f"Qty: {int(preorder.get('qty') or 0)}\n"
        f"Paid: {format_usd(float(preorder.get('total_price') or 0.0))}\n"
        f"Endpoint ID: {endpoint.get('_id')}\n"
        "Rule: fulfill in FIFO order only."
    )

    bridge_bot: Bot | None = None
    try:
        bridge_bot = await _platform_bridge_bot()
        kwargs = {
            "chat_id": int(target_chat_id),
            "text": text,
            "reply_markup": _owner_preorder_queue_kb(str(preorder["_id"])),
        }
        if target.get("message_thread_id") is not None:
            kwargs["message_thread_id"] = int(target.get("message_thread_id"))
        await bridge_bot.send_message(**kwargs)
    except Exception as exc:
        logger.exception("Custom preorder owner notify failed preorder=%s err=%s", preorder.get("_id"), exc)
    finally:
        if bridge_bot is not None:
            try:
                await bridge_bot.session.close()
            except Exception:
                pass


class CustomBuilderStates(StatesGroup):
    waiting_name = State()
    waiting_price = State()
    waiting_stock = State()
    waiting_min_qty = State()
    waiting_rename = State()
    waiting_display_text = State()
    waiting_delivery_payload = State()
    waiting_delivery_preview = State()
    waiting_product_info = State()
    waiting_buy_qty = State()
    waiting_buy_confirm = State()


async def _send_endpoint_delivery(
    *,
    bot: Bot,
    user_id: int,
    endpoint: dict,
    qty: int,
    lang: str,
    stock_items: list[str] | None = None,
) -> bool:
    qty_line = t(lang, "custom_qty_line").format(qty=int(qty))
    if stock_items:
        payload = "\n".join([str(item or "").strip() for item in stock_items if str(item or "").strip()])
        if not payload:
            return False
        await bot.send_message(
            chat_id=int(user_id),
            text=t(lang, "custom_digital_delivery_block").format(payload=payload, qty_line=qty_line),
        )
        return True

    delivery_type = str(endpoint.get("delivery_type") or "").strip().lower()
    if delivery_type == "text":
        text = str(endpoint.get("delivery_text") or "").strip()
        if not text:
            return False
        await bot.send_message(chat_id=int(user_id), text=t(lang, "custom_digital_delivery_block").format(payload=text, qty_line=qty_line))
        return True
    if delivery_type == "photo":
        file_id = str(endpoint.get("delivery_file_id") or "").strip()
        if not file_id:
            return False
        caption = str(endpoint.get("delivery_caption") or "").strip()
        if caption:
            caption = f"{caption}\n\n{qty_line}"
        else:
            caption = qty_line
        await bot.send_photo(chat_id=int(user_id), photo=file_id, caption=caption)
        return True
    if delivery_type == "document":
        file_id = str(endpoint.get("delivery_file_id") or "").strip()
        if not file_id:
            return False
        caption = str(endpoint.get("delivery_caption") or "").strip()
        if caption:
            caption = f"{caption}\n\n{qty_line}"
        else:
            caption = qty_line
        await bot.send_document(chat_id=int(user_id), document=file_id, caption=caption)
        return True
    return False


async def _auto_fulfill_inventory_preorders(
    *,
    bot: Bot,
    endpoint: dict,
    catalog_owner_id: int,
    catalog_type: str,
) -> list[str]:
    delivered: list[str] = []
    endpoint_id = endpoint.get("_id")
    if not endpoint_id:
        return delivered

    while True:
        preorder = await get_next_pending_preorder(endpoint_id)
        if not preorder:
            break

        qty = max(1, int(preorder.get("qty") or 1))
        claim = await claim_endpoint_inventory(endpoint_id, catalog_owner_id, qty, catalog_type=catalog_type)
        if not claim:
            break

        preorder_id = str(preorder.get("_id") or "").strip()
        claimed = await mark_preorder_fulfilling(preorder_id, actor_id=0)
        if not claimed:
            await release_endpoint_stock(
                endpoint_id,
                catalog_owner_id,
                qty,
                catalog_type=catalog_type,
                claimed_items=list(claim.get("claimed_items") or []),
            )
            break

        buyer_user_id = int(claimed.get("buyer_user_id") or 0)
        order_id = claimed.get("order_id")
        claimed_items = [str(item or "").strip() for item in list(claim.get("claimed_items") or []) if str(item or "").strip()]
        if buyer_user_id <= 0 or not claimed_items:
            await reset_preorder_to_pending(preorder_id)
            await release_endpoint_stock(
                endpoint_id,
                catalog_owner_id,
                qty,
                catalog_type=catalog_type,
                claimed_items=claimed_items,
            )
            break

        try:
            user = await get_user(buyer_user_id)
            lang = str((user or {}).get("language") or "en")
            await _send_endpoint_delivery(
                bot=bot,
                user_id=buyer_user_id,
                endpoint=endpoint,
                qty=qty,
                lang=lang,
                stock_items=claimed_items,
            )
            await mark_preorder_fulfilled(preorder_id, actor_id=0)
            if order_id:
                await update_order_details(
                    order_id,
                    {
                        "status": "success",
                        "custom_preorder_fulfilled_automatically": True,
                        "remaining_qty": int(claim.get("remaining_qty") or 0),
                    },
                )
                await update_order_status(order_id, "success")
            delivered.append(preorder_id)
        except Exception:
            logger.exception("Custom preorder auto-fulfill failed preorder=%s", preorder_id)
            await reset_preorder_to_pending(preorder_id)
            await release_endpoint_stock(
                endpoint_id,
                catalog_owner_id,
                qty,
                catalog_type=catalog_type,
                claimed_items=claimed_items,
            )
            break

    return delivered


def _delivery_preview_text(
    *,
    endpoint: dict,
    qty: int,
    lang: str,
    stock_items: list[str] | None = None,
) -> str | None:
    qty_line = t(lang, "custom_qty_line").format(qty=int(qty))
    if stock_items:
        payload = "\n".join([str(item or "").strip() for item in stock_items if str(item or "").strip()])
        if not payload:
            return None
        return t(lang, "custom_digital_delivery_block").format(payload=payload, qty_line=qty_line)

    delivery_type = str(endpoint.get("delivery_type") or "").strip().lower()
    if delivery_type == "text":
        text = str(endpoint.get("delivery_text") or "").strip()
        if not text:
            return None
        return t(lang, "custom_digital_delivery_block").format(payload=text, qty_line=qty_line)
    return None


def _node_btn(node: dict) -> InlineKeyboardButton:
    name = str(node.get("name") or t("en", "unnamed_plain"))
    return InlineKeyboardButton(
        text=name[:60],
        callback_data=f"cstm:open:{node['_id']}",
    )


def _builder_add_options_kb(
    node_id: str,
    node_type: str,
    *,
    is_root: bool = False,
    can_add_folder: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if node_type == "folder":
        if can_add_folder:
            rows.append([InlineKeyboardButton(text=t("en", "custom_add_folder"), callback_data=f"cstm:addf:{node_id}")])
        if not is_root:
            rows.append([InlineKeyboardButton(text=t("en", "custom_add_endpoint"), callback_data=f"cstm:adde:{node_id}")])
    rows.append([InlineKeyboardButton(text=t("en", "back"), callback_data=f"cstm:open:{node_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _allowed_move_directions(position: int) -> list[str]:
    dirs: list[str] = []
    col = int(position % _CUSTOM_GRID_COLUMNS)
    if position >= _CUSTOM_GRID_COLUMNS:
        dirs.append("up")
    dirs.append("down")
    if col > 0:
        dirs.append("left")
    if col < (_CUSTOM_GRID_COLUMNS - 1):
        dirs.append("right")
    return dirs


def _move_inline_buttons_for_item(node_id: str, position: int) -> list[InlineKeyboardButton]:
    labels = {
        "up": "⬆️",
        "down": "⬇️",
        "left": "⬅️",
        "right": "➡️",
    }
    buttons: list[InlineKeyboardButton] = []
    allowed = set(_allowed_move_directions(position))
    for direction in ("up", "down", "left", "right"):
        if direction in allowed:
            buttons.append(
                InlineKeyboardButton(
                    text=labels[direction],
                    callback_data=f"cstm:move:{direction}:{node_id}",
                )
            )
    return buttons


def _children_grid_preview_rows(children: list[dict]) -> list[list[InlineKeyboardButton]]:
    if not children:
        return []
    pos_to_child: dict[int, dict] = {}
    max_pos = 0
    for idx, child in enumerate(children):
        pos = int(child.get("position", idx))
        if pos < 0:
            pos = idx
        pos_to_child[pos] = child
        if pos > max_pos:
            max_pos = pos

    rows: list[list[InlineKeyboardButton]] = []
    row_start = 0
    while row_start <= max_pos:
        row_buttons: list[InlineKeyboardButton] = []
        for col in range(_CUSTOM_GRID_COLUMNS):
            slot = row_start + col
            child = pos_to_child.get(slot)
            if child:
                row_buttons.append(_node_btn(child))
            else:
                row_buttons.append(InlineKeyboardButton(text=t("en", "empty_slot_plain"), callback_data=f"cstm:noop:slot{slot}"))
        rows.append(row_buttons)
        row_start += _CUSTOM_GRID_COLUMNS
    return rows


def _children_customer_rows(children: list[dict]) -> list[list[InlineKeyboardButton]]:
    if not children:
        return []
    row_map: dict[int, list[tuple[int, dict]]] = {}
    for idx, child in enumerate(children):
        pos = int(child.get("position", idx))
        if pos < 0:
            pos = idx
        row_idx = int(pos // _CUSTOM_GRID_COLUMNS)
        col_idx = int(pos % _CUSTOM_GRID_COLUMNS)
        row_map.setdefault(row_idx, []).append((col_idx, child))

    rows: list[list[InlineKeyboardButton]] = []
    for row_idx in sorted(row_map.keys()):
        ordered = sorted(row_map[row_idx], key=lambda x: x[0])
        rows.append([_node_btn(child) for _, child in ordered])
    return rows


async def _move_controls_for_node(
    *,
    reseller_id: int,
    node: dict,
    catalog_type: str,
) -> list[InlineKeyboardButton]:
    if bool(node.get("is_root")):
        return []
    parent_id = node.get("parent_id")
    if not parent_id:
        return []
    siblings = await list_children(reseller_id, parent_id, catalog_type=catalog_type)
    if not siblings:
        return []
    index = next((i for i, item in enumerate(siblings) if str(item.get("_id")) == str(node.get("_id"))), -1)
    if index < 0:
        return []
    node_pos = int(node.get("position", index))
    if node_pos < 0:
        node_pos = index
    return _move_inline_buttons_for_item(str(node["_id"]), node_pos)


async def _render_node(
    message_or_cb: types.Message | types.CallbackQuery,
    state: FSMContext,
    reseller_id: int,
    node_id,
    *,
    is_builder: bool,
    catalog_type: str,
    viewer_user_id: int | None = None,
    edit_existing_message: bool = False,
) -> None:
    node = await get_node(node_id, reseller_id=reseller_id, catalog_type=catalog_type)
    if not node:
        err = t("en", "node_not_found_plain")
        if isinstance(message_or_cb, types.CallbackQuery):
            await message_or_cb.answer(err, show_alert=True)
        else:
            await message_or_cb.answer(err)
        return

    viewer_id = int(viewer_user_id or message_or_cb.from_user.id)
    normalized_catalog = _catalog_type_from_node(node)
    if _ID_INFO_ARCHIVED and normalized_catalog == _CATALOG_ID_INFO:
        user = await get_user(viewer_id)
        lang = (user or {}).get("language", "en")
        await state.clear()
        if isinstance(message_or_cb, types.CallbackQuery):
            await message_or_cb.answer(t(lang, "no_id_info_services"), show_alert=True)
        else:
            await message_or_cb.answer(t(lang, "no_id_info_services"))
        return

    ui_state = await state.get_data()
    children = await list_children(reseller_id, node["_id"], catalog_type=normalized_catalog)
    is_root_folder = bool(node.get("is_root")) and str(node.get("node_type") or "") == "folder"
    if is_root_folder:
        children = [child for child in children if str(child.get("node_type") or "") == "folder"]
    kb_rows: list[list[InlineKeyboardButton]] = []

    node_type = str(node.get("node_type") or "")
    layout_node_id = str(ui_state.get("custom_layout_node_id") or "")
    layout_mode = bool(is_builder and node_type == "folder" and layout_node_id == str(node.get("_id")))
    parent_id = node.get("parent_id")
    catalog_title = "ID INFO" if normalized_catalog == _CATALOG_ID_INFO else t("en", "custom_services_title")
    viewer_lang = await _user_lang(viewer_id)
    access_level = await _custom_services_access_level(viewer_id, message_or_cb.bot) if is_builder else "none"
    can_manage_ops = access_level in {"full", "ops"}
    can_manage_structure = access_level == "full"

    if node_type == "folder" and is_builder and layout_mode and can_manage_structure:
        kb_rows.extend(_children_grid_preview_rows(children))
        if children:
            kb_rows.append([InlineKeyboardButton(text=t("en", "divider_plain"), callback_data="cstm:noop:divider")])
        for idx, child in enumerate(children):
            child_pos = int(child.get("position", idx))
            if child_pos < 0:
                child_pos = idx
            item_row = [_node_btn(child)]
            item_row.extend(_move_inline_buttons_for_item(str(child["_id"]), child_pos))
            kb_rows.append(item_row)
    elif node_type == "folder":
        kb_rows.extend(_children_customer_rows(children))
    else:
        row: list[InlineKeyboardButton] = []
        columns = _CUSTOM_GRID_COLUMNS if is_builder else 2
        for child in children:
            row.append(_node_btn(child))
            if len(row) == columns:
                kb_rows.append(row)
                row = []
        if row:
            kb_rows.append(row)

    if node_type == "endpoint":
        price = float(node.get("price", 0))
        stock = int(node.get("available_qty", 0))
        min_q = int(node.get("min_qty", 1))
        delivery_type = str(node.get("delivery_type") or "").strip().lower()
        inventory_count = len(list(node.get("inventory_items") or []))
        delivery_status = t(viewer_lang, "configured_plain") if delivery_type in {"text", "photo", "document", "inventory"} else t(viewer_lang, "not_configured_plain")
        has_product_info = bool(str(node.get("product_info_text") or "").strip())
        preorder_enabled = _endpoint_preorder_enabled(node)
        if is_builder:
            text = (
                f"{catalog_title} - {t(viewer_lang, 'endpoint_plain')}\n\n"
                f"{t(viewer_lang, 'name_plain')}: {node.get('name')}\n"
                f"{t(viewer_lang, 'price_label')}: {format_usd(price)}\n"
                f"{t(viewer_lang, 'available_plain')}: {stock}\n"
                f"{t(viewer_lang, 'minimum_qty_plain')}: {min_q}\n"
                f"{t(viewer_lang, 'delivery_plain')}: {delivery_status}\n"
                f"{t(viewer_lang, 'stock_items_plain')}: {inventory_count}\n"
                f"{t(viewer_lang, 'product_info_plain')}: {t(viewer_lang, 'set_plain') if has_product_info else t(viewer_lang, 'not_set_plain')}\n"
                f"Preorder: {'Enabled' if preorder_enabled else 'Disabled'}"
            )
        else:
            text = _public_endpoint_text(node, catalog_title=catalog_title, lang=viewer_lang)
        if is_builder and can_manage_ops:
            if can_manage_structure:
                kb_rows.append(
                    [
                        InlineKeyboardButton(text=t(viewer_lang, "rename_plain"), callback_data=f"cstm:rename:{node['_id']}"),
                        InlineKeyboardButton(text=t(viewer_lang, "edit_plain"), callback_data=f"cstm:edit:{node['_id']}"),
                    ]
                )
            else:
                kb_rows.append([InlineKeyboardButton(text=t(viewer_lang, "edit_plain"), callback_data=f"cstm:edit:{node['_id']}")])
            kb_rows.append([InlineKeyboardButton(text=t(viewer_lang, "custom_set_stock"), callback_data=f"cstm:delivery:{node['_id']}")])
            kb_rows.append([InlineKeyboardButton(text=t(viewer_lang, "product_info_plain"), callback_data=f"cstm:pinfo:{node['_id']}")])
            if await _can_toggle_preorder(viewer_id, message_or_cb.bot):
                kb_rows.append(
                    [
                        InlineKeyboardButton(
                            text="Disable Preorder" if preorder_enabled else "Enable Preorder",
                            callback_data=f"cstm:preordertoggle:{node['_id']}",
                        )
                    ]
                )
            if can_manage_structure:
                endpoint_move = await _move_controls_for_node(
                    reseller_id=reseller_id,
                    node=node,
                    catalog_type=normalized_catalog,
                )
                if endpoint_move:
                    kb_rows.append(endpoint_move)
                kb_rows.append([InlineKeyboardButton(text=t(viewer_lang, "delete_plain"), callback_data=f"cstm:del:{node['_id']}")])
        else:
            if _endpoint_ready_for_sale(node):
                kb_rows.append([InlineKeyboardButton(text=t(viewer_lang, "buy_plain"), callback_data=f"cstm:buy:{node['_id']}")])
            elif await _can_use_preorder(node, message_or_cb.bot):
                kb_rows.append([InlineKeyboardButton(text="Reserve", callback_data=f"cstm:buy:{node['_id']}")])

        back_cb = f"cstm:open:{parent_id}" if parent_id else "cstm:cancel"
        kb_rows.append([InlineKeyboardButton(text=t(viewer_lang, "back"), callback_data=back_cb)])

    else:
        name = str(node.get("name") or ("ID INFO" if normalized_catalog == _CATALOG_ID_INFO else t(viewer_lang, "services_plain")))
        custom_display_text = str(node.get("display_text") or "").strip()
        if custom_display_text:
            text = custom_display_text
        else:
            text = catalog_title if bool(node.get("is_root")) else name

        if is_builder:
            if layout_mode and can_manage_structure:
                kb_rows.append([InlineKeyboardButton(text=t(viewer_lang, "done_plain"), callback_data=f"cstm:layoutdone:{node['_id']}")])
            elif can_manage_structure:
                kb_rows.append([InlineKeyboardButton(text=t(viewer_lang, "add_plain"), callback_data=f"cstm:add:{node['_id']}")])
                kb_rows.append(
                    [
                        InlineKeyboardButton(text=t(viewer_lang, "rename_plain"), callback_data=f"cstm:rename:{node['_id']}"),
                        InlineKeyboardButton(text=t(viewer_lang, "custom_edit_text"), callback_data=f"cstm:edittxt:{node['_id']}"),
                    ]
                )
                kb_rows.append([InlineKeyboardButton(text=t(viewer_lang, "custom_move_folder"), callback_data=f"cstm:layout:{node['_id']}")])
                if not bool(node.get("is_root")):
                    folder_move = await _move_controls_for_node(
                        reseller_id=reseller_id,
                        node=node,
                        catalog_type=normalized_catalog,
                    )
                    if folder_move:
                        kb_rows.append(folder_move)
                    kb_rows.append([InlineKeyboardButton(text=t(viewer_lang, "delete_plain"), callback_data=f"cstm:del:{node['_id']}")])
        back_cb = f"cstm:open:{parent_id}" if parent_id else "cstm:cancel"
        kb_rows.append([InlineKeyboardButton(text=t(viewer_lang, "back"), callback_data=back_cb)])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None

    if isinstance(message_or_cb, types.CallbackQuery):
        if message_or_cb.message:
            await _safe_edit_text(message_or_cb.message, text, reply_markup=kb)
    else:
        if edit_existing_message:
            await _safe_edit_text(message_or_cb, text, reply_markup=kb)
        else:
            await message_or_cb.answer(text, reply_markup=kb)

    await state.update_data(
        custom_current_node=str(node["_id"]),
        custom_mode="builder" if is_builder else "user",
        custom_catalog_type=normalized_catalog,
        custom_financial_mode=_catalog_financial_mode(normalized_catalog),
    )


@router.message(lambda m: _is_services_trigger(m.text))
async def open_custom_user(message: types.Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    bot_id = (await message.bot.get_me()).id
    can_open_builder = await is_main_bot(bot_id) and await _can_open_builder_catalog(message.from_user.id, message.bot)
    catalog_owner_id = await _resolve_catalog_owner_id(message.from_user.id, bot_id)
    wallet_scope_id = await _resolve_user_reseller(message.from_user.id, bot_id)
    if not catalog_owner_id or not wallet_scope_id:
        return await message.answer(t(lang, "no_custom_services"))

    root = await ensure_root_node(catalog_owner_id, catalog_type=_CATALOG_CUSTOM)
    children = await list_children(int(catalog_owner_id), root["_id"], catalog_type=_CATALOG_CUSTOM)
    if not children and not can_open_builder:
        return await message.answer(t(lang, "no_custom_services"), reply_markup=ReplyKeyboardRemove())
    await send_loading_sticker(message, remove_keyboard=True, fallback_text="Loading...")

    if can_open_builder:
        owner_root = await ensure_root_node(int(OWNER_ID), catalog_type=_CATALOG_CUSTOM)
        await state.update_data(
            custom_bot_id=bot_id,
            custom_catalog_owner_id=int(OWNER_ID),
            custom_wallet_scope_id=int(wallet_scope_id),
            custom_root_node_id=str(owner_root["_id"]),
            custom_mode="builder",
            custom_catalog_type=_CATALOG_CUSTOM,
            custom_financial_mode=_FINANCIAL_CUSTOM,
        )
        return await _render_node(
            message,
            state,
            int(OWNER_ID),
            owner_root["_id"],
            is_builder=True,
            catalog_type=_CATALOG_CUSTOM,
            viewer_user_id=message.from_user.id,
            edit_existing_message=False,
        )

    await state.update_data(
        custom_bot_id=bot_id,
        custom_catalog_owner_id=int(catalog_owner_id),
        custom_wallet_scope_id=int(wallet_scope_id),
        custom_root_node_id=str(root["_id"]),
        custom_mode="user",
        custom_catalog_type=_CATALOG_CUSTOM,
        custom_financial_mode=_FINANCIAL_CUSTOM,
    )
    return await _render_node(
        message,
        state,
        int(catalog_owner_id),
        root["_id"],
        is_builder=False,
        catalog_type=_CATALOG_CUSTOM,
        viewer_user_id=message.from_user.id,
        edit_existing_message=False,
    )


@router.callback_query(lambda c: c.data == "cstm:entry:catalog")
async def open_services_catalog_entry(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = await _user_lang(callback.from_user.id)
    catalog_owner_id = int(data.get("custom_catalog_owner_id") or 0)
    root_node_id = str(data.get("custom_root_node_id") or "").strip()
    if catalog_owner_id <= 0 or not root_node_id:
        return await callback.answer(t(lang, "custom_service_unavailable"), show_alert=True)
    await callback.answer()
    await _render_node(
        callback,
        state,
        catalog_owner_id,
        root_node_id,
        is_builder=False,
        catalog_type=_CATALOG_CUSTOM,
    )


@router.callback_query(lambda c: c.data == "cstm:entry:builder")
async def open_services_builder_entry(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    bot_id = (await callback.bot.get_me()).id
    if not await is_main_bot(bot_id) or not await _can_open_builder_catalog(callback.from_user.id, callback.bot):
        return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)
    await state.clear()
    root = await ensure_root_node(int(OWNER_ID), catalog_type=_CATALOG_CUSTOM)
    await state.update_data(
        custom_catalog_owner_id=int(OWNER_ID),
        custom_mode="builder",
        custom_catalog_type=_CATALOG_CUSTOM,
        custom_financial_mode=_FINANCIAL_CUSTOM,
    )
    await callback.answer()
    await _render_node(
        callback,
        state,
        int(OWNER_ID),
        root["_id"],
        is_builder=True,
        catalog_type=_CATALOG_CUSTOM,
    )
    if callback.message:
        await callback.message.answer(_builder_help_text(lang))


@router.message(lambda m: _is_id_info_trigger(m.text))
async def open_id_info_user(message: types.Message, state: FSMContext):
    if _ID_INFO_ARCHIVED:
        user = await get_user(message.from_user.id)
        lang = (user or {}).get("language", "en")
        await state.clear()
        return await message.answer(t(lang, "no_id_info_services"))
    await state.clear()
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    bot_id = (await message.bot.get_me()).id
    reseller_id = await _resolve_user_reseller(message.from_user.id, bot_id)
    if not reseller_id:
        return await message.answer(t(lang, "no_id_info_services"))
    root = await ensure_root_node(reseller_id, catalog_type=_CATALOG_ID_INFO)
    children = await list_children(int(reseller_id), root["_id"], catalog_type=_CATALOG_ID_INFO)
    if not children:
        return await message.answer(t(lang, "no_id_info_services"), reply_markup=ReplyKeyboardRemove())

    await message.answer(t(lang, "id_info_temp"), reply_markup=ReplyKeyboardRemove())
    await state.update_data(
        custom_bot_id=bot_id,
        custom_mode="user",
        custom_catalog_type=_CATALOG_ID_INFO,
        custom_financial_mode=_FINANCIAL_CUSTOM,
    )
    await _render_node(
        message,
        state,
        int(reseller_id),
        root["_id"],
        is_builder=False,
        catalog_type=_CATALOG_ID_INFO,
    )

@router.message(lambda m: (m.text or "").strip().lower() in {"/custom_builder", "custom builder"})
async def open_custom_builder(message: types.Message, state: FSMContext):
    if not await _can_open_builder_catalog(message.from_user.id, message.bot):
        return await message.answer(t(await _user_lang(message.from_user.id), "reseller_only_command"))
    lang = (await get_user(message.from_user.id) or {}).get("language", "en")
    bot_id = (await message.bot.get_me()).id
    if not await is_main_bot(bot_id):
        setup_status = await get_reseller_setup_status(message.from_user.id)
        if not bool(setup_status.get("ready")):
            return await message.answer(render_reseller_setup_notice(lang, setup_status))
    await state.clear()
    catalog_owner_id = int(OWNER_ID) if await is_main_bot(bot_id) else int(message.from_user.id)
    root = await ensure_root_node(catalog_owner_id, catalog_type=_CATALOG_CUSTOM)
    await state.update_data(
        custom_catalog_owner_id=catalog_owner_id,
        custom_mode="builder",
        custom_catalog_type=_CATALOG_CUSTOM,
        custom_financial_mode=_FINANCIAL_CUSTOM,
    )
    await _render_node(
        message,
        state,
        catalog_owner_id,
        root["_id"],
        is_builder=True,
        catalog_type=_CATALOG_CUSTOM,
    )
    await message.answer(_builder_help_text(lang))


@router.message(lambda m: (m.text or "").strip().lower() in {"/id_info_builder", "/idinfo_builder", "id info builder"})
async def open_id_info_builder(message: types.Message, state: FSMContext):
    if _ID_INFO_ARCHIVED:
        user = await get_user(message.from_user.id)
        lang = (user or {}).get("language", "en")
        await state.clear()
        return await message.answer(t(lang, "no_id_info_services"))
    if not await _can_manage_builder(message.from_user.id, message.bot):
        return await message.answer(t(await _user_lang(message.from_user.id), "reseller_only_command"))
    lang = (await get_user(message.from_user.id) or {}).get("language", "en")
    setup_status = await get_reseller_setup_status(message.from_user.id)
    if not bool(setup_status.get("ready")):
        return await message.answer(render_reseller_setup_notice(lang, setup_status))
    await state.clear()
    root = await ensure_root_node(message.from_user.id, catalog_type=_CATALOG_ID_INFO)
    await state.update_data(
        custom_mode="builder",
        custom_catalog_type=_CATALOG_ID_INFO,
        custom_financial_mode=_FINANCIAL_CUSTOM,
    )
    await _render_node(
        message,
        state,
        message.from_user.id,
        root["_id"],
        is_builder=True,
        catalog_type=_CATALOG_ID_INFO,
    )


@router.callback_query(lambda c: c.data == "rsmenu:custom_services")
async def open_custom_builder_from_menu(callback: types.CallbackQuery, state: FSMContext):
    bot_id = (await callback.bot.get_me()).id
    if not await _can_open_builder_catalog(callback.from_user.id, callback.bot):
        return await callback.answer(t(await _user_lang(callback.from_user.id), "reseller_only_command"), show_alert=True)
    lang = (await get_user(callback.from_user.id) or {}).get("language", "en")
    if not await is_main_bot(bot_id):
        setup_status = await get_reseller_setup_status(callback.from_user.id)
        if not bool(setup_status.get("ready")):
            await callback.answer(t(lang, "reseller_setup_blocked_alert"), show_alert=True)
            if callback.message:
                await callback.message.answer(render_reseller_setup_notice(lang, setup_status))
            return
    await callback.answer()
    await state.clear()
    catalog_owner_id = int(OWNER_ID) if await is_main_bot(bot_id) else int(callback.from_user.id)
    root = await ensure_root_node(catalog_owner_id, catalog_type=_CATALOG_CUSTOM)
    await state.update_data(
        custom_catalog_owner_id=catalog_owner_id,
        custom_mode="builder",
        custom_catalog_type=_CATALOG_CUSTOM,
        custom_financial_mode=_FINANCIAL_CUSTOM,
    )
    if callback.message:
        await _render_node(
            callback,
            state,
            catalog_owner_id,
            root["_id"],
            is_builder=True,
            catalog_type=_CATALOG_CUSTOM,
        )
        await callback.message.answer(_builder_help_text(lang))


@router.callback_query(lambda c: c.data == "rsmenu:id_info_services")
async def open_id_info_builder_from_menu(callback: types.CallbackQuery, state: FSMContext):
    if _ID_INFO_ARCHIVED:
        user = await get_user(callback.from_user.id)
        lang = (user or {}).get("language", "en")
        await state.clear()
        return await callback.answer(t(lang, "no_id_info_services"), show_alert=True)
    if not await _can_manage_builder(callback.from_user.id, callback.bot):
        return await callback.answer(t(await _user_lang(callback.from_user.id), "reseller_only_command"), show_alert=True)
    lang = (await get_user(callback.from_user.id) or {}).get("language", "en")
    setup_status = await get_reseller_setup_status(callback.from_user.id)
    if not bool(setup_status.get("ready")):
        await callback.answer(t(lang, "reseller_setup_blocked_alert"), show_alert=True)
        if callback.message:
            await callback.message.answer(render_reseller_setup_notice(lang, setup_status))
        return
    await callback.answer()
    await state.clear()
    root = await ensure_root_node(callback.from_user.id, catalog_type=_CATALOG_ID_INFO)
    await state.update_data(
        custom_mode="builder",
        custom_catalog_type=_CATALOG_ID_INFO,
        custom_financial_mode=_FINANCIAL_CUSTOM,
    )
    if callback.message:
        await _render_node(
            callback,
            state,
            callback.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=_CATALOG_ID_INFO,
        )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:open:"))
async def open_node(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id)
    if not node:
        return await callback.answer(t(lang, "node_not_found_plain"), show_alert=True)

    node_catalog_type = _catalog_type_from_node(node)
    if _ID_INFO_ARCHIVED and node_catalog_type == _CATALOG_ID_INFO:
        user = await get_user(callback.from_user.id)
        lang = (user or {}).get("language", "en")
        await state.clear()
        return await callback.answer(t(lang, "no_id_info_services"), show_alert=True)

    data = await state.get_data()
    explicit_mode = data.get("custom_mode")
    is_owner_reseller = await _is_current_bot_reseller(callback.from_user.id, callback.bot)
    bot_id = (await callback.message.bot.get_me()).id
    main_bot_flow = await is_main_bot(bot_id)
    catalog_owner_id_state = int(data.get("custom_catalog_owner_id") or 0)

    if explicit_mode == "builder":
        expected_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, data)
        if not await _can_open_builder_catalog(callback.from_user.id, callback.bot) or int(node.get("reseller_id") or 0) != expected_owner_id:
            return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)
        is_builder = True
    elif explicit_mode == "user":
        if main_bot_flow:
            expected_owner_id = int(OWNER_ID or 0)
            if expected_owner_id <= 0 or int(node.get("reseller_id") or 0) != expected_owner_id:
                return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)
        else:
            user_reseller = await _resolve_user_reseller(callback.from_user.id, bot_id)
            if not user_reseller or int(user_reseller) != int(node.get("reseller_id") or 0):
                return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)
        if catalog_owner_id_state and int(node.get("reseller_id") or 0) != catalog_owner_id_state:
            return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)
        is_builder = False
    else:
        # Fallback: if owner/reseller opens own node, treat as builder; otherwise user mode checks.
        fallback_builder_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, data)
        if fallback_builder_owner_id and int(node.get("reseller_id") or 0) == int(fallback_builder_owner_id):
            is_builder = True
        else:
            if main_bot_flow:
                if int(node.get("reseller_id") or 0) != int(OWNER_ID or 0):
                    return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)
            else:
                user_reseller = await _resolve_user_reseller(callback.from_user.id, bot_id)
                if not user_reseller or int(user_reseller) != int(node.get("reseller_id") or 0):
                    return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)
            is_builder = False

    await state.update_data(custom_layout_node_id=None)
    await callback.answer()
    await _render_node(
        callback,
        state,
        int(node["reseller_id"]),
        node_id,
        is_builder=is_builder,
        catalog_type=node_catalog_type,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:add:"))
async def add_options(callback: types.CallbackQuery, state: FSMContext):
    if not await _can_manage_builder_structure(callback.from_user.id, callback.bot):
        return await callback.answer(t(await _user_lang(callback.from_user.id), "reseller_only_command"), show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(await _user_lang(callback.from_user.id), "access_denied_plain"), show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=catalog_owner_id)
    if not node:
        return await callback.answer(t(await _user_lang(callback.from_user.id), "node_not_found_plain"), show_alert=True)

    if callback.message:
        can_add_folder = True
        if str(node.get("node_type") or "") == "folder":
            children = await list_children(
                catalog_owner_id,
                node["_id"],
                catalog_type=_catalog_type_from_node(node),
            )
            folder_count = sum(1 for child in children if str(child.get("node_type") or "") == "folder")
            can_add_folder = folder_count < _MAX_FOLDER_CHILDREN
        kb = _builder_add_options_kb(
            str(node_id),
            str(node.get("node_type") or "folder"),
            is_root=bool(node.get("is_root")),
            can_add_folder=can_add_folder,
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
    await callback.answer()


@router.callback_query(
    lambda c: c.data
    and (
        c.data.startswith("cstm:addf:")
        or c.data.startswith("cstm:adde:")
        or c.data.startswith("cstm:adds:")
        or c.data.startswith("cstm:addse:")
    )
)
async def add_entry_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _can_manage_builder_structure(callback.from_user.id, callback.bot):
        return await callback.answer(t(await _user_lang(callback.from_user.id), "reseller_only_command"), show_alert=True)
    lang = await _user_lang(callback.from_user.id)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)

    _, mode, anchor_id = callback.data.split(":", 2)
    anchor = await get_node(anchor_id, reseller_id=catalog_owner_id)
    if not anchor:
        return await callback.answer(t(lang, "node_not_found_plain"), show_alert=True)

    if mode in {"addf", "adde"} and str(anchor.get("node_type")) != "folder":
        return await callback.answer(t(lang, "custom_cannot_add_inside_endpoint"), show_alert=True)
    if mode == "adde" and bool(anchor.get("is_root")):
        return await callback.answer(t(lang, "custom_main_folder_subfolders_only"), show_alert=True)
    if mode in {"adds", "addse"}:
        parent_id = anchor.get("parent_id")
        if not parent_id:
            return await callback.answer(t(lang, "custom_node_has_no_parent"), show_alert=True)
        parent_node = await get_node(parent_id, reseller_id=catalog_owner_id)
        if not parent_node or str(parent_node.get("node_type") or "") != "folder":
            return await callback.answer(t(lang, "custom_parent_folder_not_found"), show_alert=True)
        anchor = parent_node
        # Convert sibling modes to normal add modes under parent.
        mode = "addf" if mode == "adds" else "adde"

    if mode == "addf":
        children = await list_children(
            catalog_owner_id,
            anchor["_id"],
            catalog_type=_catalog_type_from_node(anchor),
        )
        folder_count = sum(1 for child in children if str(child.get("node_type") or "") == "folder")
        if folder_count >= _MAX_FOLDER_CHILDREN:
            return await callback.answer(t(lang, "custom_max_folders"), show_alert=True)

    return_node_id = str(anchor["_id"])
    catalog_type = _catalog_type_from_node(anchor)

    await state.update_data(
        builder_add_mode=mode,
        builder_anchor_id=str(anchor["_id"]),
        builder_return_node_id=return_node_id,
        custom_mode="builder",
        custom_catalog_type=catalog_type,
        custom_financial_mode=_catalog_financial_mode(catalog_type),
    )
    await state.set_state(CustomBuilderStates.waiting_name)

    if callback.message:
        await callback.message.answer(
            t(lang, "custom_send_new_name"),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"cstm:stateback:{anchor_id}")]
                ]
            ),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:stateback:"))
async def builder_state_back(callback: types.CallbackQuery, state: FSMContext):
    if not await _can_manage_builder_structure(callback.from_user.id, callback.bot):
        return await callback.answer(t(await _user_lang(callback.from_user.id), "reseller_only_command"), show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(await _user_lang(callback.from_user.id), "access_denied_plain"), show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=catalog_owner_id)
    if not node:
        await state.clear()
        return await callback.answer(t(await _user_lang(callback.from_user.id), "node_not_found_plain"), show_alert=True)

    catalog_type = _catalog_type_from_node(node)
    await state.clear()
    await callback.answer()
    if callback.message:
        await _render_node(
            callback,
            state,
            catalog_owner_id,
            node["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )


@router.message(CustomBuilderStates.waiting_name)
async def add_entry_name(message: types.Message, state: FSMContext):
    if not await _can_manage_builder_structure(message.from_user.id, message.bot):
        await state.clear()
        return
    data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(message.from_user.id, message.bot, data)
    if not catalog_owner_id:
        await state.clear()
        return

    if _is_cancel_input(message.text):
        catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
        await state.clear()
        root = await ensure_root_node(catalog_owner_id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            catalog_owner_id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    name = (message.text or "").strip()
    if not name:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_name_cannot_be_empty"))

    add_mode = str(data.get("builder_add_mode") or "")
    anchor = await get_node(data.get("builder_anchor_id"), reseller_id=catalog_owner_id)
    if not anchor:
        await state.clear()
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_anchor_not_found"))
    catalog_type = _catalog_type_from_node(anchor)

    return_node_id = data.get("builder_return_node_id") or str(anchor["_id"])

    if add_mode == "addf":
        children = await list_children(
            catalog_owner_id,
            anchor["_id"],
            catalog_type=catalog_type,
        )
        folder_count = sum(1 for child in children if str(child.get("node_type") or "") == "folder")
        if folder_count >= _MAX_FOLDER_CHILDREN:
            await state.clear()
            await message.answer(t(await _user_lang(message.from_user.id), "custom_max_folders"))
            return await _render_node(
                message,
                state,
                catalog_owner_id,
                return_node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        await create_folder(catalog_owner_id, anchor["_id"], name, catalog_type=catalog_type)
        await state.clear()
        await message.answer(t(await _user_lang(message.from_user.id), "custom_folder_created"))
        return await _render_node(
            message,
            state,
            catalog_owner_id,
            return_node_id,
            is_builder=True,
            catalog_type=catalog_type,
        )

    if add_mode not in {"adde", "addf"}:
        await state.clear()
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_unsupported_add_mode"))

    await state.update_data(builder_name=name)
    await state.set_state(CustomBuilderStates.waiting_price)
    await message.answer(t(await _user_lang(message.from_user.id), "custom_send_endpoint_price"))


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:rename:"))
async def rename_node_start(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    if not await _can_manage_builder_structure(callback.from_user.id, callback.bot):
        return await callback.answer(t(lang, "reseller_only_command"), show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=catalog_owner_id)
    if not node:
        return await callback.answer(t(lang, "node_not_found_plain"), show_alert=True)

    catalog_type = _catalog_type_from_node(node)
    await state.update_data(
        rename_node_id=str(node["_id"]),
        rename_return_node_id=str(node["_id"]),
        custom_mode="builder",
        custom_catalog_type=catalog_type,
        custom_financial_mode=_catalog_financial_mode(catalog_type),
    )
    await state.set_state(CustomBuilderStates.waiting_rename)

    if callback.message:
        await callback.message.answer(
            t(lang, "custom_send_new_name_now").format(current=str(node.get("name") or "-"))
        )
    await callback.answer()


@router.message(CustomBuilderStates.waiting_rename)
async def rename_node_submit(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("custom_mode") == "builder" and not await _can_manage_builder_structure(message.from_user.id, message.bot):
        await state.clear()
        return
    catalog_owner_id = await _builder_catalog_owner_id(message.from_user.id, message.bot, data)
    if not catalog_owner_id:
        await state.clear()
        return

    if _is_cancel_input(message.text):
        catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
        node_id = data.get("rename_return_node_id")
        await state.clear()
        if node_id:
            return await _render_node(
                message,
                state,
                catalog_owner_id,
                node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        root = await ensure_root_node(catalog_owner_id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            catalog_owner_id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    new_name = (message.text or "").strip()
    if not new_name:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_name_cannot_be_empty"))

    node_id = data.get("rename_node_id")
    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    updated = await rename_node(node_id, catalog_owner_id, new_name, catalog_type=catalog_type)
    await state.clear()
    if not updated:
        return await message.answer(t(await _user_lang(message.from_user.id), "node_not_found_plain"))

    await message.answer(t(await _user_lang(message.from_user.id), "custom_name_updated"))
    return await _render_node(
        message,
        state,
        catalog_owner_id,
        updated["_id"],
        is_builder=True,
        catalog_type=catalog_type,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:edittxt:"))
async def edit_display_text_start(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    if not await _can_manage_builder_structure(callback.from_user.id, callback.bot):
        return await callback.answer(t(lang, "reseller_only_command"), show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=catalog_owner_id)
    if not node:
        return await callback.answer(t(lang, "node_not_found_plain"), show_alert=True)
    if str(node.get("node_type") or "") != "folder":
        return await callback.answer(t(lang, "custom_text_folders_only"), show_alert=True)

    catalog_type = _catalog_type_from_node(node)
    await state.update_data(
        edit_text_node_id=str(node["_id"]),
        edit_text_return_node_id=str(node["_id"]),
        custom_mode="builder",
        custom_catalog_type=catalog_type,
        custom_financial_mode=_catalog_financial_mode(catalog_type),
    )
    await state.set_state(CustomBuilderStates.waiting_display_text)

    current_text = str(node.get("display_text") or "").strip() or "-"
    if callback.message:
        await callback.message.answer(
            t(lang, "custom_send_folder_display_text").format(current=current_text)
        )
    await callback.answer()


@router.message(CustomBuilderStates.waiting_display_text)
async def edit_display_text_submit(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not await _can_manage_builder_structure(message.from_user.id, message.bot):
        await state.clear()
        return
    catalog_owner_id = await _builder_catalog_owner_id(message.from_user.id, message.bot, data)
    if not catalog_owner_id:
        await state.clear()
        return

    if _is_cancel_input(message.text):
        catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
        node_id = data.get("edit_text_return_node_id")
        await state.clear()
        if node_id:
            return await _render_node(
                message,
                state,
                catalog_owner_id,
                node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        root = await ensure_root_node(catalog_owner_id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            catalog_owner_id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    node_id = data.get("edit_text_node_id")
    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    raw_text = (message.text or "").strip()
    if raw_text.lower() in {"clear", "/clear", "مسح"}:
        raw_text = ""
    elif len(raw_text) > 500:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_text_too_long"))

    updated = await update_node_display_text(
        node_id=node_id,
        reseller_id=catalog_owner_id,
        display_text=raw_text,
        catalog_type=catalog_type,
    )
    await state.clear()
    if not updated:
        return await message.answer(t(await _user_lang(message.from_user.id), "node_not_found_plain"))

    await message.answer(t(await _user_lang(message.from_user.id), "custom_display_text_updated"))
    return await _render_node(
        message,
        state,
        catalog_owner_id,
        updated["_id"],
        is_builder=True,
        catalog_type=catalog_type,
    )


@router.message(CustomBuilderStates.waiting_price)
async def add_endpoint_price(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("custom_mode") == "builder" and not await _can_manage_builder(message.from_user.id, message.bot):
        await state.clear()
        return
    catalog_owner_id = await _builder_catalog_owner_id(message.from_user.id, message.bot, data)
    if data.get("custom_mode") == "builder" and not catalog_owner_id:
        await state.clear()
        return

    if _is_cancel_input(message.text):
        catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
        await state.clear()
        root = await ensure_root_node(catalog_owner_id or message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            catalog_owner_id or message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    try:
        price = float((message.text or "").strip())
    except Exception:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_invalid_price"))

    if price <= 0:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_price_gt_zero"))

    if data.get("edit_endpoint_id"):
        await state.update_data(edit_price=price)
    else:
        await state.update_data(builder_price=price)

    await state.set_state(CustomBuilderStates.waiting_stock)
    await message.answer(t(await _user_lang(message.from_user.id), "custom_send_available_quantity"))


@router.message(CustomBuilderStates.waiting_stock)
async def add_endpoint_stock(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("custom_mode") == "builder" and not await _can_manage_builder(message.from_user.id, message.bot):
        await state.clear()
        return
    catalog_owner_id = await _builder_catalog_owner_id(message.from_user.id, message.bot, data)
    if data.get("custom_mode") == "builder" and not catalog_owner_id:
        await state.clear()
        return

    if _is_cancel_input(message.text):
        catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
        await state.clear()
        root = await ensure_root_node(catalog_owner_id or message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            catalog_owner_id or message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    try:
        stock = int((message.text or "").strip())
    except Exception:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_invalid_quantity"))

    if stock < 0:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_quantity_zero_or_greater"))

    if data.get("edit_endpoint_id"):
        updated = await update_endpoint(
            data.get("edit_endpoint_id"),
            catalog_owner_id or message.from_user.id,
            price=float(data.get("edit_price")),
            available_qty=stock,
            min_qty=1,
            catalog_type=str(data.get("custom_catalog_type") or _CATALOG_CUSTOM),
        )
        return_node_id = data.get("edit_return_node_id")
        catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
        await state.clear()
        if not updated:
            return await message.answer(t(await _user_lang(message.from_user.id), "custom_endpoint_not_found"))

        await message.answer(t(await _user_lang(message.from_user.id), "custom_endpoint_updated"))
        if return_node_id:
            return await _render_node(
                message,
                state,
                catalog_owner_id or message.from_user.id,
                return_node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        root = await ensure_root_node(catalog_owner_id or message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            catalog_owner_id or message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )
    else:
        anchor = await get_node(data.get("builder_anchor_id"), reseller_id=catalog_owner_id or message.from_user.id)
        if not anchor:
            await state.clear()
            return await message.answer(t(await _user_lang(message.from_user.id), "custom_anchor_not_found"))
        if bool(anchor.get("is_root")):
            await state.clear()
            return await message.answer(t(await _user_lang(message.from_user.id), "custom_main_folder_subfolders_only"))

        parent_id = anchor["_id"] if data.get("builder_add_mode") == "adde" else anchor.get("parent_id")
        catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
        await create_endpoint(
            reseller_id=catalog_owner_id or message.from_user.id,
            parent_id=parent_id,
            name=str(data.get("builder_name") or "").strip(),
            price=float(data.get("builder_price")),
            available_qty=stock,
            min_qty=1,
            catalog_type=catalog_type,
        )

        return_node_id = data.get("builder_return_node_id") or str(anchor["_id"])
        await state.clear()
        await message.answer(t(await _user_lang(message.from_user.id), "custom_endpoint_created_success"))
        await _render_node(
            message,
            state,
            catalog_owner_id or message.from_user.id,
            return_node_id,
            is_builder=True,
            catalog_type=catalog_type,
        )
        return


@router.message(CustomBuilderStates.waiting_min_qty)
async def add_endpoint_min(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("custom_mode") == "builder" and not await _can_manage_builder(message.from_user.id, message.bot):
        await state.clear()
        return
    catalog_owner_id = await _builder_catalog_owner_id(message.from_user.id, message.bot, data)
    if data.get("custom_mode") == "builder" and not catalog_owner_id:
        await state.clear()
        return

    if _is_cancel_input(message.text):
        catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
        await state.clear()
        root = await ensure_root_node(catalog_owner_id or message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            catalog_owner_id or message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    try:
        min_qty = int((message.text or "").strip())
    except Exception:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_invalid_minimum_quantity"))

    if min_qty < 1:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_minimum_quantity_at_least_one"))

    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    if data.get("edit_endpoint_id"):
        updated = await update_endpoint(
            data.get("edit_endpoint_id"),
            catalog_owner_id or message.from_user.id,
            price=float(data.get("edit_price")),
            available_qty=int(data.get("edit_stock")),
            min_qty=min_qty,
            catalog_type=catalog_type,
        )
        return_node_id = data.get("edit_return_node_id")
        await state.clear()
        if not updated:
            return await message.answer(t(await _user_lang(message.from_user.id), "custom_endpoint_not_found"))

        await message.answer(t(await _user_lang(message.from_user.id), "custom_endpoint_updated"))
        if return_node_id:
            return await _render_node(
                message,
                state,
                catalog_owner_id or message.from_user.id,
                return_node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        root = await ensure_root_node(catalog_owner_id or message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            catalog_owner_id or message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    anchor = await get_node(data.get("builder_anchor_id"), reseller_id=catalog_owner_id or message.from_user.id)
    if not anchor:
        await state.clear()
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_anchor_not_found"))
    if bool(anchor.get("is_root")):
        await state.clear()
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_main_folder_subfolders_only"))

    parent_id = anchor["_id"] if data.get("builder_add_mode") == "adde" else anchor.get("parent_id")
    await create_endpoint(
        reseller_id=catalog_owner_id or message.from_user.id,
        parent_id=parent_id,
        name=str(data.get("builder_name") or "").strip(),
        price=float(data.get("builder_price")),
        available_qty=int(data.get("builder_stock")),
        min_qty=min_qty,
        catalog_type=catalog_type,
    )

    return_node_id = data.get("builder_return_node_id") or str(anchor["_id"])
    await state.clear()
    await message.answer(t(await _user_lang(message.from_user.id), "custom_endpoint_created_success"))
    await _render_node(
        message,
        state,
        catalog_owner_id or message.from_user.id,
        return_node_id,
        is_builder=True,
        catalog_type=catalog_type,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:edit:"))
async def edit_endpoint_start(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    if not await _can_manage_builder(callback.from_user.id, callback.bot):
        return await callback.answer(t(lang, "reseller_only_command"), show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    endpoint = await get_node(node_id, reseller_id=catalog_owner_id)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        return await callback.answer(t(lang, "custom_endpoint_not_found"), show_alert=True)

    await state.update_data(
        edit_endpoint_id=str(endpoint["_id"]),
        edit_return_node_id=str(endpoint.get("parent_id") or endpoint["_id"]),
        custom_mode="builder",
        custom_catalog_type=_catalog_type_from_node(endpoint),
        custom_financial_mode=_catalog_financial_mode(_catalog_type_from_node(endpoint)),
    )
    await state.set_state(CustomBuilderStates.waiting_price)

    if callback.message:
        await callback.message.answer(
            t(lang, "custom_send_new_price_now").format(current=float(endpoint.get("price", 0)))
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:preordertoggle:"))
async def toggle_endpoint_preorder(callback: types.CallbackQuery, state: FSMContext):
    if not await _can_toggle_preorder(callback.from_user.id, callback.bot):
        return await callback.answer("Main-bot only", show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer("No permission", show_alert=True)

    node_id = str(callback.data or "").split(":", 2)[2]
    endpoint = await get_node(node_id, reseller_id=catalog_owner_id)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        return await callback.answer("Endpoint not found", show_alert=True)

    updated = await set_endpoint_preorder_enabled(
        endpoint["_id"],
        catalog_owner_id,
        not _endpoint_preorder_enabled(endpoint),
        catalog_type=_catalog_type_from_node(endpoint),
    )
    if not updated:
        return await callback.answer("Update failed", show_alert=True)

    if callback.message:
        await _render_node(
            callback,
            state,
            catalog_owner_id,
            updated["_id"],
            is_builder=True,
            catalog_type=_catalog_type_from_node(updated),
        )
    await callback.answer("Preorder updated")


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:delivery:"))
async def set_delivery_start(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    if not await _can_manage_builder(callback.from_user.id, callback.bot):
        return await callback.answer(t(lang, "reseller_only_command"), show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    endpoint = await get_node(node_id, reseller_id=catalog_owner_id)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        return await callback.answer(t(lang, "custom_endpoint_not_found"), show_alert=True)

    catalog_type = _catalog_type_from_node(endpoint)
    await state.update_data(
        delivery_endpoint_id=str(endpoint["_id"]),
        delivery_return_node_id=str(endpoint["_id"]),
        custom_mode="builder",
        custom_catalog_type=catalog_type,
        custom_financial_mode=_catalog_financial_mode(catalog_type),
    )
    await state.set_state(CustomBuilderStates.waiting_delivery_payload)

    if callback.message:
        await callback.message.answer(t(lang, "custom_send_stock_lines"))
    await callback.answer()


@router.message(CustomBuilderStates.waiting_delivery_payload)
async def set_delivery_submit(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not await _can_manage_builder(message.from_user.id, message.bot):
        await state.clear()
        return
    catalog_owner_id = await _builder_catalog_owner_id(message.from_user.id, message.bot, data)
    if not catalog_owner_id:
        await state.clear()
        return
    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    endpoint_id = data.get("delivery_endpoint_id")
    return_node_id = data.get("delivery_return_node_id")
    endpoint = await get_node(endpoint_id, reseller_id=catalog_owner_id)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        await state.clear()
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_endpoint_not_found"))
    if _is_cancel_input(message.text):
        await state.clear()
        if return_node_id:
            return await _render_node(
                message,
                state,
                catalog_owner_id,
                return_node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        root = await ensure_root_node(catalog_owner_id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            catalog_owner_id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    text = str(message.text or "").strip()
    if not text:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_send_stock_lines_plain_text"))
    ssn_mode = await _is_ssn_stock_endpoint(endpoint, catalog_owner_id)
    items, raw_payload, warnings = _parse_inventory_submission(text, ssn_mode=ssn_mode)
    if not items:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_no_valid_stock_lines"))
    await state.update_data(
        delivery_preview_raw_payload=raw_payload,
        delivery_preview_items=items,
        delivery_preview_warnings=warnings,
        delivery_preview_ssn_mode=ssn_mode,
    )
    await state.set_state(CustomBuilderStates.waiting_delivery_preview)
    await message.answer(
        _stock_preview_text(items, warnings),
        reply_markup=_stock_preview_kb(await _user_lang(message.from_user.id)),
    )


@router.callback_query(lambda c: c.data == "cstm:stockretry")
async def retry_delivery_stock_preview(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = await _user_lang(callback.from_user.id)
    if not await _can_manage_builder(callback.from_user.id, callback.bot):
        await state.clear()
        return await callback.answer(t(lang, "reseller_only_command"), show_alert=True)
    await state.set_state(CustomBuilderStates.waiting_delivery_payload)
    if callback.message:
        await callback.message.answer(t(lang, "custom_send_stock_lines"))
    await callback.answer()


@router.callback_query(lambda c: c.data == "cstm:stockcancel")
async def cancel_delivery_stock_preview(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = await _user_lang(callback.from_user.id)
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, data)
    return_node_id = data.get("delivery_return_node_id")
    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    await state.clear()
    if not catalog_owner_id:
        return await callback.answer()
    target_node = return_node_id
    if not target_node:
        root = await ensure_root_node(catalog_owner_id, catalog_type=catalog_type)
        target_node = root["_id"]
    if callback.message and target_node:
        await _render_node(
            callback,
            state,
            catalog_owner_id,
            target_node,
            is_builder=True,
            catalog_type=catalog_type,
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "cstm:stocksave")
async def save_delivery_stock_preview(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = await _user_lang(callback.from_user.id)
    if not await _can_manage_builder(callback.from_user.id, callback.bot):
        await state.clear()
        return await callback.answer(t(lang, "reseller_only_command"), show_alert=True)
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, data)
    if not catalog_owner_id:
        await state.clear()
        return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)

    endpoint_id = data.get("delivery_endpoint_id")
    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    items = [str(item or "").strip() for item in list(data.get("delivery_preview_items") or []) if str(item or "").strip()]
    raw_payload = str(data.get("delivery_preview_raw_payload") or "").strip()
    warnings = [str(item or "").strip() for item in list(data.get("delivery_preview_warnings") or []) if str(item or "").strip()]
    if not items:
        await state.set_state(CustomBuilderStates.waiting_delivery_payload)
        if callback.message:
            await callback.message.answer(t(lang, "custom_send_stock_lines"))
        return await callback.answer()

    updated = await set_endpoint_inventory(
        endpoint_id,
        catalog_owner_id,
        inventory_items=items,
        raw_payload=raw_payload,
        parse_warnings=warnings,
        catalog_type=catalog_type,
    )
    await state.clear()
    if not updated:
        return await callback.answer(t(lang, "custom_failed_save_delivery_payload"), show_alert=True)
    fulfilled_preorders = await _auto_fulfill_inventory_preorders(
        bot=callback.bot,
        endpoint=updated,
        catalog_owner_id=catalog_owner_id,
        catalog_type=catalog_type,
    )
    refreshed = await get_node(updated["_id"], reseller_id=catalog_owner_id, catalog_type=catalog_type) or updated
    if callback.message:
        saved_text = t(lang, "custom_stock_saved").format(count=len(items))
        if warnings:
            saved_text = f"{saved_text}\nWarnings: {len(warnings)}"
        if fulfilled_preorders:
            saved_text = f"{saved_text}\nPreorders fulfilled: {len(fulfilled_preorders)}"
        await callback.message.answer(saved_text)
        await _render_node(
            callback,
            state,
            catalog_owner_id,
            refreshed["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:pinfo:"))
async def set_product_info_start(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    if not await _can_manage_builder(callback.from_user.id, callback.bot):
        return await callback.answer(t(lang, "reseller_only_command"), show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    endpoint = await get_node(node_id, reseller_id=catalog_owner_id)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        return await callback.answer(t(lang, "custom_endpoint_not_found"), show_alert=True)

    catalog_type = _catalog_type_from_node(endpoint)
    await state.update_data(
        product_info_endpoint_id=str(endpoint["_id"]),
        product_info_return_node_id=str(endpoint["_id"]),
        custom_mode="builder",
        custom_catalog_type=catalog_type,
        custom_financial_mode=_catalog_financial_mode(catalog_type),
    )
    await state.set_state(CustomBuilderStates.waiting_product_info)

    if callback.message:
        await callback.message.answer(t(lang, "custom_send_product_info_text"))
    await callback.answer()


@router.message(CustomBuilderStates.waiting_product_info)
async def set_product_info_submit(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not await _can_manage_builder(message.from_user.id, message.bot):
        await state.clear()
        return
    catalog_owner_id = await _builder_catalog_owner_id(message.from_user.id, message.bot, data)
    if not catalog_owner_id:
        await state.clear()
        return
    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    endpoint_id = data.get("product_info_endpoint_id")
    return_node_id = data.get("product_info_return_node_id")

    if _is_cancel_input(message.text):
        await state.clear()
        if return_node_id:
            return await _render_node(
                message,
                state,
                catalog_owner_id,
                return_node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        return

    raw = str(message.text or "").strip()
    text = "" if raw == "-" else raw
    updated = await update_endpoint_product_info(
        endpoint_id,
        catalog_owner_id,
        text,
        catalog_type=catalog_type,
    )
    await state.clear()
    if not updated:
        return await message.answer(t(await _user_lang(message.from_user.id), "custom_failed_save_product_info"))

    await message.answer(t(await _user_lang(message.from_user.id), "custom_product_info_saved"))
    return await _render_node(
        message,
        state,
        catalog_owner_id,
        updated["_id"],
        is_builder=True,
        catalog_type=catalog_type,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:del:"))
async def delete_node_cb(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    if not await _can_manage_builder_structure(callback.from_user.id, callback.bot):
        return await callback.answer(t(lang, "reseller_only_command"), show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=catalog_owner_id)
    if not node:
        return await callback.answer(t(lang, "node_not_found_plain"), show_alert=True)

    if bool(node.get("is_root")):
        return await callback.answer(t(lang, "custom_root_folder_cannot_be_deleted"), show_alert=True)

    if str(node.get("node_type") or "") == "folder":
        children = await list_children(catalog_owner_id, node["_id"], catalog_type=_catalog_type_from_node(node))
        if children:
            return await callback.answer(t(lang, "custom_folder_not_empty_cannot_delete"), show_alert=True)

    parent_id = node.get("parent_id")
    catalog_type = _catalog_type_from_node(node)
    modified = await deactivate_node(node_id, catalog_owner_id, catalog_type=catalog_type)
    await callback.answer(t(lang, "custom_deleted_items").format(count=modified))

    if callback.message:
        target_node_id = None
        if parent_id:
            parent_node = await get_node(parent_id, reseller_id=catalog_owner_id, catalog_type=catalog_type)
            if parent_node:
                target_node_id = parent_node["_id"]
        if target_node_id is None:
            root = await ensure_root_node(catalog_owner_id, catalog_type=catalog_type)
            target_node_id = root["_id"]
        await _render_node(
            callback,
            state,
            catalog_owner_id,
            target_node_id,
            is_builder=True,
            catalog_type=catalog_type,
        )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:move:"))
async def move_node_cb(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    if not await _can_manage_builder_structure(callback.from_user.id, callback.bot):
        return await callback.answer(t(lang, "reseller_only_command"), show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)

    parts = str(callback.data or "").split(":", 3)
    if len(parts) != 4:
        return await callback.answer(t(lang, "custom_invalid_move_request"), show_alert=True)
    _, _, direction, node_id = parts
    direction = str(direction or "").strip().lower()
    if direction not in {"up", "down", "left", "right"}:
        return await callback.answer(t(lang, "custom_invalid_move_direction"), show_alert=True)

    node = await get_node(node_id, reseller_id=catalog_owner_id)
    if not node:
        return await callback.answer(t(lang, "node_not_found_plain"), show_alert=True)
    if bool(node.get("is_root")):
        return await callback.answer(t(lang, "custom_root_folder_cannot_be_moved"), show_alert=True)

    catalog_type = _catalog_type_from_node(node)
    ok, reason = await move_node_in_parent(
        node_id=node["_id"],
        reseller_id=catalog_owner_id,
        direction=direction,
        catalog_type=catalog_type,
    )
    if not ok:
        if reason == "edge":
            return await callback.answer(t(lang, "custom_move_not_possible_direction"), show_alert=True)
        if reason == "root_not_movable":
            return await callback.answer(t(lang, "custom_root_folder_cannot_be_moved"), show_alert=True)
        return await callback.answer(t(lang, "custom_move_failed"), show_alert=True)

    parent_id = node.get("parent_id")
    if not parent_id:
        root = await ensure_root_node(catalog_owner_id, catalog_type=catalog_type)
        parent_id = root["_id"]
    await callback.answer(t(lang, "custom_moved_plain"))
    if callback.message:
        await _render_node(
            callback,
            state,
            catalog_owner_id,
            parent_id,
            is_builder=True,
            catalog_type=catalog_type,
        )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:noop:"))
async def move_noop_cb(callback: types.CallbackQuery):
    await callback.answer(t(await _user_lang(callback.from_user.id), "custom_move_not_available_direction"), show_alert=False)


@router.callback_query(lambda c: c.data == "cstm:cancel")
async def custom_panel_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer(t(await _user_lang(callback.from_user.id), "closed_plain"))
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        user = await get_user(callback.from_user.id)
        lang = str((user or {}).get("language") or "en")
        await callback.message.answer(
            t(lang, "main_menu"),
            reply_markup=await menu_for_current_bot(lang, (await callback.bot.get_me()).id),
        )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:layout:"))
async def open_layout_mode(callback: types.CallbackQuery, state: FSMContext):
    if not await _can_manage_builder_structure(callback.from_user.id, callback.bot):
        return await callback.answer(t(await _user_lang(callback.from_user.id), "reseller_only_command"), show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(await _user_lang(callback.from_user.id), "access_denied_plain"), show_alert=True)
    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=catalog_owner_id)
    if not node or str(node.get("node_type") or "") != "folder":
        return await callback.answer(t(await _user_lang(callback.from_user.id), "custom_folder_not_found"), show_alert=True)
    catalog_type = _catalog_type_from_node(node)
    await state.update_data(custom_layout_node_id=str(node["_id"]))
    await callback.answer()
    if callback.message:
        await _render_node(
            callback,
            state,
            catalog_owner_id,
            node["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:layoutdone:"))
async def close_layout_mode(callback: types.CallbackQuery, state: FSMContext):
    if not await _can_manage_builder_structure(callback.from_user.id, callback.bot):
        return await callback.answer(t(await _user_lang(callback.from_user.id), "reseller_only_command"), show_alert=True)
    state_data = await state.get_data()
    catalog_owner_id = await _builder_catalog_owner_id(callback.from_user.id, callback.bot, state_data)
    if not catalog_owner_id:
        return await callback.answer(t(await _user_lang(callback.from_user.id), "access_denied_plain"), show_alert=True)
    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=catalog_owner_id)
    if not node:
        await state.update_data(custom_layout_node_id=None)
        return await callback.answer(t(await _user_lang(callback.from_user.id), "node_not_found_plain"), show_alert=True)
    catalog_type = _catalog_type_from_node(node)
    await state.update_data(custom_layout_node_id=None)
    await callback.answer(t(await _user_lang(callback.from_user.id), "saved_plain"))
    if callback.message:
        await _render_node(
            callback,
            state,
            catalog_owner_id,
            node["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )


def _buy_qty_kb(
    *,
    lang: str,
    endpoint_id: str,
    min_qty: int,
    available_qty: int,
    back_node_id: str,
    preorder: bool = False,
    quantities: list[int] | None = None,
) -> InlineKeyboardMarkup:
    presets = list(quantities or [1, 5, 10])
    if preorder:
        options = [q for q in presets if q >= int(min_qty)]
        if not options:
            options = [int(min_qty)]
    else:
        options = [q for q in presets if q >= int(min_qty) and q <= int(available_qty)]
        if not options and int(min_qty) <= int(available_qty):
            options = [int(min_qty)]
    rows: list[list[InlineKeyboardButton]] = []
    if options:
        rows.append(
            [
                InlineKeyboardButton(text=str(q), callback_data=f"cstm:buyqty:{endpoint_id}:{q}")
                for q in options
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text=t(lang, "back"), callback_data=f"cstm:open:{back_node_id}"),
            InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data="cstm:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _service_supports_multi_qty(endpoint: dict | None, data: dict | None = None) -> bool:
    parts = [
        str((data or {}).get("buy_service_name") or "").strip().lower(),
        str((endpoint or {}).get("name") or "").strip().lower(),
    ]
    haystack = " ".join(part for part in parts if part)
    if not haystack:
        return False
    return any(token in haystack for token in ("email", "gmail", "icloud"))


def _allowed_buy_quantities(endpoint: dict | None, data: dict | None = None) -> list[int]:
    if _service_supports_multi_qty(endpoint, data):
        return [1, 5, 10]
    return [1]


def _buy_confirm_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "confirm_purchase"), callback_data="cstm:buyconfirm")],
            [
                InlineKeyboardButton(text=t(lang, "back"), callback_data="cstm:buyqtyback"),
                InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data="cstm:cancel"),
            ],
        ]
    )


def _purchase_complete_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_back_main"), callback_data="cstm:cancel")],
        ]
    )


def _stock_preview_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Save Stock", callback_data="cstm:stocksave")],
            [
                InlineKeyboardButton(text="✏️ Send Again", callback_data="cstm:stockretry"),
                InlineKeyboardButton(text=t(lang, "btn_cancel"), callback_data="cstm:stockcancel"),
            ],
        ]
    )


async def _ask_buy_qty(message: types.Message, endpoint: dict, data: dict) -> None:
    lang = await _user_lang(message.from_user.id)
    min_qty = int(data.get("buy_min_qty", 1))
    available_qty = int(endpoint.get("available_qty", 0))
    preorder = bool(data.get("buy_is_preorder"))
    allowed_quantities = _allowed_buy_quantities(endpoint, data)
    if preorder:
        options = [q for q in allowed_quantities if q >= int(min_qty)]
    else:
        options = [q for q in allowed_quantities if q >= int(min_qty) and q <= int(available_qty)]
    if not options:
        options = [1]
    await message.answer(
        "Choose preorder quantity" if preorder else t(lang, "choose_quantity_plain"),
        reply_markup=_buy_qty_kb(
            lang=lang,
            endpoint_id=str(endpoint["_id"]),
            min_qty=min_qty,
            available_qty=available_qty,
            back_node_id=str(data.get("buy_return_node_id") or endpoint.get("parent_id") or endpoint["_id"]),
            preorder=preorder,
            quantities=options,
        ),
    )


async def _show_buy_confirm(message: types.Message, state: FSMContext, endpoint: dict, qty: int) -> None:
    lang = await _user_lang(message.from_user.id)
    data = await state.get_data()
    service_name = str(data.get("buy_service_name") or endpoint.get("name") or t(lang, "product_plain"))
    unit_price = float(data.get("buy_unit_price") or endpoint.get("price", 0))
    total = unit_price * int(qty)
    available_qty = int(endpoint.get("available_qty", 0))
    product_info = str(endpoint.get("product_info_text") or "").strip()
    preorder = bool(data.get("buy_is_preorder"))

    await state.update_data(buy_pending_qty=int(qty))
    await state.set_state(CustomBuilderStates.waiting_buy_confirm)
    summary = (
        f"{t(lang, 'product_plain')}: {service_name}\n"
        f"{t(lang, 'requested_qty_plain')}: {int(qty)}\n"
        f"{t(lang, 'available_qty_plain')}: {'-' if preorder else available_qty}\n"
        f"{t(lang, 'price_label')}: {format_usd(total)}"
    )
    if product_info:
        summary = f"{summary}\n\n{product_info}"
    await message.answer(
        f"{summary}\n\n{'Confirm preorder?' if preorder else t(lang, 'confirm_purchase_question')}",
        reply_markup=_buy_confirm_kb(lang),
    )


async def _execute_buy(
    message: types.Message,
    state: FSMContext,
    user_id: int,
    *,
    result_message: types.Message | None = None,
) -> None:
    user = await get_user(user_id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()

    endpoint_id = data.get("buy_endpoint_id")
    catalog_owner_id = int(data.get("buy_catalog_owner_id") or data.get("buy_reseller_id") or 0)
    wallet_scope_id = int(data.get("buy_wallet_scope_id") or data.get("buy_reseller_id") or 0)
    catalog_type = str(data.get("buy_catalog_type") or data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    preorder_flow = bool(data.get("buy_is_preorder"))
    endpoint = await get_node(endpoint_id, reseller_id=catalog_owner_id, catalog_type=catalog_type)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        await state.clear()
        await message.answer(t(lang, "order_not_found"))
        return

    if int(endpoint.get("reseller_id") or 0) != catalog_owner_id:
        await state.clear()
        await message.answer(t(lang, "custom_service_routing_mismatch"))
        return
    if not preorder_flow and not _endpoint_ready_for_sale(endpoint):
        await state.clear()
        await message.answer(t(lang, "custom_endpoint_not_ready_for_sale"))
        return
    if preorder_flow and not await _can_use_preorder(endpoint, message.bot):
        await state.clear()
        await message.answer(t(lang, "custom_endpoint_not_ready_for_sale"))
        return

    qty = int(data.get("buy_pending_qty") or 0)
    min_qty = int(data.get("buy_min_qty", 1))
    if qty < min_qty:
        await state.set_state(CustomBuilderStates.waiting_buy_qty)
        await message.answer(t(lang, "custom_minimum_quantity_is").format(min_qty=min_qty))
        await _ask_buy_qty(message, endpoint, data)
        return

    claimed_items: list[str] = []
    delivery_type = str(endpoint.get("delivery_type") or "").strip().lower()
    if not preorder_flow and delivery_type == "inventory":
        claim = await claim_endpoint_inventory(endpoint["_id"], catalog_owner_id, qty, catalog_type=catalog_type)
        if not claim:
            await state.set_state(CustomBuilderStates.waiting_buy_qty)
            await message.answer(t(lang, "custom_not_enough_stock"))
            await _ask_buy_qty(message, endpoint, data)
            return
        claimed_items = list(claim.get("claimed_items") or [])
        remaining_qty = int(claim.get("remaining_qty") or 0)
    elif not preorder_flow:
        reserved = await reserve_endpoint_stock(endpoint["_id"], catalog_owner_id, qty, catalog_type=catalog_type)
        if not reserved:
            await state.set_state(CustomBuilderStates.waiting_buy_qty)
            await message.answer(t(lang, "custom_not_enough_stock"))
            await _ask_buy_qty(message, endpoint, data)
            return
        remaining_qty = int(reserved.get("available_qty") or 0)
    else:
        remaining_qty = int(endpoint.get("available_qty") or 0)
    if delivery_type == "inventory" and not claimed_items:
        if preorder_flow:
            claimed_items = []
        else:
            await state.set_state(CustomBuilderStates.waiting_buy_qty)
            await message.answer(t(lang, "custom_not_enough_stock"))
            await _ask_buy_qty(message, endpoint, data)
            return

    order_id = None
    purchased = False
    try:
        unit_price = float(data.get("buy_unit_price") or endpoint.get("price", 0))
        total = unit_price * qty
        financial_mode = str(data.get("buy_financial_mode") or _catalog_financial_mode(catalog_type))
        service_type = "core" if financial_mode == _FINANCIAL_CORE else "custom"

        order = await create_order_v3(
            user_id=user_id,
            reseller_id=wallet_scope_id,
            service_type=service_type,
            service_ref_id=str(endpoint["_id"]),
            retail_amount=total,
            wholesale_amount=0.0,
            reseller_profit_amount=total if financial_mode == _FINANCIAL_CUSTOM else 0.0,
            status="pending",
        )
        order_id = order["_id"]

        if financial_mode == _FINANCIAL_CORE:
            ok, reason = await FinancialManager.process_core_purchase(
                user_id,
                str(order_id),
                total,
                0.0,
                reseller_id=wallet_scope_id,
            )
        else:
            ok, reason = await FinancialManager.process_custom_purchase(
                user_id,
                str(order_id),
                total,
                reseller_id=wallet_scope_id,
            )
        if not ok:
            await update_order_status(order_id, "failed")
            await state.clear()
            await message.answer(t(lang, "custom_purchase_failed_reason").format(reason=reason))
            return

        await update_order_details(
            order_id,
            {
                "custom_service_name": data.get("buy_service_name") or endpoint.get("name"),
                "qty": qty,
                "unit_price": unit_price,
                "total_price": total,
                "catalog_type": catalog_type,
                "financial_mode": financial_mode,
                "status": "queued" if preorder_flow else "success",
                "custom_preorder": preorder_flow,
            },
        )
        if preorder_flow:
            preorder = await create_preorder_request(
                endpoint_id=endpoint["_id"],
                catalog_owner_id=catalog_owner_id,
                wallet_scope_id=wallet_scope_id,
                buyer_user_id=user_id,
                order_id=order_id,
                qty=qty,
                unit_price=unit_price,
                total_price=total,
                service_name=str(data.get("buy_service_name") or endpoint.get("name") or ""),
                catalog_type=catalog_type,
            )
            await update_order_details(order_id, {"custom_preorder_id": preorder["_id"]})
            await update_order_status(order_id, "queued")
            await _notify_owner_preorder_created(preorder=preorder, endpoint=endpoint, buyer_user=user)
        else:
            await update_order_status(order_id, "success")
        purchased = True
        if preorder_flow:
            queue_position = await get_pending_preorder_position(preorder["_id"])
            await state.clear()
            await message.answer(
                "Reservation created successfully\n"
                f"Service: {data.get('buy_service_name') or endpoint.get('name')}\n"
                f"Qty: {qty}\n"
                f"Total: {format_usd(total)}\n"
                f"Queue position: {queue_position}\n"
                "Delivery will be sent later by the admin."
            )
            return

        delivery_ok = False
        delivery_preview = _delivery_preview_text(
            endpoint=endpoint,
            qty=qty,
            lang=lang,
            stock_items=claimed_items,
        )
        try:
            if delivery_preview is not None and result_message is not None:
                delivery_ok = True
            else:
                delivery_ok = await _send_endpoint_delivery(
                    bot=message.bot,
                    user_id=user_id,
                    endpoint=endpoint,
                    qty=qty,
                    lang=lang,
                    stock_items=claimed_items,
                )
        except Exception as exc:
            logger.exception(
                "Digital delivery failed endpoint=%s user=%s err=%s",
                endpoint.get("_id"),
                user_id,
                exc,
            )

        await state.clear()
        summary_text = t(lang, "custom_purchase_success_summary").format(
            service=data.get("buy_service_name") or endpoint.get("name"),
            qty=qty,
            total=total,
            remaining_qty=remaining_qty,
            delivery=t(lang, "sent_plain") if delivery_ok else t(lang, "custom_delivery_not_configured_or_failed"),
        )
        if delivery_preview is not None and result_message is not None:
            try:
                await _safe_edit_text(
                    result_message,
                    f"{delivery_preview}\n\n{summary_text}",
                    reply_markup=_purchase_complete_kb(lang),
                )
            except Exception:
                await message.answer(f"{delivery_preview}\n\n{summary_text}", reply_markup=_purchase_complete_kb(lang))
        else:
            await message.answer(
                summary_text,
                reply_markup=_purchase_complete_kb(lang),
            )
    except Exception as exc:
        logger.exception("Custom service purchase flow failed: %s", exc)
        if order_id is not None:
            await update_order_status(order_id, "failed")
        await state.clear()
        await message.answer(t(lang, "custom_purchase_failed_unexpected"))
    finally:
        if not purchased and not preorder_flow:
            await release_endpoint_stock(
                endpoint["_id"],
                catalog_owner_id,
                qty,
                catalog_type=catalog_type,
                claimed_items=claimed_items,
            )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:buy:"))
async def start_buy_endpoint(callback: types.CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = (user or {}).get("language", "en")

    node_id = callback.data.split(":", 2)[2]
    endpoint = await get_node(node_id)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        return await callback.answer(t(lang, "invalid_order_info"), show_alert=True)
    preorder_flow = False
    if not _endpoint_ready_for_sale(endpoint):
        preorder_flow = await _can_use_preorder(endpoint, callback.bot)
    if not _endpoint_ready_for_sale(endpoint) and not preorder_flow:
        return await callback.answer(t(lang, "custom_endpoint_not_ready_for_sale"), show_alert=True)

    bot_id = (await callback.bot.get_me()).id
    if await is_main_bot(bot_id):
        wallet_scope_id = int(callback.from_user.id)
    else:
        user_reseller = await _resolve_user_reseller(callback.from_user.id, bot_id)
        if not user_reseller or int(user_reseller) != int(endpoint.get("reseller_id") or 0):
            return await callback.answer(t(lang, "access_denied_plain"), show_alert=True)
        wallet_scope_id = int(user_reseller)
    catalog_type = _catalog_type_from_node(endpoint)
    financial_mode = _catalog_financial_mode(catalog_type)
    service_name_default = "ID INFO" if catalog_type == _CATALOG_ID_INFO else t(lang, "custom_service_plain")
    await state.update_data(
        buy_endpoint_id=str(endpoint["_id"]),
        buy_reseller_id=int(endpoint["reseller_id"]),
        buy_catalog_owner_id=int(endpoint["reseller_id"]),
        buy_wallet_scope_id=int(wallet_scope_id),
        buy_service_name=str(endpoint.get("name") or service_name_default),
        buy_unit_price=float(endpoint.get("price", 0)),
        buy_min_qty=int(endpoint.get("min_qty", 1)),
        buy_return_node_id=str(endpoint.get("parent_id") or endpoint["_id"]),
        buy_catalog_type=catalog_type,
        buy_financial_mode=financial_mode,
        buy_is_preorder=preorder_flow,
        custom_mode="user",
        custom_catalog_type=catalog_type,
        custom_financial_mode=financial_mode,
    )
    await state.set_state(CustomBuilderStates.waiting_buy_qty)

    if callback.message:
        await _ask_buy_qty(callback.message, endpoint, await state.get_data())
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:buyqty:"))
async def choose_buy_qty(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    data = await state.get_data()
    endpoint_id_state = str(data.get("buy_endpoint_id") or "")
    parts = str(callback.data or "").split(":")
    if len(parts) != 4:
        return await callback.answer(t(lang, "custom_invalid_quantity"), show_alert=True)
    endpoint_id = str(parts[2])
    if endpoint_id_state and endpoint_id != endpoint_id_state:
        return await callback.answer(t(lang, "custom_session_mismatch_reopen"), show_alert=True)
    try:
        qty = int(parts[3])
    except Exception:
        return await callback.answer(t(lang, "custom_invalid_quantity"), show_alert=True)

    endpoint = await get_node(endpoint_id)
    if not endpoint:
        return await callback.answer(t(lang, "custom_service_unavailable"), show_alert=True)
    preorder_flow = bool(data.get("buy_is_preorder"))
    if not preorder_flow and not _endpoint_ready_for_sale(endpoint):
        return await callback.answer(t(lang, "custom_endpoint_not_ready_for_sale"), show_alert=True)
    allowed_quantities = _allowed_buy_quantities(endpoint, data)
    if qty not in allowed_quantities:
        return await callback.answer(t(lang, "custom_invalid_quantity"), show_alert=True)
    min_qty = int(data.get("buy_min_qty", 1))
    if qty < min_qty:
        return await callback.answer(t(lang, "custom_minimum_quantity_is").format(min_qty=min_qty), show_alert=True)
    if not preorder_flow and int(endpoint.get("available_qty", 0)) < qty:
        return await callback.answer(t(lang, "custom_not_enough_stock"), show_alert=True)

    if callback.message:
        await _show_buy_confirm(callback.message, state, endpoint, qty)
    await callback.answer()


@router.callback_query(lambda c: c.data == "cstm:buyqtyback")
async def back_to_buy_qty(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    data = await state.get_data()
    endpoint_id = data.get("buy_endpoint_id")
    if not endpoint_id:
        return await callback.answer(t(lang, "custom_no_active_purchase"), show_alert=True)
    endpoint = await get_node(endpoint_id)
    if not endpoint:
        return await callback.answer(t(lang, "custom_service_unavailable"), show_alert=True)
    preorder_flow = bool(data.get("buy_is_preorder"))
    if not preorder_flow and not _endpoint_ready_for_sale(endpoint):
        return await callback.answer(t(lang, "custom_endpoint_not_ready_for_sale"), show_alert=True)
    await state.set_state(CustomBuilderStates.waiting_buy_qty)
    if callback.message:
        await _ask_buy_qty(callback.message, endpoint, data)
    await callback.answer()


@router.callback_query(lambda c: c.data == "cstm:buyconfirm")
async def confirm_buy_endpoint(callback: types.CallbackQuery, state: FSMContext):
    lang = await _user_lang(callback.from_user.id)
    data = await state.get_data()
    qty = int(data.get("buy_pending_qty") or 0)
    if qty <= 0:
        return await callback.answer(t(lang, "custom_choose_quantity_first"), show_alert=True)
    if callback.message:
        await _execute_buy(callback.message, state, callback.from_user.id, result_message=callback.message)
    await callback.answer()


@router.message(CustomBuilderStates.waiting_buy_qty)
async def handle_buy_qty(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()

    if _is_cancel_input(message.text):
        reseller_id = int(data.get("buy_reseller_id") or 0)
        return_node_id = data.get("buy_return_node_id")
        catalog_type = str(data.get("buy_catalog_type") or data.get("custom_catalog_type") or _CATALOG_CUSTOM)
        await state.clear()
        if reseller_id > 0 and return_node_id:
            return await _render_node(
                message,
                state,
                reseller_id,
                return_node_id,
                is_builder=False,
                catalog_type=catalog_type,
            )
        return await message.answer(t(lang, "reseller_cancelled_plain"))

    endpoint_id = data.get("buy_endpoint_id")
    endpoint = await get_node(endpoint_id)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        await state.clear()
        return await message.answer(t(lang, "order_not_found"))
    preorder_flow = bool(data.get("buy_is_preorder"))
    if not preorder_flow and not _endpoint_ready_for_sale(endpoint):
        await state.clear()
        return await message.answer(t(lang, "custom_endpoint_not_ready_for_sale"))

    try:
        qty = int((message.text or "").strip())
    except Exception:
        return await message.answer(t(lang, "custom_invalid_quantity"))

    allowed_quantities = _allowed_buy_quantities(endpoint, data)
    if qty not in allowed_quantities:
        return await message.answer(t(lang, "custom_invalid_quantity"))
    min_qty = int(data.get("buy_min_qty", 1))
    if qty < min_qty:
        return await message.answer(t(lang, "custom_minimum_quantity_is").format(min_qty=min_qty))
    if not preorder_flow and int(endpoint.get("available_qty", 0)) < qty:
        return await message.answer(t(lang, "custom_not_enough_stock"))

    await _show_buy_confirm(message, state, endpoint, qty)


@router.message(CustomBuilderStates.waiting_buy_confirm)
async def handle_buy_confirm_text(message: types.Message, state: FSMContext):
    lang = await _user_lang(message.from_user.id)
    if _is_cancel_input(message.text):
        await state.clear()
        return await message.answer(t(lang, "reseller_cancelled_plain"))
    await message.answer(t(lang, "custom_press_confirm_purchase"))





