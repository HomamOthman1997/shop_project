from __future__ import annotations

import logging

from aiogram import Bot, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove

from database.bots_repo import get_reseller_id_for_bot
from database.custom_services_repo import (
    claim_endpoint_inventory,
    create_endpoint,
    create_folder,
    deactivate_node,
    ensure_root_node,
    get_node,
    list_children,
    move_node_in_parent,
    rename_node,
    release_endpoint_stock,
    set_endpoint_inventory,
    update_node_display_text,
    update_endpoint,
    update_endpoint_product_info,
)
from database.financial_ledger import create_order_v3
from database.orders_repo import update_order_details, update_order_status
from database.user_repo import get_user, get_user_reseller_for_bot, set_user_reseller_for_bot
from keyboards.main_menu_kb import main_menu
from utils.financial_manager import FinancialManager
from utils.permissions import is_reseller
from utils.reseller_setup_guard import get_reseller_setup_status, render_reseller_setup_notice
from utils.translations import t

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
    return "ID INFO" if catalog_type == _CATALOG_ID_INFO else "Custom Services"


def _catalog_financial_mode(catalog_type: str) -> str:
    return _FINANCIAL_CORE if catalog_type == _CATALOG_ID_INFO else _FINANCIAL_CUSTOM


def _is_cancel_input(text: str | None) -> bool:
    return (text or "").strip().lower() in _CANCEL_INPUTS


