from __future__ import annotations

import re
from typing import Any

SERVICE_ORDER: tuple[str, ...] = (
    "games",
    "chat_apps",
    "communications_data",
    "internet_providers",
    "paid_apps",
    "numbers_services",
    "paid_subscriptions",
    "store_cards",
)

SERVICE_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "paid_apps",
        (
            "android amt",
            "dft pro",
            "eft pro",
            "unlock tool",
            "unlock",
            "انلوك",
            "amt",
        ),
    ),
    (
        "internet_providers",
        (
            "internet provider",
            "internet",
            "wifi",
            "wi-fi",
            "fiber",
            "broadband",
            "مزود",
            "مزودات",
            "انترنت",
            "hifi net",
            "lazer net",
            "pro net",
            "sama net",
            "view net",
            "mts",
            "party star",
        ),
    ),
    (
        "paid_subscriptions",
        (
            "telegram premium",
            "telegram star",
            "telegram stars",
            "subscriptions",
            "subscription",
            "premium",
            "اشتراك",
            "اشتراكات",
            "بريميوم",
        ),
    ),
    (
        "chat_apps",
        (
            "discord",
            "imo",
            "chat",
            "social",
            "apps",
            "applications",
            "tada",
            "bigo",
            "coco",
            "azal",
            "live",
            "whatsapp",
            "messenger",
            "viber",
            "line",
            "wechat",
            "دردشة",
            "تطبيقات الدردشة",
        ),
    ),
    (
        "store_cards",
        (
            "steam",
            "itunes",
            "apple",
            "google play",
            "playstation",
            "psn",
            "xbox",
            "nintendo",
            "razer",
            "roblox",
            "gift card",
            "gift cards",
            "voucher",
            "vouchers",
            "cards",
            "visa",
            "mastercard",
            "amazon",
            "بطاقات",
            "قسائم",
            "متاجر",
        ),
    ),
    (
        "numbers_services",
        (
            "otp",
            "sms",
            "virtual number",
            "numbers",
            "number",
            "خدمات الارقام",
            "ارقام",
            "رقم",
        ),
    ),
    (
        "communications_data",
        (
            "sim",
            "telecom",
            "topup",
            "top up",
            "data",
            "mtn",
            "syriatel",
            "sawa",
            "اتصالات",
            "بيانات",
            "رصيد",
        ),
    ),
    (
        "games",
        (
            "pubg",
            "free fire",
            "mobile legends",
            "mlbb",
            "honor of kings",
            "clash of clans",
            "brawl stars",
            "call of duty",
            "cod",
            "valorant",
            "fortnite",
            "genshin",
            "war robots",
            "8 ball pool",
            "jawaker",
            "yalla ludo",
            "game",
            "games",
            "الالعاب",
            "ألعاب",
        ),
    ),
]

FAMILY_RULES: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {
    "games": [
        ("pubg", "PUBG", ("pubg", "pubgm", "new state", "ببجي", "شدات")),
        ("mobile_legends", "Mobile Legends", ("mobile legends", "mlbb", "موبايل ليجند")),
        ("free_fire", "Free Fire", ("free fire", "freefire", "فري فاير")),
        ("honor_of_kings", "Honor of Kings", ("honor of kings", "honor of king", "hok")),
        ("league_of_legends", "League of Legends", ("league of legends", "riot points", "lol")),
        ("genshin_impact", "Genshin Impact", ("genshin impact", "genshin")),
        ("eafc_mobile", "EAFC Mobile", ("eafc", "fc mobile")),
        ("delta_force", "Delta Force", ("delta force", "garena deltaforce")),
        ("clash_of_clans", "Clash of Clans", ("clash of clans", "coc")),
        ("roblox", "Roblox", ("roblox",)),
        ("valorant", "Valorant", ("valorant",)),
        ("war_robots", "War Robots", ("war robots",)),
        ("call_of_duty", "Call of Duty", ("call of duty", "cod")),
    ],
    "chat_apps": [
        ("discord", "Discord", ("discord",)),
        ("imo", "IMO", ("imo",)),
        ("telegram", "Telegram", ("telegram", "تلغرام", "تلجرام")),
        ("whatsapp", "WhatsApp", ("whatsapp", "واتساب")),
        ("bigo_live", "Bigo Live", ("bigo",)),
        ("coco_live", "Coco Live", ("coco",)),
        ("azal_live", "Azal Live", ("azal",)),
        ("tada_chat", "Tada Chat", ("tada",)),
        ("line", "LINE", ("line",)),
        ("wechat", "WeChat", ("wechat",)),
    ],
    "paid_subscriptions": [
        ("netflix", "Netflix", ("netflix",)),
        ("shahid", "Shahid", ("shahid",)),
        ("spotify", "Spotify", ("spotify",)),
        ("youtube", "YouTube", ("youtube",)),
        ("telegram_premium", "Telegram Premium", ("telegram premium", "telegram stars", "telegram star")),
        ("canva", "Canva", ("canva",)),
        ("chatgpt", "ChatGPT", ("chatgpt",)),
    ],
    "store_cards": [
        ("apple_itunes", "Apple / iTunes", ("itunes", "apple", "ابل", "ايتونز")),
        ("steam", "Steam", ("steam", "ستيم")),
        ("google_play", "Google Play", ("google play", "google", "جوجل")),
        ("playstation", "PlayStation", ("playstation", "psn")),
        ("xbox", "Xbox", ("xbox",)),
        ("nintendo", "Nintendo", ("nintendo",)),
        ("razer_gold", "Razer Gold", ("razer",)),
        ("roblox", "Roblox", ("roblox", "روبلوكس")),
        ("visa", "Visa", ("visa",)),
    ],
    "communications_data": [
        ("telecom_data", "Telecom & Data", ("telecom", "data", "topup", "اتصالات", "بيانات", "رصيد")),
    ],
    "internet_providers": [
        ("internet_providers", "Internet Providers", ("internet", "wifi", "fiber", "مزود", "انترنت")),
    ],
    "paid_apps": [
        ("android_amt", "Android AMT", ("android amt", "amt")),
        ("dft_pro", "DFT Pro", ("dft pro",)),
        ("eft_pro", "EFT Pro", ("eft pro",)),
        ("unlock_tool", "Unlock Tool", ("unlock tool", "unlock", "انلوك")),
    ],
    "numbers_services": [
        ("numbers_services", "Numbers Services", ("sms", "otp", "number", "numbers", "ارقام", "رقم")),
    ],
}

