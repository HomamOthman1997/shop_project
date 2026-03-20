import logging
from decimal import Decimal
from typing import Any

from database.financial_ledger import (
    process_core_purchase as _process_core_purchase,
    refund_core_purchase as _refund_core_purchase,
    process_custom_purchase as _process_custom_purchase,
    refund_custom_purchase as _refund_custom_purchase,
)

logger = logging.getLogger("financial_manager")


class FinancialManager:
    @classmethod
    async def process_core_purchase(
        cls,
        user_id: int,
        order_id: Any,
        sale_price: float | int | Decimal,
        cost_price: float | int | Decimal,
        reseller_id: int | None = None,
    ):
        try:
            ok, code, _meta = await _process_core_purchase(
                user_id=user_id,
                order_id=order_id,
                sale_price=sale_price,
                cost_price=cost_price,
                actor_id=user_id,
                reseller_id=reseller_id,
            )
        except Exception as exc:
            logger.exception("process_core_purchase failed: %s", exc)
            return False, "FINANCIAL_ERROR"
        if ok:
            return True, "Success"
        return False, code

    @classmethod
    async def refund_core_purchase(
        cls,
        user_id: int,
        order_id: Any,
        sale_price: float | int | Decimal,
        cost_price: float | int | Decimal,
        reseller_id: int | None = None,
    ):
        try:
            ok, code, _meta = await _refund_core_purchase(
                user_id=user_id,
                order_id=order_id,
                sale_price=sale_price,
                cost_price=cost_price,
                actor_id=user_id,
                reseller_id=reseller_id,
            )
        except Exception as exc:
            logger.exception("refund_core_purchase failed: %s", exc)
            return False, "FINANCIAL_ERROR"
        if ok:
            return True, "Refund Success"
        return False, code

    @classmethod
    async def process_custom_purchase(cls, user_id: int, order_id: str, price: float, reseller_id: int | None = None):
        try:
            ok, code, _meta = await _process_custom_purchase(
                user_id=user_id,
                order_id=order_id,
                price=price,
                actor_id=user_id,
                reseller_id=reseller_id,
            )
        except Exception as exc:
            logger.exception("process_custom_purchase failed: %s", exc)
            return False, "FINANCIAL_ERROR"
        if ok:
            return True, "Success"
        return False, code

    @classmethod
    async def refund_custom_purchase(cls, user_id: int, order_id: str, price: float, reseller_id: int | None = None):
        try:
            ok, code, _meta = await _refund_custom_purchase(
                user_id=user_id,
                order_id=order_id,
                price=price,
                actor_id=user_id,
                reseller_id=reseller_id,
            )
        except Exception as exc:
            logger.exception("refund_custom_purchase failed: %s", exc)
            return False, "FINANCIAL_ERROR"
        if ok:
            return True, "Refund Success"
        return False, code
