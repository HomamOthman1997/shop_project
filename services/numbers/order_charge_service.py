from __future__ import annotations

from typing import Any

from database.orders_repo import update_order_status
from services.numbers.shared.events import _log_number_event_from_order
from utils.core_service_guard import finance_error_public_text
from utils.financial_manager import FinancialManager


class OrderChargeError(Exception):
    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


async def charge_order_or_raise(
    *,
    order: dict[str, Any],
    order_id: Any,
    user_id: int,
    reseller_id: int,
    final_price: float,
    cost_price: float,
    lang: str,
    number_mode: str,
    source: str,
) -> None:
    ok, message = await FinancialManager.process_core_purchase(
        user_id=int(user_id),
        order_id=order_id,
        sale_price=final_price,
        cost_price=cost_price,
        reseller_id=int(reseller_id),
    )
    if ok:
        return
    await update_order_status(order_id, "failed")
    await _log_number_event_from_order(
        order,
        "wallet_charge_failed",
        payload={"message": str(message), "source": source},
        status_after="failed",
        number_mode=number_mode,
    )
    raise OrderChargeError(str(message), finance_error_public_text(lang, str(message)))
