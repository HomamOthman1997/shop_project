from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderQuality:
    provider: str
    tier: str
    recommendation_bonus: float
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "tier": self.tier,
            "recommendation_bonus": self.recommendation_bonus,
            "note": self.note,
        }


_QUALITY: dict[str, ProviderQuality] = {
    "smspool": ProviderQuality(
        provider="smspool",
        tier="excellent",
        recommendation_bonus=4.0,
        note="Owner-tested; numbers are consistently good.",
    ),
    "textverified": ProviderQuality(
        provider="textverified",
        tier="excellent",
        recommendation_bonus=4.0,
        note="Owner-tested; numbers are consistently good.",
    ),
    "herosms": ProviderQuality(
        provider="herosms",
        tier="excellent",
        recommendation_bonus=4.0,
        note="Owner-tested; numbers are consistently good.",
    ),
    "telabot": ProviderQuality(
        provider="telabot",
        tier="excellent",
        recommendation_bonus=4.0,
        note="Owner-tested; numbers are consistently good.",
    ),
    "nonvoip": ProviderQuality(
        provider="nonvoip",
        tier="excellent",
        recommendation_bonus=4.0,
        note="Owner-tested; numbers are excellent, refund path is still governed by readiness policy.",
    ),
    "nonvoip_s6": ProviderQuality(
        provider="nonvoip_s6",
        tier="excellent",
        recommendation_bonus=4.0,
        note="Alias lane for the owner-tested NonVoIP provider.",
    ),
    "pvadeals": ProviderQuality(
        provider="pvadeals",
        tier="trusted",
        recommendation_bonus=2.0,
        note="Owner-classified as trusted.",
    ),
    "vaksms": ProviderQuality(
        provider="vaksms",
        tier="mixed",
        recommendation_bonus=-3.0,
        note="Owner-tested as mixed: some numbers receive codes and some do not.",
    ),
    "pvapins": ProviderQuality(
        provider="pvapins",
        tier="mixed",
        recommendation_bonus=-3.0,
        note="Owner-classified as similar to VAKSMS.",
    ),
    "smsready": ProviderQuality(
        provider="smsready",
        tier="unclassified",
        recommendation_bonus=-6.0,
        note="Not classified by owner yet.",
    ),
}

_DEFAULT = ProviderQuality(
    provider="",
    tier="unclassified",
    recommendation_bonus=-6.0,
    note="Provider quality has not been classified yet.",
)


def provider_quality(provider_code: str) -> ProviderQuality:
    code = str(provider_code or "").strip().lower()
    if not code:
        return _DEFAULT
    return _QUALITY.get(code, ProviderQuality(**{**_DEFAULT.to_dict(), "provider": code}))


def provider_recommendation_bonus(provider_code: str) -> float:
    return provider_quality(provider_code).recommendation_bonus


def provider_quality_rows() -> list[dict[str, Any]]:
    return [provider_quality(code).to_dict() for code in sorted(_QUALITY)]
