from __future__ import annotations

from typing import Any

# Public obfuscated identifiers shown to end users.
# Keep mapping stable to avoid confusing existing users.
_PROVIDER_PUBLIC_IDS: dict[str, str] = {
    "herosms": "S1",
    "textverified": "S2",
    "smspool": "S3",
    "telabot": "S4",
    "pvadeals": "S5",
    "vaksms": "S6",
    "smsman": "S7",
    "smsman_s6": "S8",
    "smsready": "S9",
    "pvapins": "S10",
    # Proxy providers are also hidden behind the same public IDs.
    "9proxy": "S5",
    "4g": "S5",
    "cyberyozh": "S6",
}

_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "S1": "Alpha",
    "S2": "Bravo",
    "S3": "Charlie",
    "S4": "Delta",
    "S5": "Echo",
    "S6": "Foxtrot",
    "S7": "NonVoIP",
    "S8": "NonVoIP",
    "S9": "Golf",
    "S10": "Hotel",
}

_GENERIC_PROVIDER_ERROR = {
    "en": "Service is temporarily unavailable. Please try another option.",
    "ar": "الخدمة غير متاحة حاليا. جرب خيارا آخر.",
}


def provider_public_id(provider_code: Any) -> str:
    code = str(provider_code or "").strip().lower()
    if not code:
        return "S5"
    return _PROVIDER_PUBLIC_IDS.get(code, "S5")


def provider_display_name(provider_code: Any) -> str:
    public_id = provider_public_id(provider_code)
    return _PROVIDER_DISPLAY_NAMES.get(public_id, public_id)


def provider_generic_error(lang: str = "en") -> str:
    key = "ar" if str(lang).strip().lower().startswith("ar") else "en"
    return _GENERIC_PROVIDER_ERROR[key]