REGION_TOKENS: tuple[str, ...] = (
    "global",
    "usa",
    "us",
    "uk",
    "europe",
    "eu",
    "americas",
    "america",
    "sea",
    "asia",
    "mena",
    "na",
    "sa",
    "latam",
    "ksa",
    "saudi arabia",
    "uae",
    "turkey",
    "india",
    "indonesia",
    "malaysia",
    "singapore",
    "cambodia",
    "thailand",
    "vietnam",
    "pakistan",
    "bangladesh",
    "canada",
    "brazil",
    "mexico",
    "japan",
    "korea",
    "hong kong",
    "taiwan",
    "germany",
    "german",
    "naeu",
    "sg",
    "my",
    "sgmy",
    "ph",
    "kh",
    "vn",
    "philippines",
)


def norm_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def clean_family_text(value: str | None) -> str:
    raw = norm_text(value)
    raw = re.sub(r"[\[\]{}]", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return ""
    escaped = [re.escape(token) for token in REGION_TOKENS]
    paren = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", raw)
    if paren:
        base = norm_text(paren.group(1))
        region = norm_text(paren.group(2))
        if any(re.fullmatch(token, region, flags=re.IGNORECASE) for token in escaped):
            raw = base
    suffix = re.match(rf"^(.*?)(?:\s*[-/|]\s*|\s+)({'|'.join(escaped)})$", raw, flags=re.IGNORECASE)
    if suffix:
        raw = norm_text(suffix.group(1))
    raw = re.sub(r"(gift\s*cards?|giftcards?|vouchers?|voucher|cards?)", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def detect_service_key(text: str | None) -> str:
    n = norm_text(text)
    if not n:
        return "games"
    for key, tokens in SERVICE_RULES:
        if any(token in n for token in tokens):
            return key
    return "games"


def guess_family(service_key: str, category_name: str, sample_names: list[str] | None = None) -> tuple[str, str]:
    sample_names = list(sample_names or [])
    text = norm_text(" ".join([category_name] + sample_names))
    rules = list(FAMILY_RULES.get(service_key, []))
    for family_key, label, tokens in rules:
        if any(token in text for token in tokens):
            return family_key, label

    base = clean_family_text(category_name) or clean_family_text(" ".join(sample_names[:2]))
    if not base:
        return "other", "Other"
    family_key = re.sub(r"[^a-z0-9]+", "_", base).strip("_") or "other"
    label = " ".join(part.capitalize() for part in base.split()[:4]) or "Other"
    return family_key, label


def service_sort_key(value: str | None) -> int:
    key = str(value or "").strip()
    try:
        return SERVICE_ORDER.index(key)
    except ValueError:
        return len(SERVICE_ORDER) + 1


def provider_label(provider_code: str, *, lang: str) -> str:
    code = norm_text(provider_code)
    if code == "za3em":
        return "الزعيم" if lang == "ar" else "Za3em"
    if code == "g2bulk":
        return "جي تو بالك" if lang == "ar" else "G2Bulk"
    if code in {"ingsm", "in_gsm"}:
        return "إن-جي إس إم" if lang == "ar" else "in-gsm"
    return provider_code or ("غير محدد" if lang == "ar" else "Unknown")


def pick_cheapest_offer(offers: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [row for row in offers if bool(row.get("available")) and float(row.get("price") or 0.0) > 0]
    if not valid:
        return None
    valid.sort(key=lambda row: float(row.get("price") or 0.0))
    return dict(valid[0])
