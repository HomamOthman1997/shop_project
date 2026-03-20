from typing import Any, Optional, TypedDict


class PriceResponse(TypedDict, total=False):
    success: bool
    price: float
    api_service_name: str
    raw: Any


class BuyResponse(TypedDict, total=False):
    success: bool
    order_id: Optional[str]
    number: Optional[str]
    raw: Any


class SMSResponse(TypedDict, total=False):
    success: bool
    messages: list[str]
    raw: Any