async def _safe_edit_text(
    message: types.Message,
    text: str,
    *,
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


async def _is_current_bot_reseller(user_id: int, bot: Bot) -> bool:
    bot_id = (await bot.get_me()).id
    return await is_reseller(user_id, bot_id=bot_id)


async def _resolve_user_reseller(user_id: int, bot_id: int) -> int | None:
    reseller_id = await get_user_reseller_for_bot(user_id, bot_id)
    if reseller_id:
        return int(reseller_id)
    inferred = await get_reseller_id_for_bot(bot_id)
    if inferred:
        await set_user_reseller_for_bot(user_id, bot_id, int(inferred))
        return int(inferred)
    return None


class CustomBuilderStates(StatesGroup):
    waiting_name = State()
    waiting_price = State()
    waiting_stock = State()
    waiting_min_qty = State()
    waiting_rename = State()
    waiting_display_text = State()
    waiting_delivery_payload = State()
    waiting_product_info = State()
    waiting_buy_qty = State()
    waiting_buy_confirm = State()


async def _send_endpoint_delivery(
    *,
    bot: Bot,
    user_id: int,
    endpoint: dict,
    qty: int,
    stock_items: list[str] | None = None,
) -> bool:
    if stock_items:
        payload = "\n".join([str(item or "").strip() for item in stock_items if str(item or "").strip()])
        if not payload:
            return False
        await bot.send_message(
            chat_id=int(user_id),
            text=f"Digital Delivery\n\n{payload}\n\nQty: {int(qty)}",
        )
        return True

    delivery_type = str(endpoint.get("delivery_type") or "").strip().lower()
    if delivery_type == "text":
        text = str(endpoint.get("delivery_text") or "").strip()
        if not text:
            return False
        await bot.send_message(chat_id=int(user_id), text=f"Digital Delivery\n\n{text}\n\nQty: {int(qty)}")
        return True
    if delivery_type == "photo":
        file_id = str(endpoint.get("delivery_file_id") or "").strip()
        if not file_id:
            return False
        caption = str(endpoint.get("delivery_caption") or "").strip()
        if caption:
            caption = f"{caption}\n\nQty: {int(qty)}"
        else:
            caption = f"Qty: {int(qty)}"
        await bot.send_photo(chat_id=int(user_id), photo=file_id, caption=caption)
        return True
    if delivery_type == "document":
        file_id = str(endpoint.get("delivery_file_id") or "").strip()
        if not file_id:
            return False
        caption = str(endpoint.get("delivery_caption") or "").strip()
        if caption:
            caption = f"{caption}\n\nQty: {int(qty)}"
        else:
            caption = f"Qty: {int(qty)}"
        await bot.send_document(chat_id=int(user_id), document=file_id, caption=caption)
        return True
    return False


def _node_btn(node: dict) -> InlineKeyboardButton:
    name = str(node.get("name") or "Unnamed")
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
            rows.append([InlineKeyboardButton(text="Add Folder", callback_data=f"cstm:addf:{node_id}")])
        if not is_root:
            rows.append([InlineKeyboardButton(text="Add Endpoint", callback_data=f"cstm:adde:{node_id}")])
        rows.append([InlineKeyboardButton(text="Add Sibling Folder", callback_data=f"cstm:adds:{node_id}")])
        rows.append([InlineKeyboardButton(text="Add Sibling Endpoint", callback_data=f"cstm:addse:{node_id}")])
    else:
        rows.append([InlineKeyboardButton(text="Add Sibling Folder", callback_data=f"cstm:adds:{node_id}")])
        rows.append([InlineKeyboardButton(text="Add Sibling Endpoint", callback_data=f"cstm:addse:{node_id}")])
    rows.append([InlineKeyboardButton(text="Back", callback_data=f"cstm:open:{node_id}")])
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
                row_buttons.append(InlineKeyboardButton(text="▫️", callback_data=f"cstm:noop:slot{slot}"))
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
) -> None:
    node = await get_node(node_id, reseller_id=reseller_id, catalog_type=catalog_type)
    if not node:
        err = "Node not found."
        if isinstance(message_or_cb, types.CallbackQuery):
            await message_or_cb.answer(err, show_alert=True)
        else:
            await message_or_cb.answer(err)
        return

    normalized_catalog = _catalog_type_from_node(node)
    if _ID_INFO_ARCHIVED and normalized_catalog == _CATALOG_ID_INFO:
        user = await get_user(int(message_or_cb.from_user.id))
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
    catalog_title = _catalog_title(normalized_catalog)

    if node_type == "folder" and is_builder and layout_mode:
        kb_rows.extend(_children_grid_preview_rows(children))
        if children:
            kb_rows.append([InlineKeyboardButton(text="────────────", callback_data="cstm:noop:divider")])
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
        delivery_status = "Configured" if delivery_type in {"text", "photo", "document", "inventory"} else "Not Configured"
        has_product_info = bool(str(node.get("product_info_text") or "").strip())
        text = (
            f"{catalog_title} Endpoint\n\n"
            f"Name: {node.get('name')}\n"
            f"Price: {price:.2f}$\n"
            f"Available: {stock}\n"
            f"Minimum Qty: {min_q}\n"
            f"Delivery: {delivery_status}\n"
            f"Stock Items: {inventory_count}\n"
            f"Product Info: {'Set' if has_product_info else 'Not Set'}"
        )
        if is_builder:
            kb_rows.append(
                [
                    InlineKeyboardButton(text="Rename", callback_data=f"cstm:rename:{node['_id']}"),
                    InlineKeyboardButton(text="Edit", callback_data=f"cstm:edit:{node['_id']}"),
                ]
            )
            kb_rows.append([InlineKeyboardButton(text="Set Stock", callback_data=f"cstm:delivery:{node['_id']}")])
            kb_rows.append([InlineKeyboardButton(text="Product Info", callback_data=f"cstm:pinfo:{node['_id']}")])
            endpoint_move = await _move_controls_for_node(
                reseller_id=reseller_id,
                node=node,
                catalog_type=normalized_catalog,
            )
            if endpoint_move:
                kb_rows.append(endpoint_move)
            kb_rows.append([InlineKeyboardButton(text="Delete", callback_data=f"cstm:del:{node['_id']}")])
        else:
            kb_rows.append([InlineKeyboardButton(text="Buy", callback_data=f"cstm:buy:{node['_id']}")])

        back_cb = f"cstm:open:{parent_id}" if parent_id else "cstm:cancel"
        kb_rows.append([InlineKeyboardButton(text="Back", callback_data=back_cb)])

    else:
        name = str(node.get("name") or ("ID INFO" if normalized_catalog == _CATALOG_ID_INFO else "Services"))
        custom_display_text = str(node.get("display_text") or "").strip()
        if custom_display_text:
            text = custom_display_text
        elif children:
            text = f"{catalog_title}\n\n{name}\nItems: {len(children)}"
        else:
            text = f"{catalog_title}\n\n{name}\nNo items in this folder yet."

        if is_builder:
            if layout_mode:
                kb_rows.append([InlineKeyboardButton(text="Done", callback_data=f"cstm:layoutdone:{node['_id']}")])
            else:
                kb_rows.append([InlineKeyboardButton(text="Add", callback_data=f"cstm:add:{node['_id']}")])
                kb_rows.append(
                    [
                        InlineKeyboardButton(text="Rename", callback_data=f"cstm:rename:{node['_id']}"),
                        InlineKeyboardButton(text="Edit Text", callback_data=f"cstm:edittxt:{node['_id']}"),
                    ]
                )
                kb_rows.append([InlineKeyboardButton(text="Move Folder", callback_data=f"cstm:layout:{node['_id']}")])
                if not bool(node.get("is_root")):
                    folder_move = await _move_controls_for_node(
                        reseller_id=reseller_id,
                        node=node,
                        catalog_type=normalized_catalog,
                    )
                    if folder_move:
                        kb_rows.append(folder_move)
                    kb_rows.append([InlineKeyboardButton(text="Delete", callback_data=f"cstm:del:{node['_id']}")])
        back_cb = f"cstm:open:{parent_id}" if parent_id else "cstm:cancel"
        kb_rows.append([InlineKeyboardButton(text="Back", callback_data=back_cb)])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None

    if isinstance(message_or_cb, types.CallbackQuery):
        if message_or_cb.message:
            await _safe_edit_text(message_or_cb.message, text, reply_markup=kb)
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
    reseller_id = await _resolve_user_reseller(message.from_user.id, bot_id)
    if not reseller_id:
        return await message.answer(t(lang, "no_custom_services"))

    root = await ensure_root_node(reseller_id, catalog_type=_CATALOG_CUSTOM)
    children = await list_children(int(reseller_id), root["_id"], catalog_type=_CATALOG_CUSTOM)
    if not children:
        return await message.answer(t(lang, "no_custom_services"), reply_markup=ReplyKeyboardRemove())

    await message.answer(t(lang, "services_temp"), reply_markup=ReplyKeyboardRemove())
    await state.update_data(
        custom_bot_id=bot_id,
        custom_mode="user",
        custom_catalog_type=_CATALOG_CUSTOM,
        custom_financial_mode=_FINANCIAL_CUSTOM,
    )
    await _render_node(
        message,
        state,
        int(reseller_id),
        root["_id"],
        is_builder=False,
        catalog_type=_CATALOG_CUSTOM,
    )


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
        custom_financial_mode=_FINANCIAL_CORE,
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
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("Reseller only.")
    lang = (await get_user(message.from_user.id) or {}).get("language", "en")
    setup_status = await get_reseller_setup_status(message.from_user.id)
    if not bool(setup_status.get("ready")):
        return await message.answer(render_reseller_setup_notice(lang, setup_status))
    await state.clear()
    root = await ensure_root_node(message.from_user.id, catalog_type=_CATALOG_CUSTOM)
    await state.update_data(
        custom_mode="builder",
        custom_catalog_type=_CATALOG_CUSTOM,
        custom_financial_mode=_FINANCIAL_CUSTOM,
    )
    await _render_node(
        message,
        state,
        message.from_user.id,
        root["_id"],
        is_builder=True,
        catalog_type=_CATALOG_CUSTOM,
    )


