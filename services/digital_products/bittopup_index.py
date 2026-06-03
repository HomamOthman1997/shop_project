from __future__ import annotations

from urllib.parse import urlparse

BITTOPUP_BASE_URL = "https://bittopup.com"

# Curated from the operator-reviewed BitTopup sheet. These are the only
# BitTopup product pages we scan for now.
BITTOPUP_INDEX_ROWS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("Likee-Gift-Card", "chat_apps", "likee", "Likee", "Global", "Likee Gift Card"),
    ("imo-diamond-recharge", "chat_apps", "imo", "IMO", "Global", "IMO Diamond Recharge"),
    ("Discord-Nitro-Subscription", "chat_apps", "discord", "Discord", "Global", "Discord Nitro Subscription"),
    ("MICO-Live-Coins-MENA", "chat_apps", "mico_live", "Mico Live", "Global", "MICO Live Coins (MENA)"),
    ("mico-live-coins", "chat_apps", "mico_live", "Mico Live", "Global", "MICO Live Coins"),
    ("MIKA-Chat-Coins", "chat_apps", "mika_chat_coins", "Mika Chat Coins", "Global", "MIKA Chat Coins"),
    ("Likee-Diamond", "chat_apps", "likee", "Likee", "Global", "Likee"),
    ("bigo-live-diamonds", "chat_apps", "bigo_live", "Bigo Live", "Global", "Bigo Recharge"),
    ("Nimo-TV-Diamonds", "chat_apps", "nimo_tv", "Nimo TV", "Global", "Nimo TV Diamonds"),
    ("Kuaishou-Kwai-CN-Coin", "chat_apps", "kwai", "Kwai", "Global", "Kuaishou Kwai (CN) Coin"),
    ("Poppo-Live-Coins", "chat_apps", "poppo_live", "Poppo Live", "Global", "Poppo Live Coins"),
    ("soulchill", "chat_apps", "soul_chill", "Soul Chill", "Global", "Soul Chill"),
    ("sugovoice-chat-party-top-up", "chat_apps", "sugo_voice", "SUGO Voice", "Global", "SUGO Recharge"),
    ("chamet", "chat_apps", "chamet", "Chamet", "Global", "Chamet Recharge"),
    ("xena-live", "chat_apps", "xena_live", "Xena Live", "Global", "Xena Live"),
    ("yoho-group-voice-chat", "chat_apps", "yoho_group_voice_chat", "YoHo Group Voice Chat", "Global", "YoHo: Group Voice Chat"),
    ("yoyo", "chat_apps", "yoyo_live", "Yoyo Live", "Global", "Yoyo Live"),
    ("migo-live", "chat_apps", "migo_live", "Migo Live", "Global", "Migo Live"),
    ("tango-coins", "chat_apps", "tango", "Tango", "Global", "Tango Coins Recharge"),
    ("1star-chat", "chat_apps", "1star_chat", "1Star Chat", "Global", "1Star Chat"),
    ("4chat", "chat_apps", "4chat", "4CHAT", "Global", "4CHAT"),
    ("amo-chat", "chat_apps", "amo_chat", "Amo Chat", "Global", "Amo Chat"),
    ("azal", "chat_apps", "azal_live", "Azal Live", "Global", "Azal"),
    ("boli", "chat_apps", "boli", "Boli", "Global", "Boli"),
    ("chata", "chat_apps", "chata", "CHATA", "Global", "CHATA"),
    ("chati", "chat_apps", "chati", "CHATI", "Global", "CHATI"),
    ("chillchat", "chat_apps", "chillchat", "ChillChat", "Global", "ChillChat"),
    ("Free-Fire-Diamonds-EU-+-TR", "games", "free_fire", "Free Fire", "EU", "Free Fire Diamonds EU + TR"),
    ("Jawaker-Voucher", "games", "jawaker", "Jawaker", "Global", "Jawaker Voucher"),
    ("Knives-Out-PIN", "games", "knives_out", "Knives Out", "Global", "Knives Out PIN"),
    ("Lords-Mobile-Diamonds-Global", "games", "lords_mobile", "Lords Mobile", "Global", "Lords Mobile Diamonds"),
    ("FINAL-FANTASY-XIV-Online", "games", "final_fantasy_xiv_online", "Final Fantasy XIV Online", "EU", "FINAL FANTASY XIV Online"),
    ("Teen-Patti-Gold-Gift-Card", "games", "teen_patti_gold", "Teen Patti Gold", "Global", "Teen Patti Gold Gift Card"),
    ("Free-Fire-Diamonds", "games", "free_fire", "Free Fire", "Global", "Free Fire Diamonds"),
    ("pubg-uc", "games", "pubg", "PUBG", "Global", "PUBG UC Top Up"),
    ("mlbb-diamonds", "games", "mobile_legends", "Mobile Legends", "Global", "Mobile Legends Bang Bang"),
    ("identity-v-echoes", "games", "identity_v", "Identity V", "Global", "Identity V Top Up"),
    ("Yalla-Ludo-Diamonds", "games", "yalla_ludo", "Yalla Ludo", "Global", "Yalla Ludo Global"),
    ("Knives-Out-Vouchers", "games", "knives_out", "Knives Out", "Global", "Knives Out Vouchers"),
    ("Arena-Breakout-Pass-&-Packages", "games", "arena_breakout", "Arena Breakout", "Global", "Arena Breakout Pass & Packages"),
    ("Arena-Breakout-Bonds", "games", "arena_breakout", "Arena Breakout", "Global", "Arena Breakout Bonds"),
    ("Sausage-Man-Candies", "games", "sausage_man", "Sausage Man", "Global", "Sausage Man Candies"),
    ("Honor-of-Kings-Tokens-Global", "games", "honor_of_kings", "Honor of Kings", "Global", "Honor of Kings Top Up"),
    ("Onmyoji-Arena", "games", "onmyoji_arena", "Onmyoji Arena", "Global", "Onmyoji Arena"),
    ("New-State-Mobile-NC", "games", "new_state", "New State Mobile", "Global", "New State Mobile NC"),
    ("Eggy-Party-Eggy-Coins", "games", "eggy_party", "Eggy Party", "Global", "Eggy Party Eggy Coins"),
    ("Super-Sus-Who-Is-The-Impostor-Golden-Star", "games", "super_sus", "Super SUS", "Global", "Super Sus -Who Is The Impostor Golden Star"),
    ("Blood-Strike-Golds", "games", "blood_strike", "Blood Strike", "Global", "Blood Strike Top Up"),
    ("Blood-Strike-Pass", "games", "blood_strike", "Blood Strike", "MENA", "Blood Strike (MENA)"),
    ("goddess-of-victory-nikke", "games", "goddess_of_victory_nikke", "Goddess of Victory NIKKE", "Global", "Goddess of Victory NIKKE"),
    ("MapleStory-M-Package", "games", "maplestory_m", "MapleStory M", "Global", "MapleStory M Package"),
    ("MapleStory-M-Crystal", "games", "maplestory_m", "MapleStory M", "Global", "MapleStory M Crystal"),
    ("Hero-Clash-Red-Diamonds", "games", "hero_clash", "Hero Clash", "Global", "Hero Clash Red Diamonds"),
    ("ZEPETO-ZEMs-&-Coins", "games", "zepeto", "ZEPETO", "Global", "ZEPETO ZEMs & Coins"),
    ("Dunk-City-Dynasty-Tokens", "games", "dunk_city_dynasty", "Dunk City Dynasty", "Global", "Dunk City Dynasty"),
    ("Life-MakeOver-Coupons-Global", "games", "life_makeover", "Life MakeOver", "Global", "Life MakeOver Coupons Global"),
    ("Life-MakeOver-Package-Global", "games", "life_makeover", "Life MakeOver", "Global", "Life MakeOver Package Global"),
    ("bleach-soul-resonance", "games", "bleach_soul_resonance", "BLEACH: Soul Resonance", "Global", "BLEACH: Soul Resonance"),
    ("Farlight-84-Diamonds", "games", "farlight_84", "Farlight 84", "Global", "Farlight 84 Diamonds"),
    ("Black-Clover-M-Summon-Pack-ASIA", "games", "black_clover_m", "Black Clover M", "ASIA", "Black Clover M Summon Pack - ASIA"),
    ("Black-Clover-M-Premium-Black-Crystals-ASIA", "games", "black_clover_m", "Black Clover M", "ASIA", "Black Clover M Premium Black Crystals - ASIA"),
    ("LifeAfter-Night-falls-Credits-EU", "games", "lifeafter", "LifeAfter", "EU", "LifeAfter"),
    ("StarMaker-Sing-Karaoke-Coins", "games", "starmaker", "StarMaker", "Global", "StarMaker Coins (Gold)"),
    ("Palworld-Game-account", "games", "palworld", "Palworld", "Global", "Palworld Game account"),
    ("pubg-gcoin", "games", "pubg", "PUBG", "Global", "PUBG G-COIN CDK"),
    ("zenless-zone-zero", "games", "zenless_zone_zero", "Zenless Zone Zero", "Global", "ZZZ Top Up"),
    ("whiteout-survival-frost-star", "games", "whiteout_survival", "Whiteout Survival", "Global", "Whiteout Survival Top Up"),
    ("delta-force", "games", "delta_force", "Delta Force", "Global", "Delta Force Top Up"),
    ("wuthering-waves", "games", "wuthering_waves", "Wuthering Waves", "Global", "Wuthering Waves Top Up"),
    ("crystal-of-atlan-asia-top-up", "games", "crystal_of_atlan", "Crystal of Atlan", "ASIA", "Crystal of Atlan Asia Top Up"),
    ("mecha-break", "games", "mecha_break", "Mecha BREAK", "Global", "Mecha BREAK"),
    ("ragnarok-crush", "games", "ragnarok_crush", "Ragnarok Crush", "Global", "Ragnarok Crush"),
    ("punishing-gray-raven-rainbow-cards", "games", "punishing_gray_raven", "Punishing Gray Raven", "Global", "Punishing Gray Raven Rainbow Cards"),
    ("pixel-gun-3d", "games", "pixel_gun_3d", "Pixel Gun 3D", "Global", "Pixel Gun 3D"),
    ("path-to-nowhere", "games", "path_to_nowhere", "Path to Nowhere", "Global", "Path to Nowhere"),
    ("afk-journey", "games", "afk_journey", "AFK Journey", "Global", "AFK Journey"),
    ("state-of-survival", "games", "state_of_survival", "State of Survival", "Global", "State of Survival"),
    ("garena-delta-force-mena", "games", "delta_force", "Delta Force", "MENA", "Garena Delta Force MENA"),
    ("racing-master-hmt", "games", "racing_master", "Racing Master", "Global", "Racing Master Global"),
    ("garena-free-fire-global", "games", "free_fire", "Free Fire", "Global", "Garena Free Fire Pins Global"),
    ("watcher-of-realms", "games", "watcher_of_realms", "Watcher of Realms", "Global", "Watcher of Realms"),
    ("mobile-legends-adventure-mcash", "games", "mobile_legends_adventure", "Mobile Legends Adventure", "Global", "Mobile Legends: Adventure M-Cash"),
    ("where-winds-meet", "games", "where_winds_meet", "Where Winds Meet", "Global", "Where Winds Meet Top Up"),
    ("once-human-top-up", "games", "once_human", "Once Human", "Global", "Once Human Top Up"),
    ("kingshot", "games", "kingshot", "Kingshot", "Global", "Kingshot"),
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
