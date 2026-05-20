import re
import unicodedata
from typing import Dict


_SERVICE_ALIAS_REPLACEMENTS: dict[str, str] = {
    "اتابول": "attapoll",
    "اتا بول": "attapoll",
    "أتابول": "attapoll",
    "أتا بول": "attapoll",
}


def normalize_service_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = _SERVICE_ALIAS_REPLACEMENTS.get(text.strip(), text)
    return re.sub(r"[^a-z0-9]+", "", text)


_RAW_SERVICE_FAMILY_GROUPS: Dict[str, tuple[str, ...]] = {
    # Keep Google product lines separate.
    # Gmail should not absorb other Google services like Google Voice/Play/Chat.
    "gmail": ("googlegmail",),
    "microsoft": ("microsoftazure", "microsoftoutlook", "microsoftrewards", "microsoftxboxlive"),
    "capitalone": ("capitalonecafe", "capitaloneshopping"),
    "match": ("matchmeetic",),
    "mercado": ("mercadolibre", "mercadopago"),
    "sendgrid": ("twiliosendgrid",),
    "tencent": ("tencentcloud", "tencentqq"),
    "amazonwebservices": ("amazonamazonwebservices",),
    "anthropic": ("claude", "claudeai", "claudeaianthropic"),
    "battlenet": ("battlenetblizzard",),
    "blablacar": ("blabla",),
    "brandedsurveys": ("brandedsurvey",),
    "burnerapp": ("burner",),
    "cheapvoip": ("cheapvoiphotvoip",),
    "crumblcookies": ("crumbl",),
    "dataannotationtech": ("dataannotation",),
    "fetchrewards": ("fetch",),
    "fivesurveys": ("fivesurvey",),
    "footlocker": ("kidsfootlocker",),
    "freecash": ("freecashcom",),
    "grailed": ("grailedcom",),
    "habitburgerandgrill": ("habitburger",),
    "hepsiburada": ("hepsiburadacom",),
    "instagram": ("instagramthreads",),
    "irazoo": ("irazoocom",),
    "jeevansathi": ("jeevan",),
    "luckylandslots": ("luckyland",),
    "manusai": ("manus",),
    "milesrewards": ("milesreward",),
    "mistralai": ("mistral",),
    "modeearnapp": ("modeearn",),
    "robinhood": ("myrobinhood",),
    "numero": ("numeroesim",),
    "openai": ("openaichatgpt",),
    "opinionsoutpost": ("opinionoutpost",),
    "oracle": ("oraclecloud",),
    "playfulrewards": ("playful",),
    "postmates": ("uberpostmates",),
    "remotasks": ("remotask",),
    "rewardedplay": ("rewardedplayplay4",),
    "triumph": ("ripsbytriumph",),
    "ritual": ("ritualco",),
    "samsclub": ("sam'sclub",),
    "samsung": ("samsungshop",),
    "sikayetvar": ("sikayetvar",),
    "sisal": ("sisalfunclub",),
    "skybet": ("skybetting",),
    "taptap": ("taptapsend",),
    "tipalti": ("wpstipalti",),
    "twitter": ("twitterx",),
    # Explicit business-approved merges only.
    "swagbucks": (
        "inboxdollars",
        "inboxpounds",
        "mypoints",
        "ysense",
        "adgatesurvey",
        "tadapoll",
        "swagbucksinboxdollarsinboxpoundsmypointsysensenoonesadgatesurveytadapollpay",
    ),
    "united": ("unitedairlines",),
    "viavan": ("viaappviavan",),
    "wagerweb": ("wagerwebeu",),
    "walmart": ("walmart4",),
    "webull": ("webullpay",),
    "weee": ("weee!",),
    "winzo": ("winzogame",),
    "youla": ("yoularu",),
    "zaxbys": ("zaxby",),
}


def _normalize_groups(raw: Dict[str, tuple[str, ...]]) -> Dict[str, tuple[str, ...]]:
    groups: Dict[str, tuple[str, ...]] = {}
    for canonical, members in raw.items():
        canonical_key = normalize_service_key(canonical)
        if not canonical_key:
            continue
        normalized_members: list[str] = []
        seen = {canonical_key}
        for member in members:
            member_key = normalize_service_key(member)
            if not member_key or member_key in seen:
                continue
            seen.add(member_key)
            normalized_members.append(member_key)
        groups[canonical_key] = tuple(normalized_members)
    return groups


SERVICE_FAMILY_GROUPS = _normalize_groups(_RAW_SERVICE_FAMILY_GROUPS)


def _build_canonical_map(groups: Dict[str, tuple[str, ...]]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for canonical, members in groups.items():
        mapping[canonical] = canonical
        for member in members:
            mapping.setdefault(member, canonical)
    return mapping


CANONICAL_SERVICE_KEYS = _build_canonical_map(SERVICE_FAMILY_GROUPS)


DISPLAY_NAME_OVERRIDES: Dict[str, str] = {
    "gmail": "Gmail",
    "microsoft": "Microsoft Family",
    "capitalone": "Capital One Family",
    "mercado": "Mercado Family",
    "sendgrid": "SendGrid / Twilio SendGrid",
    "tencent": "Tencent Family",
    "amazonwebservices": "Amazon Web Services",
    "anthropic": "Claude / Anthropic",
    "battlenet": "Battle.net / Blizzard",
    "blablacar": "BlaBlaCar",
    "brandedsurveys": "Branded Surveys",
    "fetchrewards": "Fetch Rewards",
    "fivesurveys": "Five Surveys",
    "freecash": "Freecash",
    "habitburgerandgrill": "Habit Burger",
    "hepsiburada": "Hepsiburada",
    "instagram": "Instagram / Threads",
    "openai": "OpenAI / ChatGPT",
    "samsclub": "Sam's Club",
    "swagbucks": "Swagbucks",
    "twitter": "Twitter / X",
    "webull": "Webull / Webull Pay",
}
