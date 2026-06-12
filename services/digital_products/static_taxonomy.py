from __future__ import annotations

import re
from typing import Any

from services.digital_products.custom_catalog import FAMILY_TABLE as CUSTOM_FAMILY_TABLE, SECTION_TABLE

SERVICE_ORDER: tuple[str, ...] = tuple(str(row.get("key") or "").strip() for row in SECTION_TABLE if str(row.get("key") or "").strip())

CHAT_FAMILY_ALIASES: dict[str, tuple[str, str]] = {
    "4fun chat": ("4fun_chat", "4fun Chat"),
    "ahlan chat": ("ahlan_chat", "Ahlan Chat"),
    "amar chat": ("amar_chat", "Amar Chat"),
    "ayumi chat": ("ayumi_chat", "Ayumi Chat"),
    "ayome chat": ("ayumi_chat", "Ayumi Chat"),
    "azal live": ("azal_live", "Azal Live"),
    "bella chat": ("bella_chat", "Bella Chat"),
    "billa chat": ("bella_chat", "Bella Chat"),
    "bigo live": ("bigo_live", "Bigo Live"),
    "bigo live diamonds": ("bigo_live", "Bigo Live"),
    "binmo chat": ("binmo_chat", "Binmo Chat"),
    "bobo chat": ("bobo_chat", "Bobo Chat"),
    "boli": ("boli", "Boli"),
    "chamet": ("chamet", "Chamet"),
    "coco live": ("coco_live", "Coco Live"),
    "cocco live": ("coco_live", "Coco Live"),
    "discord": ("discord", "Discord"),
    "ditto live": ("ditto_live", "Ditto Live"),
    "fancy life": ("fancy_life", "Fancy Life"),
    "fancy live": ("fancy_life", "Fancy Life"),
    "fofo chat": ("fofo_chat", "Fofo Chat"),
    "funup": ("funup", "FunUp"),
    "gimme live": ("gimme_live", "Gimme Live"),
    "hago": ("hago", "Hago"),
    "haki chat": ("haki_chat", "Haki Chat"),
    "hamiparty": ("hamiparty", "HamiParty"),
    "hapi arabic": ("hapi_arabic", "Hapi Arabic"),
    "hati": ("hati", "Hati"),
    "hawa chat": ("hawa_chat", "Hawa Chat"),
    "haya chat": ("haya_chat", "Haya Chat"),
    "hiya chat": ("haya_chat", "Haya Chat"),
    "hayuki": ("hayuki", "Hayuki"),
    "higo": ("higo", "Higo"),
    "hiyoo chat": ("hiyoo_chat", "Hiyoo Chat"),
    "imo": ("imo", "IMO"),
    "imu chat": ("imu_chat", "Imu Chat"),
    "janko chat": ("janko_chat", "Janko Chat"),
    "kessmet": ("kessmet", "Kessmet"),
    "kiti": ("kiti", "Kiti"),
    "kiyo live": ("kiyo_live", "Kiyo Live"),
    "kwai": ("kwai", "Kwai"),
    "laki": ("laki", "Laki"),
    "lama chat": ("lama_chat", "Lama Chat"),
    "layam": ("layam", "Layam"),
    "layla chat": ("layla_chat", "Layla Chat"),
    "light chat": ("light_chat", "Light Chat"),
    "ligo live": ("ligo_live", "Ligo Live"),
    "likee": ("likee", "Likee"),
    "line": ("line", "LINE"),
    "lions chat": ("lions_chat", "Lions Chat"),
    "maza chat": ("maza_chat", "Maza Chat"),
    "mico live": ("mico_live", "Mico Live"),
    "migo live": ("migo_live", "Migo Live"),
    "mr7ba chat": ("mr7ba_chat", "Mr7ba Chat"),
    "nabd": ("nabd", "Nabd"),
    "ohla chat": ("ohla_chat", "Ohla Chat"),
    "اوهلا شات": ("ohla_chat", "Ohla Chat"),
    "olmet chat": ("olmet_chat", "Olmet Chat"),
    "oloo live": ("oloo_live", "Oloo Live"),
    "opa live": ("opa_live", "Opa Live"),
    "pawa live": ("pawa_live", "Pawa Live"),
    "poppo live": ("poppo_live", "Poppo Live"),
    "pota live": ("pota_live", "Pota Live"),
    "roka live": ("roka_live", "Roka Live"),
    "sahra": ("sahra", "Sahra"),
    "salam": ("salam", "Salam"),
    "saya likee": ("saya_likee", "Saya Likee"),
    "sodfa": ("sodfa", "Sodfa"),
    "soyo chat": ("soyo_chat", "Soyo Chat"),
    "sugo chat": ("sugo_chat", "Sugo Chat"),
    "super live": ("super_live", "Super Live"),
    "tada chat": ("tada_chat", "Tada Chat"),
    "taka life": ("taka_life", "Taka Life"),
    "taka live": ("taka_life", "Taka Life"),
    "talk talk": ("talk_talk", "Talk Talk"),
    "tami chat": ("tami_chat", "Tami Chat"),
    "tango live": ("tango_live", "Tango Live"),
    "toptop": ("toptop", "TopTop"),
    "vova": ("vova", "VOVA"),
    "waaw": ("waaw", "Waaw"),
    "waho chat": ("waho_chat", "Waho Chat"),
    "weak chat": ("weak_chat", "Weak Chat"),
    "xena live": ("xena_live", "Xena Live"),
    "yaahlan chat": ("yaahlan_chat", "Yaahlan Chat"),
    "yami star": ("yami_star", "Yami Star"),
    "yoparti": ("yoparti", "YoParti"),
    "yoyo chat": ("yoyo_chat", "Yoyo Chat"),
    "yudo": ("yudo", "Yudo"),
    "دانا شات": ("dana_chat", "Dana Chat"),
}

