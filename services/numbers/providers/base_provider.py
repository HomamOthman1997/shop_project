"""A common interface for all number providers.

Each method returns a dictionary conforming to one of
`PriceResponse`, `BuyResponse`, or `SMSResponse` from
`services.numbers.types`.
"""
from typing import Optional

from services.numbers.types import PriceResponse, BuyResponse, SMSResponse


class BaseProvider:

    async def get_price(
        self,
        service: str,
        country: Optional[str] = None,
        state: Optional[str] = None,
    ) -> PriceResponse:
        raise NotImplementedError

    async def buy_number(
        self,
        service: str,
        country: Optional[str] = None,
        state: Optional[str] = None,
        **kwargs,
    ) -> BuyResponse:
        raise NotImplementedError

    async def get_sms(self, activation_id: str) -> SMSResponse:
        raise NotImplementedError

    async def cancel(self, activation_id: str) -> SMSResponse:
        raise NotImplementedError

    # optional helper methods that not all providers support
    # some services expose account/balance endpoints which can be used
    # for diagnostics; implementations may return None if unavailable.
    async def get_account(self) -> Optional[dict]:
        """Return raw account information if supported by the API."""
        return None

    async def get_balance(self) -> Optional[float]:
        """Return current balance/credits for the account, or ``None``.

        The returned value may be used for logging or pre‑purchase checks; the
        base implementation simply returns ``None``.
        """
        return None
