from __future__ import annotations


MAIN_PLATFORM_SERVICES = (
    {"key": "main_bot", "label_en": "CyberZone Hub", "label_ar": "مركز CyberZone"},
    {"key": "p2p", "label_en": "P2P", "label_ar": "بي تو بي"},
    {"key": "cards", "label_en": "Card EX", "label_ar": "Card EX"},
)

MAIN_PRODUCT_LINES = (
    {"key": "numbers", "label_en": "Numbers Bot", "label_ar": "بوت الأرقام"},
    {"key": "digital_store", "label_en": "Digital Store", "label_ar": "المتجر الرقمي"},
    {"key": "card_ex", "label_en": "Card EX", "label_ar": "Card EX"},
    {"key": "create_bot", "label_en": "Reseller Bot Builder", "label_ar": "إنشاء بوت ريسيلر"},
)


def render_main_product_lines(lang: str) -> str:
    is_ar = str(lang or "").lower().startswith("ar")
    labels = [item["label_ar"] if is_ar else item["label_en"] for item in MAIN_PRODUCT_LINES]
    return " - ".join(labels)