_CHAT_ALIAS_TERMS: tuple[str, ...] = tuple(CHAT_FAMILY_ALIASES.keys())

SERVICE_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "social_services",
        (
            "followers",
            "follow",
            "متابعين",
            "مشاهدات",
            "لايكات",
            "تفاعل",
            "خدمات تيك توك",
            "خدمات الفيسبوك",
            "خدمات انستغرام",
            "خدمات تلجرام",
            "خدمات تلغرام",
            "خدمات كيك",
            "خدمات وتس اب",
            "خدمات يوتيوب",
        ),
    ),
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
            "netflix",
            "shahid",
            "tv shahid",
            "snapchat",
            "chatgpt",
            "canva",
            "youtube",
            "spotify",
            "subscriptions",
            "subscription",
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
            "telegram",
            "telegram stars",
            "hago",
            "chamet",
            "yoyo",
            "yami",
            "layla",
            "tango",
            "waaw",
            "waho",
            "toptop",
            "sugo",
            "tada",
            "bigo",
            "coco",
            "azal",
            "whatsapp",
            "messenger",
            "viber",
            "line",
            "wechat",
            "قسم التطبيقات",
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
            "google",
            "google play",
            "playstation",
            "play station",
            "psn",
            "xbox",
            "nintendo",
            "razer",
            "roblox",
            "gift card",
            "gift cards",
            "voucher",
            "vouchers",
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

for _service_key, _rows in CUSTOM_FAMILY_TABLE.items():
    existing = list(FAMILY_RULES.get(_service_key, []))
    existing_keys = {row[0] for row in existing}
    merged_rows = [
        (str(row.get("key") or "").strip(), str(row.get("label") or "").strip(), tuple(str(alias or "").strip().lower() for alias in tuple(row.get("aliases") or ()) if str(alias or "").strip()))
        for row in _rows
        if str(row.get("key") or "").strip() and str(row.get("label") or "").strip()
    ]
    for merged in reversed(merged_rows):
        if merged[0] in existing_keys:
            existing = [merged if row[0] == merged[0] else row for row in existing]
        else:
            existing.insert(0, merged)
    FAMILY_RULES[_service_key] = existing

