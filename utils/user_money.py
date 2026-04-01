from __future__ import annotations


_MONEY_EMOJI = "💲"


def format_usd(amount) -> str:
    try:
        value = float(amount or 0)
    except Exception:
        value = 0.0
    return f"{value:.2f} {_MONEY_EMOJI}"


def format_usd_compact(amount) -> str:
    try:
        value = float(amount or 0)
    except Exception:
        value = 0.0
    if value.is_integer():
        return f"{int(value)} {_MONEY_EMOJI}"
    return f"{value:.2f} {_MONEY_EMOJI}"