@router.message(lambda m: (m.text or "").strip().lower() in {"/id_info_builder", "/idinfo_builder", "id info builder"})
async def open_id_info_builder(message: types.Message, state: FSMContext):
    if _ID_INFO_ARCHIVED:
        user = await get_user(message.from_user.id)
        lang = (user or {}).get("language", "en")
        await state.clear()
        return await message.answer(t(lang, "no_id_info_services"))
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        return await message.answer("Reseller only.")
    lang = (await get_user(message.from_user.id) or {}).get("language", "en")
    setup_status = await get_reseller_setup_status(message.from_user.id)
    if not bool(setup_status.get("ready")):
        return await message.answer(render_reseller_setup_notice(lang, setup_status))
    await state.clear()
    root = await ensure_root_node(message.from_user.id, catalog_type=_CATALOG_ID_INFO)
    await state.update_data(
        custom_mode="builder",
        custom_catalog_type=_CATALOG_ID_INFO,
        custom_financial_mode=_FINANCIAL_CORE,
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
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    lang = (await get_user(callback.from_user.id) or {}).get("language", "en")
    setup_status = await get_reseller_setup_status(callback.from_user.id)
    if not bool(setup_status.get("ready")):
        await callback.answer(t(lang, "reseller_setup_blocked_alert"), show_alert=True)
        if callback.message:
            await callback.message.answer(render_reseller_setup_notice(lang, setup_status))
        return
    await callback.answer()
    await state.clear()
    root = await ensure_root_node(callback.from_user.id, catalog_type=_CATALOG_CUSTOM)
    await state.update_data(
        custom_mode="builder",
        custom_catalog_type=_CATALOG_CUSTOM,
        custom_financial_mode=_FINANCIAL_CUSTOM,
    )
    if callback.message:
        await _render_node(
            callback,
            state,
            callback.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=_CATALOG_CUSTOM,
        )


@router.callback_query(lambda c: c.data == "rsmenu:id_info_services")
async def open_id_info_builder_from_menu(callback: types.CallbackQuery, state: FSMContext):
    if _ID_INFO_ARCHIVED:
        user = await get_user(callback.from_user.id)
        lang = (user or {}).get("language", "en")
        await state.clear()
        return await callback.answer(t(lang, "no_id_info_services"), show_alert=True)
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
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
        custom_financial_mode=_FINANCIAL_CORE,
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
    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id)
    if not node:
        return await callback.answer("Node not found", show_alert=True)

    node_catalog_type = _catalog_type_from_node(node)
    if _ID_INFO_ARCHIVED and node_catalog_type == _CATALOG_ID_INFO:
        user = await get_user(callback.from_user.id)
        lang = (user or {}).get("language", "en")
        await state.clear()
        return await callback.answer(t(lang, "no_id_info_services"), show_alert=True)

    data = await state.get_data()
    explicit_mode = data.get("custom_mode")
    is_owner_reseller = await _is_current_bot_reseller(callback.from_user.id, callback.bot)

    if explicit_mode == "builder":
        if not is_owner_reseller or int(node.get("reseller_id") or 0) != int(callback.from_user.id):
            return await callback.answer("Access denied", show_alert=True)
        is_builder = True
    elif explicit_mode == "user":
        bot_id = (await callback.message.bot.get_me()).id
        user_reseller = await _resolve_user_reseller(callback.from_user.id, bot_id)
        if not user_reseller or int(user_reseller) != int(node.get("reseller_id") or 0):
            return await callback.answer("Access denied", show_alert=True)
        is_builder = False
    else:
        # Fallback: if reseller opens own node, treat as builder; otherwise user mode checks.
        if is_owner_reseller and int(node.get("reseller_id") or 0) == int(callback.from_user.id):
            is_builder = True
        else:
            bot_id = (await callback.message.bot.get_me()).id
            user_reseller = await _resolve_user_reseller(callback.from_user.id, bot_id)
            if not user_reseller or int(user_reseller) != int(node.get("reseller_id") or 0):
                return await callback.answer("Access denied", show_alert=True)
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
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=callback.from_user.id)
    if not node:
        return await callback.answer("Node not found", show_alert=True)

    if callback.message:
        can_add_folder = True
        if str(node.get("node_type") or "") == "folder":
            children = await list_children(
                callback.from_user.id,
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
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    _, mode, anchor_id = callback.data.split(":", 2)
    anchor = await get_node(anchor_id, reseller_id=callback.from_user.id)
    if not anchor:
        return await callback.answer("Node not found", show_alert=True)

    if mode in {"addf", "adde"} and str(anchor.get("node_type")) != "folder":
        return await callback.answer("Cannot add inside an endpoint.", show_alert=True)
    if mode == "adde" and bool(anchor.get("is_root")):
        return await callback.answer("Main folder accepts subfolders only.", show_alert=True)
    if mode in {"adds", "addse"}:
        parent_id = anchor.get("parent_id")
        if not parent_id:
            return await callback.answer("This node has no parent.", show_alert=True)
        parent_node = await get_node(parent_id, reseller_id=callback.from_user.id)
        if not parent_node or str(parent_node.get("node_type") or "") != "folder":
            return await callback.answer("Parent folder not found.", show_alert=True)
        anchor = parent_node
        # Convert sibling modes to normal add modes under parent.
        mode = "addf" if mode == "adds" else "adde"

    if mode == "addf":
        children = await list_children(
            callback.from_user.id,
            anchor["_id"],
            catalog_type=_catalog_type_from_node(anchor),
        )
        folder_count = sum(1 for child in children if str(child.get("node_type") or "") == "folder")
        if folder_count >= _MAX_FOLDER_CHILDREN:
            return await callback.answer("Maximum is 9 folders (3x3).", show_alert=True)

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
            "Send new name:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Back", callback_data=f"cstm:stateback:{anchor_id}")]
                ]
            ),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:stateback:"))
