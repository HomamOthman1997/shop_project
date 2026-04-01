from __future__ import annotations


MAIN_PLATFORM_SERVICES = (
    {"key": "main_bot", "label_en": "Main Bot", "label_ar": "البوت الرئيسي"},
    {"key": "p2p", "label_en": "P2P", "label_ar": "بي تو بي"},
    {"key": "cards", "label_en": "Cards", "label_ar": "شراء البطاقات"},
)

MAIN_PRODUCT_LINES = (
    {"key": "numbers", "label_en": "Numbers", "label_ar": "الأرقام"},
    {"key": "proxies", "label_en": "Proxies", "label_ar": "البروكسيات"},
    {"key": "games", "label_en": "Game Topups", "label_ar": "شحن الألعاب"},
    {"key": "apps", "label_en": "Apps", "label_ar": "التطبيقات"},
    {"key": "create_bot", "label_en": "Create Bots", "label_ar": "إنشاء البوتات"},
)


def render_main_product_lines(lang: str) -> str:
    is_ar = str(lang or "").lower().startswith("ar")
    labels = [item["label_ar"] if is_ar else item["label_en"] for item in MAIN_PRODUCT_LINES]
    return " - ".join(labels)
