from __future__ import annotations


MAIN_PRODUCT_LINES = (
    {
        "key": "numbers",
        "label_en": "Numbers Bot",
        "label_ar": "بوت الأرقام",
        "desc_en": "phone numbers and activation orders",
        "desc_ar": "شراء واستلام الأرقام",
    },
    {
        "key": "digital_store",
        "label_en": "Digital Store",
        "label_ar": "المتجر الرقمي",
        "desc_en": "game top-ups, digital cards, SIM and eSIM",
        "desc_ar": "شحن ألعاب، بطاقات رقمية، SIM و eSIM",
    },
    {
        "key": "card_ex",
        "label_en": "Card EX",
        "label_ar": "Card EX",
        "desc_en": "card selling and exchange",
        "desc_ar": "بيع وتصريف البطاقات",
    },
    {
        "key": "create_bot",
        "label_en": "Reseller Bot Builder",
        "label_ar": "إنشاء بوت ريسيلر",
        "desc_en": "create and manage reseller bots",
        "desc_ar": "إنشاء وإدارة بوتات الريسيلر",
    },
)

OTHER_SERVICE_LINES = tuple(item for item in MAIN_PRODUCT_LINES if item["key"] in {"numbers", "digital_store", "card_ex"})


def _is_ar(lang: str) -> bool:
    return str(lang or "").lower().startswith("ar")


def _line(item: dict[str, str], *, is_ar: bool) -> str:
    label = item["label_ar"] if is_ar else item["label_en"]
    desc = item["desc_ar"] if is_ar else item["desc_en"]
    return f"- {label}: {desc}"


def render_main_product_lines(lang: str) -> str:
    is_ar = _is_ar(lang)
    title = "خريطة المنصة:" if is_ar else "Platform map:"
    return "\n".join([title, *[_line(item, is_ar=is_ar) for item in MAIN_PRODUCT_LINES]])


def render_other_services_text(lang: str, available_keys: list[str] | tuple[str, ...]) -> str:
    is_ar = _is_ar(lang)
    available = {str(key) for key in available_keys}
    lines = [_line(item, is_ar=is_ar) for item in OTHER_SERVICE_LINES if item["key"] in available]
    if is_ar:
        return "\n".join(
            [
                "خدماتنا الأخرى",
                "",
                "اختر البوت حسب حاجتك:",
                *lines,
                "",
                "كتالوج الخدمات الخاصة يبقى داخل مركز CyberZone.",
            ]
        )
    return "\n".join(
        [
            "Our Other Services",
            "",
            "Choose the bot that matches what you need:",
            *lines,
            "",
            "The custom-services catalog stays inside CyberZone Hub.",
        ]
    )