async def builder_state_back(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=callback.from_user.id)
    if not node:
        await state.clear()
        return await callback.answer("Node not found", show_alert=True)

    catalog_type = _catalog_type_from_node(node)
    await state.clear()
    await callback.answer()
    if callback.message:
        await _render_node(
            callback,
            state,
            callback.from_user.id,
            node["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )


@router.message(CustomBuilderStates.waiting_name)
async def add_entry_name(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return

    if _is_cancel_input(message.text):
        catalog_type = str((await state.get_data()).get("custom_catalog_type") or _CATALOG_CUSTOM)
        await state.clear()
        root = await ensure_root_node(message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    name = (message.text or "").strip()
    if not name:
        return await message.answer("Name cannot be empty.")

    data = await state.get_data()
    add_mode = str(data.get("builder_add_mode") or "")
    anchor = await get_node(data.get("builder_anchor_id"), reseller_id=message.from_user.id)
    if not anchor:
        await state.clear()
        return await message.answer("Anchor not found.")
    catalog_type = _catalog_type_from_node(anchor)

    return_node_id = data.get("builder_return_node_id") or str(anchor["_id"])

    if add_mode == "addf":
        children = await list_children(
            message.from_user.id,
            anchor["_id"],
            catalog_type=catalog_type,
        )
        folder_count = sum(1 for child in children if str(child.get("node_type") or "") == "folder")
        if folder_count >= _MAX_FOLDER_CHILDREN:
            await state.clear()
            await message.answer("Maximum is 9 folders (3x3).")
            return await _render_node(
                message,
                state,
                message.from_user.id,
                return_node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        await create_folder(message.from_user.id, anchor["_id"], name, catalog_type=catalog_type)
        await state.clear()
        await message.answer("Folder created.")
        return await _render_node(
            message,
            state,
            message.from_user.id,
            return_node_id,
            is_builder=True,
            catalog_type=catalog_type,
        )

    if add_mode not in {"adde", "addf"}:
        await state.clear()
        return await message.answer("Unsupported add mode.")

    await state.update_data(builder_name=name)
    await state.set_state(CustomBuilderStates.waiting_price)
    await message.answer("Send endpoint price (example: 2.5), or /cancel")


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:rename:"))
async def rename_node_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=callback.from_user.id)
    if not node:
        return await callback.answer("Node not found", show_alert=True)

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
            "Send new name now.\n"
            f"Current: {str(node.get('name') or '-')}\n"
            "Or /cancel"
        )
    await callback.answer()


@router.message(CustomBuilderStates.waiting_rename)
async def rename_node_submit(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("custom_mode") == "builder" and not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return

    if _is_cancel_input(message.text):
        catalog_type = str((await state.get_data()).get("custom_catalog_type") or _CATALOG_CUSTOM)
        node_id = (await state.get_data()).get("rename_return_node_id")
        await state.clear()
        if node_id:
            return await _render_node(
                message,
                state,
                message.from_user.id,
                node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        root = await ensure_root_node(message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    new_name = (message.text or "").strip()
    if not new_name:
        return await message.answer("Name cannot be empty.")

    node_id = data.get("rename_node_id")
    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    updated = await rename_node(node_id, message.from_user.id, new_name, catalog_type=catalog_type)
    await state.clear()
    if not updated:
        return await message.answer("Node not found.")

    await message.answer("Name updated.")
    return await _render_node(
        message,
        state,
        message.from_user.id,
        updated["_id"],
        is_builder=True,
        catalog_type=catalog_type,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:edittxt:"))
async def edit_display_text_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=callback.from_user.id)
    if not node:
        return await callback.answer("Node not found", show_alert=True)
    if str(node.get("node_type") or "") != "folder":
        return await callback.answer("Text can be edited for folders only.", show_alert=True)

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
            "Send folder display text now.\n"
            f"Current: {current_text}\n"
            "Send 'clear' to reset default text.\n"
            "Or /cancel"
        )
    await callback.answer()


@router.message(CustomBuilderStates.waiting_display_text)
async def edit_display_text_submit(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return

    if _is_cancel_input(message.text):
        data = await state.get_data()
        catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
        node_id = data.get("edit_text_return_node_id")
        await state.clear()
        if node_id:
            return await _render_node(
                message,
                state,
                message.from_user.id,
                node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        root = await ensure_root_node(message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    data = await state.get_data()
    node_id = data.get("edit_text_node_id")
    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    raw_text = (message.text or "").strip()
    if raw_text.lower() in {"clear", "/clear", "مسح"}:
        raw_text = ""
    elif len(raw_text) > 500:
        return await message.answer("Text is too long. Max 500 characters.")

    updated = await update_node_display_text(
        node_id=node_id,
        reseller_id=message.from_user.id,
        display_text=raw_text,
        catalog_type=catalog_type,
    )
    await state.clear()
    if not updated:
        return await message.answer("Node not found.")

    await message.answer("Display text updated.")
    return await _render_node(
        message,
        state,
        message.from_user.id,
        updated["_id"],
        is_builder=True,
        catalog_type=catalog_type,
    )


@router.message(CustomBuilderStates.waiting_price)
async def add_endpoint_price(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("custom_mode") == "builder" and not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return

    if _is_cancel_input(message.text):
        catalog_type = str((await state.get_data()).get("custom_catalog_type") or _CATALOG_CUSTOM)
        await state.clear()
        root = await ensure_root_node(message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    try:
        price = float((message.text or "").strip())
    except Exception:
        return await message.answer("Invalid price.")

    if price <= 0:
        return await message.answer("Price must be greater than zero.")

    if data.get("edit_endpoint_id"):
        await state.update_data(edit_price=price)
    else:
        await state.update_data(builder_price=price)

    await state.set_state(CustomBuilderStates.waiting_stock)
    await message.answer("Send available quantity, or /cancel")


@router.message(CustomBuilderStates.waiting_stock)
async def add_endpoint_stock(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("custom_mode") == "builder" and not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return

    if _is_cancel_input(message.text):
        catalog_type = str((await state.get_data()).get("custom_catalog_type") or _CATALOG_CUSTOM)
        await state.clear()
        root = await ensure_root_node(message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    try:
        stock = int((message.text or "").strip())
    except Exception:
        return await message.answer("Invalid quantity.")

    if stock < 0:
        return await message.answer("Quantity must be zero or greater.")

    if data.get("edit_endpoint_id"):
        await state.update_data(edit_stock=stock)
    else:
        await state.update_data(builder_stock=stock)

    await state.set_state(CustomBuilderStates.waiting_min_qty)
    await message.answer("Send minimum required quantity, or /cancel")


@router.message(CustomBuilderStates.waiting_min_qty)
async def add_endpoint_min(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("custom_mode") == "builder" and not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return

    if _is_cancel_input(message.text):
        catalog_type = str((await state.get_data()).get("custom_catalog_type") or _CATALOG_CUSTOM)
        await state.clear()
        root = await ensure_root_node(message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    try:
        min_qty = int((message.text or "").strip())
    except Exception:
        return await message.answer("Invalid minimum quantity.")

    if min_qty < 1:
        return await message.answer("Minimum quantity must be at least 1.")

    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    if data.get("edit_endpoint_id"):
        updated = await update_endpoint(
            data.get("edit_endpoint_id"),
            message.from_user.id,
            price=float(data.get("edit_price")),
            available_qty=int(data.get("edit_stock")),
            min_qty=min_qty,
            catalog_type=catalog_type,
        )
        return_node_id = data.get("edit_return_node_id")
        await state.clear()
        if not updated:
            return await message.answer("Endpoint not found.")

        await message.answer("Endpoint updated.")
        if return_node_id:
            return await _render_node(
                message,
                state,
                message.from_user.id,
                return_node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        root = await ensure_root_node(message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    anchor = await get_node(data.get("builder_anchor_id"), reseller_id=message.from_user.id)
    if not anchor:
        await state.clear()
        return await message.answer("Anchor not found.")
    if bool(anchor.get("is_root")):
        await state.clear()
        return await message.answer("Main folder accepts subfolders only.")

    parent_id = anchor["_id"] if data.get("builder_add_mode") == "adde" else anchor.get("parent_id")
    await create_endpoint(
        reseller_id=message.from_user.id,
        parent_id=parent_id,
        name=str(data.get("builder_name") or "").strip(),
        price=float(data.get("builder_price")),
        available_qty=int(data.get("builder_stock")),
        min_qty=min_qty,
        catalog_type=catalog_type,
    )

    return_node_id = data.get("builder_return_node_id") or str(anchor["_id"])
    await state.clear()
    await message.answer("Endpoint created successfully.")
    await _render_node(
        message,
        state,
        message.from_user.id,
        return_node_id,
        is_builder=True,
        catalog_type=catalog_type,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:edit:"))
async def edit_endpoint_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    endpoint = await get_node(node_id, reseller_id=callback.from_user.id)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        return await callback.answer("Endpoint not found", show_alert=True)

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
            "Send new price now.\n"
            f"Current: {float(endpoint.get('price', 0)):.2f}$\n"
            "Or /cancel"
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:delivery:"))
async def set_delivery_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    endpoint = await get_node(node_id, reseller_id=callback.from_user.id)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        return await callback.answer("Endpoint not found", show_alert=True)

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
        await callback.message.answer(
            "Send stock lines now (one item per line).\n"
            "Example:\n"
            "email1@gmail.com:pass1\n"
            "email2@gmail.com:pass2\n\n"
            "Use Back or /cancel to abort."
        )
    await callback.answer()


@router.message(CustomBuilderStates.waiting_delivery_payload)
async def set_delivery_submit(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return

    data = await state.get_data()
    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    endpoint_id = data.get("delivery_endpoint_id")
    return_node_id = data.get("delivery_return_node_id")

    if _is_cancel_input(message.text):
        await state.clear()
        if return_node_id:
            return await _render_node(
                message,
                state,
                message.from_user.id,
                return_node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        root = await ensure_root_node(message.from_user.id, catalog_type=catalog_type)
        return await _render_node(
            message,
            state,
            message.from_user.id,
            root["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )

    text = str(message.text or "").strip()
    if not text:
        return await message.answer("Send stock lines as plain text, one line per item, or /cancel.")
    items = [line.strip() for line in text.splitlines() if line.strip()]
    if not items:
        return await message.answer("No valid stock lines found. Try again.")
    updated = await set_endpoint_inventory(
        endpoint_id,
        message.from_user.id,
        inventory_items=items,
        catalog_type=catalog_type,
    )

    await state.clear()
    if not updated:
        return await message.answer("Failed to save delivery payload.")

    await message.answer(f"Stock saved: {len(items)} item(s).")
    return await _render_node(
        message,
        state,
        message.from_user.id,
        updated["_id"],
        is_builder=True,
        catalog_type=catalog_type,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:pinfo:"))
async def set_product_info_start(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    endpoint = await get_node(node_id, reseller_id=callback.from_user.id)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        return await callback.answer("Endpoint not found", show_alert=True)

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
        await callback.message.answer(
            "Send product info text shown before confirmation.\n"
            "Send '-' to clear.\n"
            "Use Back or /cancel to abort."
        )
    await callback.answer()


@router.message(CustomBuilderStates.waiting_product_info)
async def set_product_info_submit(message: types.Message, state: FSMContext):
    if not await _is_current_bot_reseller(message.from_user.id, message.bot):
        await state.clear()
        return

    data = await state.get_data()
    catalog_type = str(data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    endpoint_id = data.get("product_info_endpoint_id")
    return_node_id = data.get("product_info_return_node_id")

    if _is_cancel_input(message.text):
        await state.clear()
        if return_node_id:
            return await _render_node(
                message,
                state,
                message.from_user.id,
                return_node_id,
                is_builder=True,
                catalog_type=catalog_type,
            )
        return

    raw = str(message.text or "").strip()
    text = "" if raw == "-" else raw
    updated = await update_endpoint_product_info(
        endpoint_id,
        message.from_user.id,
        text,
        catalog_type=catalog_type,
    )
    await state.clear()
    if not updated:
        return await message.answer("Failed to save product info.")

    await message.answer("Product info saved.")
    return await _render_node(
        message,
        state,
        message.from_user.id,
        updated["_id"],
        is_builder=True,
        catalog_type=catalog_type,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:del:"))
async def delete_node_cb(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=callback.from_user.id)
    if not node:
        return await callback.answer("Node not found", show_alert=True)

    if bool(node.get("is_root")):
        return await callback.answer("Root folder cannot be deleted.", show_alert=True)

    if str(node.get("node_type") or "") == "folder":
        children = await list_children(callback.from_user.id, node["_id"], catalog_type=_catalog_type_from_node(node))
        if children:
            return await callback.answer("Folder is not empty and cannot be deleted.", show_alert=True)

    parent_id = node.get("parent_id")
    catalog_type = _catalog_type_from_node(node)
    modified = await deactivate_node(node_id, callback.from_user.id, catalog_type=catalog_type)
    await callback.answer(f"Deleted {modified} item(s).")

    if callback.message:
        target_node_id = None
        if parent_id:
            parent_node = await get_node(parent_id, reseller_id=callback.from_user.id, catalog_type=catalog_type)
            if parent_node:
                target_node_id = parent_node["_id"]
        if target_node_id is None:
            root = await ensure_root_node(callback.from_user.id, catalog_type=catalog_type)
            target_node_id = root["_id"]
        await _render_node(
            callback,
            state,
            callback.from_user.id,
            target_node_id,
            is_builder=True,
            catalog_type=catalog_type,
        )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:move:"))
async def move_node_cb(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)

    parts = str(callback.data or "").split(":", 3)
    if len(parts) != 4:
        return await callback.answer("Invalid move request.", show_alert=True)
    _, _, direction, node_id = parts
    direction = str(direction or "").strip().lower()
    if direction not in {"up", "down", "left", "right"}:
        return await callback.answer("Invalid move direction.", show_alert=True)

    node = await get_node(node_id, reseller_id=callback.from_user.id)
    if not node:
        return await callback.answer("Node not found", show_alert=True)
    if bool(node.get("is_root")):
        return await callback.answer("Root folder cannot be moved.", show_alert=True)

    catalog_type = _catalog_type_from_node(node)
    ok, reason = await move_node_in_parent(
        node_id=node["_id"],
        reseller_id=callback.from_user.id,
        direction=direction,
        catalog_type=catalog_type,
    )
    if not ok:
        if reason == "edge":
            return await callback.answer("Move not possible in this direction.", show_alert=True)
        if reason == "root_not_movable":
            return await callback.answer("Root folder cannot be moved.", show_alert=True)
        return await callback.answer("Move failed.", show_alert=True)

    parent_id = node.get("parent_id")
    if not parent_id:
        root = await ensure_root_node(callback.from_user.id, catalog_type=catalog_type)
        parent_id = root["_id"]
    await callback.answer("Moved.")
    if callback.message:
        await _render_node(
            callback,
            state,
            callback.from_user.id,
            parent_id,
            is_builder=True,
            catalog_type=catalog_type,
        )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:noop:"))
async def move_noop_cb(callback: types.CallbackQuery):
    await callback.answer("غير متاح بهالاتجاه", show_alert=False)


@router.callback_query(lambda c: c.data == "cstm:cancel")
async def custom_panel_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Closed")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        user = await get_user(callback.from_user.id)
        lang = str((user or {}).get("language") or "en")
        await callback.message.answer("Main Menu", reply_markup=main_menu(lang))


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:layout:"))
async def open_layout_mode(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=callback.from_user.id)
    if not node or str(node.get("node_type") or "") != "folder":
        return await callback.answer("Folder not found", show_alert=True)
    catalog_type = _catalog_type_from_node(node)
    await state.update_data(custom_layout_node_id=str(node["_id"]))
    await callback.answer()
    if callback.message:
        await _render_node(
            callback,
            state,
            callback.from_user.id,
            node["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )


@router.callback_query(lambda c: c.data and c.data.startswith("cstm:layoutdone:"))
async def close_layout_mode(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_current_bot_reseller(callback.from_user.id, callback.bot):
        return await callback.answer("Reseller only", show_alert=True)
    node_id = callback.data.split(":", 2)[2]
    node = await get_node(node_id, reseller_id=callback.from_user.id)
    if not node:
        await state.update_data(custom_layout_node_id=None)
        return await callback.answer("Node not found", show_alert=True)
    catalog_type = _catalog_type_from_node(node)
    await state.update_data(custom_layout_node_id=None)
    await callback.answer("Saved.")
    if callback.message:
        await _render_node(
            callback,
            state,
            callback.from_user.id,
            node["_id"],
            is_builder=True,
            catalog_type=catalog_type,
        )


def _buy_qty_kb(*, endpoint_id: str, min_qty: int, available_qty: int, back_node_id: str) -> InlineKeyboardMarkup:
    presets = [1, 5, 10]
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
            InlineKeyboardButton(text="Back", callback_data=f"cstm:open:{back_node_id}"),
            InlineKeyboardButton(text="Cancel", callback_data="cstm:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _buy_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Confirm Purchase", callback_data="cstm:buyconfirm")],
            [
                InlineKeyboardButton(text="Back", callback_data="cstm:buyqtyback"),
                InlineKeyboardButton(text="Cancel", callback_data="cstm:cancel"),
            ],
        ]
    )


async def _ask_buy_qty(message: types.Message, endpoint: dict, data: dict) -> None:
    min_qty = int(data.get("buy_min_qty", 1))
    available_qty = int(endpoint.get("available_qty", 0))
    await message.answer(
        "Choose quantity",
        reply_markup=_buy_qty_kb(
            endpoint_id=str(endpoint["_id"]),
            min_qty=min_qty,
            available_qty=available_qty,
            back_node_id=str(data.get("buy_return_node_id") or endpoint.get("parent_id") or endpoint["_id"]),
        ),
    )


async def _show_buy_confirm(message: types.Message, state: FSMContext, endpoint: dict, qty: int) -> None:
    data = await state.get_data()
    service_name = str(data.get("buy_service_name") or endpoint.get("name") or "Product")
    unit_price = float(data.get("buy_unit_price") or endpoint.get("price", 0))
    total = unit_price * int(qty)
    available_qty = int(endpoint.get("available_qty", 0))
    product_info = str(endpoint.get("product_info_text") or "").strip()

    await state.update_data(buy_pending_qty=int(qty))
    await state.set_state(CustomBuilderStates.waiting_buy_confirm)
    await message.answer(
        f"Product: {service_name}\n"
        f"Requested Qty: {int(qty)}\n"
        f"Available Qty: {available_qty}\n"
        f"Price: {total:.2f}$"
    )
    if product_info:
        await message.answer(product_info)
    await message.answer("Confirm purchase?", reply_markup=_buy_confirm_kb())


async def _execute_buy(message: types.Message, state: FSMContext, user_id: int) -> None:
    user = await get_user(user_id)
    lang = (user or {}).get("language", "en")
    data = await state.get_data()

    endpoint_id = data.get("buy_endpoint_id")
    reseller_id = int(data.get("buy_reseller_id") or 0)
    catalog_type = str(data.get("buy_catalog_type") or data.get("custom_catalog_type") or _CATALOG_CUSTOM)
    endpoint = await get_node(endpoint_id, catalog_type=catalog_type)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        await state.clear()
        await message.answer(t(lang, "order_not_found"))
        return

    if int(endpoint.get("reseller_id") or 0) != reseller_id:
        await state.clear()
        await message.answer("Service routing mismatch. Please reopen services.")
        return

    qty = int(data.get("buy_pending_qty") or 0)
    min_qty = int(data.get("buy_min_qty", 1))
    if qty < min_qty:
        await state.set_state(CustomBuilderStates.waiting_buy_qty)
        await message.answer(f"Minimum quantity is {min_qty}.")
        await _ask_buy_qty(message, endpoint, data)
        return

    claim = await claim_endpoint_inventory(endpoint["_id"], reseller_id, qty, catalog_type=catalog_type)
    if not claim:
        await state.set_state(CustomBuilderStates.waiting_buy_qty)
        await message.answer("Not enough stock.")
        await _ask_buy_qty(message, endpoint, data)
        return
    claimed_items = list(claim.get("claimed_items") or [])
    remaining_qty = int(claim.get("remaining_qty") or 0)

    order_id = None
    purchased = False
    try:
        unit_price = float(data.get("buy_unit_price") or endpoint.get("price", 0))
        total = unit_price * qty
        financial_mode = str(data.get("buy_financial_mode") or _catalog_financial_mode(catalog_type))
        service_type = "core" if financial_mode == _FINANCIAL_CORE else "custom"

        order = await create_order_v3(
            user_id=user_id,
            reseller_id=reseller_id,
            service_type=service_type,
            service_ref_id=str(endpoint["_id"]),
            retail_amount=total,
            wholesale_amount=0.0,
            owner_fee_amount=0.0,
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
                reseller_id=reseller_id,
            )
        else:
            ok, reason = await FinancialManager.process_custom_purchase(
                user_id,
                str(order_id),
                total,
                reseller_id=reseller_id,
            )
        if not ok:
            await update_order_status(order_id, "failed")
            await state.clear()
            await message.answer(f"Purchase failed: {reason}")
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
                "status": "success",
            },
        )
        await update_order_status(order_id, "success")
        purchased = True
        delivery_ok = False
        try:
            delivery_ok = await _send_endpoint_delivery(
                bot=message.bot,
                user_id=user_id,
                endpoint=endpoint,
                qty=qty,
                stock_items=claimed_items,
            )
        except Exception as exc:
            logger.exception(
                "Digital delivery failed endpoint=%s user=%s err=%s",
                endpoint.get("_id"),
                user_id,
                exc,
            )

        return_node_id = data.get("buy_return_node_id")
        await state.clear()
        await message.answer(
            "Purchased successfully\n"
            f"Service: {data.get('buy_service_name') or endpoint.get('name')}\n"
            f"Qty: {qty}\n"
            f"Total: {total:.2f}$\n"
            f"Remaining stock: {remaining_qty}\n"
            f"Delivery: {'Sent' if delivery_ok else 'Not configured or failed'}"
        )
        if return_node_id:
            await _render_node(
                message,
                state,
                reseller_id,
                return_node_id,
                is_builder=False,
                catalog_type=catalog_type,
            )
    except Exception as exc:
        logger.exception("Custom service purchase flow failed: %s", exc)
        if order_id is not None:
            await update_order_status(order_id, "failed")
        await state.clear()
        await message.answer("Purchase failed: unexpected error. Please try again.")
    finally:
        if not purchased:
            await release_endpoint_stock(
                endpoint["_id"],
                reseller_id,
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

    bot_id = (await callback.message.bot.get_me()).id
    user_reseller = await _resolve_user_reseller(callback.from_user.id, bot_id)
    if not user_reseller or int(user_reseller) != int(endpoint.get("reseller_id") or 0):
        return await callback.answer("Access denied", show_alert=True)

    catalog_type = _catalog_type_from_node(endpoint)
    financial_mode = _catalog_financial_mode(catalog_type)
    service_name_default = "ID INFO" if catalog_type == _CATALOG_ID_INFO else "Custom Service"
    await state.update_data(
        buy_endpoint_id=str(endpoint["_id"]),
        buy_reseller_id=int(endpoint["reseller_id"]),
        buy_service_name=str(endpoint.get("name") or service_name_default),
        buy_unit_price=float(endpoint.get("price", 0)),
        buy_min_qty=int(endpoint.get("min_qty", 1)),
        buy_return_node_id=str(endpoint.get("parent_id") or endpoint["_id"]),
        buy_catalog_type=catalog_type,
        buy_financial_mode=financial_mode,
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
    data = await state.get_data()
    endpoint_id_state = str(data.get("buy_endpoint_id") or "")
    parts = str(callback.data or "").split(":")
    if len(parts) != 4:
        return await callback.answer("Invalid quantity.", show_alert=True)
    endpoint_id = str(parts[2])
    if endpoint_id_state and endpoint_id != endpoint_id_state:
        return await callback.answer("Session mismatch. Reopen service.", show_alert=True)
    try:
        qty = int(parts[3])
    except Exception:
        return await callback.answer("Invalid quantity.", show_alert=True)

    endpoint = await get_node(endpoint_id)
    if not endpoint:
        return await callback.answer("Service unavailable.", show_alert=True)
    min_qty = int(data.get("buy_min_qty", 1))
    if qty < min_qty:
        return await callback.answer(f"Minimum quantity is {min_qty}.", show_alert=True)
    if int(endpoint.get("available_qty", 0)) < qty:
        return await callback.answer("Not enough stock.", show_alert=True)

    if callback.message:
        await _show_buy_confirm(callback.message, state, endpoint, qty)
    await callback.answer()


@router.callback_query(lambda c: c.data == "cstm:buyqtyback")
async def back_to_buy_qty(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    endpoint_id = data.get("buy_endpoint_id")
    if not endpoint_id:
        return await callback.answer("No active purchase.", show_alert=True)
    endpoint = await get_node(endpoint_id)
    if not endpoint:
        return await callback.answer("Service unavailable.", show_alert=True)
    await state.set_state(CustomBuilderStates.waiting_buy_qty)
    if callback.message:
        await _ask_buy_qty(callback.message, endpoint, data)
    await callback.answer()


@router.callback_query(lambda c: c.data == "cstm:buyconfirm")
async def confirm_buy_endpoint(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    qty = int(data.get("buy_pending_qty") or 0)
    if qty <= 0:
        return await callback.answer("Choose quantity first.", show_alert=True)
    if callback.message:
        await _execute_buy(callback.message, state, callback.from_user.id)
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
        return await message.answer("Canceled.")

    endpoint_id = data.get("buy_endpoint_id")
    endpoint = await get_node(endpoint_id)
    if not endpoint or endpoint.get("node_type") != "endpoint":
        await state.clear()
        return await message.answer(t(lang, "order_not_found"))

    try:
        qty = int((message.text or "").strip())
    except Exception:
        return await message.answer("Invalid quantity.")

    min_qty = int(data.get("buy_min_qty", 1))
    if qty < min_qty:
        return await message.answer(f"Minimum quantity is {min_qty}.")
    if int(endpoint.get("available_qty", 0)) < qty:
        return await message.answer("Not enough stock.")

    await _show_buy_confirm(message, state, endpoint, qty)


@router.message(CustomBuilderStates.waiting_buy_confirm)
async def handle_buy_confirm_text(message: types.Message, state: FSMContext):
    if _is_cancel_input(message.text):
        await state.clear()
        return await message.answer("Canceled.")
    await message.answer("Press Confirm Purchase button.")





