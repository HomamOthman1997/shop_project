from __future__ import annotations

from urllib.parse import urlparse

BITTOPUP_BASE_URL = "https://bittopup.com"

# Curated from the operator-reviewed BitTopup sheet. BitTopup is kept
# for chat apps only; games are served by G2Bulk.
BITTOPUP_INDEX_ROWS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ('Likee-Gift-Card', 'chat_apps', 'likee', 'Likee', 'Global', 'Likee Gift Card'),
    ('imo-diamond-recharge', 'chat_apps', 'imo', 'IMO', 'Global', 'IMO Diamond Recharge'),
    ('Discord-Nitro-Subscription', 'chat_apps', 'discord', 'Discord', 'Global', 'Discord Nitro Subscription'),
    ('MICO-Live-Coins-MENA', 'chat_apps', 'mico_live', 'Mico Live', 'Global', 'MICO Live Coins (MENA)'),
    ('mico-live-coins', 'chat_apps', 'mico_live', 'Mico Live', 'Global', 'MICO Live Coins'),
    ('MIKA-Chat-Coins', 'chat_apps', 'mika_chat_coins', 'Mika Chat Coins', 'Global', 'MIKA Chat Coins'),
    ('Likee-Diamond', 'chat_apps', 'likee', 'Likee', 'Global', 'Likee'),
    ('bigo-live-diamonds', 'chat_apps', 'bigo_live', 'Bigo Live', 'Global', 'Bigo Recharge'),
    ('Nimo-TV-Diamonds', 'chat_apps', 'nimo_tv', 'Nimo TV', 'Global', 'Nimo TV Diamonds'),
    ('Kuaishou-Kwai-CN-Coin', 'chat_apps', 'kwai', 'Kwai', 'Global', 'Kuaishou Kwai (CN) Coin'),
    ('Poppo-Live-Coins', 'chat_apps', 'poppo_live', 'Poppo Live', 'Global', 'Poppo Live Coins'),
    ('soulchill', 'chat_apps', 'soul_chill', 'Soul Chill', 'Global', 'Soul Chill'),
    ('sugovoice-chat-party-top-up', 'chat_apps', 'sugo_voice', 'SUGO Voice', 'Global', 'SUGO Recharge'),
    ('chamet', 'chat_apps', 'chamet', 'Chamet', 'Global', 'Chamet Recharge'),
    ('xena-live', 'chat_apps', 'xena_live', 'Xena Live', 'Global', 'Xena Live'),
    ('yoho-group-voice-chat', 'chat_apps', 'yoho_group_voice_chat', 'YoHo Group Voice Chat', 'Global', 'YoHo: Group Voice Chat'),
    ('yoyo', 'chat_apps', 'yoyo_live', 'Yoyo Live', 'Global', 'Yoyo Live'),
    ('migo-live', 'chat_apps', 'migo_live', 'Migo Live', 'Global', 'Migo Live'),
    ('tango-coins', 'chat_apps', 'tango', 'Tango', 'Global', 'Tango Coins Recharge'),
    ('1star-chat', 'chat_apps', '1star_chat', '1Star Chat', 'Global', '1Star Chat'),
    ('4chat', 'chat_apps', '4chat', '4CHAT', 'Global', '4CHAT'),
    ('amo-chat', 'chat_apps', 'amo_chat', 'Amo Chat', 'Global', 'Amo Chat'),
    ('azal', 'chat_apps', 'azal_live', 'Azal Live', 'Global', 'Azal'),
    ('boli', 'chat_apps', 'boli', 'Boli', 'Global', 'Boli'),
    ('chata', 'chat_apps', 'chata', 'CHATA', 'Global', 'CHATA'),
    ('chati', 'chat_apps', 'chati', 'CHATI', 'Global', 'CHATI'),
    ('chillchat', 'chat_apps', 'chillchat', 'ChillChat', 'Global', 'ChillChat'),
)

BITTOPUP_INDEX_BY_SLUG: dict[str, dict[str, str]] = {
    slug: {
        "slug": slug,
        "url": f"{BITTOPUP_BASE_URL}/goods/{slug}",
        "service_key": service_key,
        "family_key": family_key,
        "family_label": family_label,
        "region": region,
        "product_name": product_name,
    }
    for slug, service_key, family_key, family_label, region, product_name in BITTOPUP_INDEX_ROWS
}


def bittopup_indexed_urls() -> list[str]:
    return [row["url"] for row in BITTOPUP_INDEX_BY_SLUG.values()]


def bittopup_index_metadata_for_url(url: str) -> dict[str, str] | None:
    slug = urlparse(str(url or "")).path.strip("/").split("/")[-1]
    if not slug:
        return None
    return BITTOPUP_INDEX_BY_SLUG.get(slug)