CUSTOM_SERVICE_RULES: list[tuple[str, tuple[str, ...]]] = []
for _section in SECTION_TABLE:
    _section_key = str(_section.get("key") or "").strip()
    if not _section_key:
        continue
    _aliases: list[str] = [str(alias or "").strip().lower() for alias in tuple(_section.get("aliases") or ()) if str(alias or "").strip()]
    for _row in CUSTOM_FAMILY_TABLE.get(_section_key, ()):
        _aliases.extend(str(alias or "").strip().lower() for alias in tuple(_row.get("aliases") or ()) if str(alias or "").strip())
    CUSTOM_SERVICE_RULES.append((_section_key, tuple(dict.fromkeys(_aliases))))

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


def _contains_taxonomy_token(text: str, token: str) -> bool:
    alias = norm_text(token)
    if not alias:
        return False
    return bool(re.search(rf"(^|[^a-z0-9\u0600-\u06ff]){re.escape(alias)}([^a-z0-9\u0600-\u06ff]|$)", text))


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


def detect_service_key_strict(text: str | None) -> str | None:
    n = norm_text(text)
    if not n:
        return None
    if any(token in n for token in ("ارقام", "رقم", "numbers", "number", "otp", "sms", "virtual number")):
        return "numbers_services"
    if _contains_taxonomy_token(n, "telegram"):
        return "chat_apps"
    # A named game always belongs under Games, even when the product is sold as a card or voucher.
    for row in CUSTOM_FAMILY_TABLE.get("games", ()):
        aliases = [str(alias or "").strip().lower() for alias in tuple(row.get("aliases") or ()) if str(alias or "").strip()]
        if any(_contains_taxonomy_token(n, alias) for alias in aliases):
            return "games"
    for _family_key, _label, aliases in FAMILY_RULES.get("games", ()):
        if any(_contains_taxonomy_token(n, alias) for alias in aliases):
            return "games"
    for service_key, rows in CUSTOM_FAMILY_TABLE.items():
        if service_key == "games":
            continue
        for row in rows:
            aliases = [str(alias or "").strip().lower() for alias in tuple(row.get("aliases") or ()) if str(alias or "").strip()]
            if any(n == alias for alias in aliases):
                return service_key
            if any(re.search(rf"(^|[^a-z0-9\u0600-\u06ff]){re.escape(alias)}([^a-z0-9\u0600-\u06ff]|$)", n) for alias in aliases):
                return service_key
    if any(_contains_taxonomy_token(n, token) for token in _CHAT_ALIAS_TERMS):
        return "chat_apps"
    for key, tokens in CUSTOM_SERVICE_RULES:
        if any(_contains_taxonomy_token(n, token) for token in tokens):
            return key
    for key, tokens in SERVICE_RULES:
        if any(_contains_taxonomy_token(n, token) for token in tokens):
            return key
    return None


def detect_service_key(text: str | None) -> str:
    return detect_service_key_strict(text) or "games"


def guess_family(service_key: str, category_name: str, sample_names: list[str] | None = None) -> tuple[str, str]:
    sample_names = list(sample_names or [])
    text = norm_text(" ".join([category_name] + sample_names))
    if service_key == "chat_apps":
        for token, mapped in CHAT_FAMILY_ALIASES.items():
            if token in text:
                return mapped
    rules = list(FAMILY_RULES.get(service_key, []))
    exact_candidates = [clean_family_text(category_name), *[clean_family_text(name) for name in sample_names[:3]]]
    for candidate in exact_candidates:
        if not candidate:
            continue
        for family_key, label, tokens in rules:
            if any(candidate == clean_family_text(token) for token in tokens):
                return family_key, label
    for family_key, label, tokens in rules:
        if any(_contains_taxonomy_token(text, token) for token in tokens):
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
    if code == "bittopup":
        return "بيت توب أب" if lang == "ar" else "BitTopup"
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
