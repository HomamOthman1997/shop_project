from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from database.orders_repo import update_order_details, update_order_status
from services.numbers.order_charge_service import OrderChargeError, charge_order_or_raise
from services.numbers.order_purchase_service import ProviderProvisioningError
from services.numbers.shared.temp_order import _utc_now
from utils.financial_manager import FinancialManager


class UnexpectedProvisioningError(Exception):
    def __init__(self, public_message: str) -> None:
        super().__init__(public_message)
        self.public_message = public_message


async def execute_order_provisioning_transaction(
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
    provision_fn: Callable[[], Awaitable[dict[str, Any]]],
    unexpected_failure_message: str,
    charge_fn: Callable[..., Awaitable[None]] = charge_order_or_raise,
    after_charge_fn: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    await charge_fn(
        order=order,
        order_id=order_id,
        user_id=int(user_id),
        reseller_id=int(reseller_id),
        final_price=final_price,
        cost_price=cost_price,
        lang=lang,
        number_mode=number_mode,
        source=source,
    )
    if after_charge_fn is not None:
        await after_charge_fn()

    try:
        return await provision_fn()
    except ProviderProvisioningError:
        raise
    except Exception as exc:
        await _refund_unexpected_provisioning_failure(
            order_id=order_id,
            user_id=int(user_id),
            reseller_id=int(reseller_id),
            final_price=final_price,
            cost_price=cost_price,
        )
        raise UnexpectedProvisioningError(unexpected_failure_message) from exc


async def _refund_unexpected_provisioning_failure(
    *,
    order_id: Any,
    user_id: int,
    reseller_id: int,
    final_price: float,
    cost_price: float,
) -> None:
    refund_ok, _refund_msg = await FinancialManager.refund_core_purchase(
        int(user_id),
        order_id,
        final_price,
        cost_price,
        reseller_id=int(reseller_id),
    )
    await update_order_status(order_id, "refunded" if refund_ok else "failed")
    await update_order_details(
        order_id,
        {
            "provisioning_state": "provider_failed_refunded" if refund_ok else "provider_failed_refund_error",
            "provisioning_failure_at": _utc_now(),
        },
    )


__all__ = [
    "OrderChargeError",
    "ProviderProvisioningError",
    "UnexpectedProvisioningError",
    "execute_order_provisioning_transaction",
]
