"""One-time fetch of catalog thumbnail images into the local web assets folder.

Pulls a square thumbnail per catalog family (games + chat apps) and writes it to
webapp/auth/img/<section>/<slug>.png. The storefront renders
/auth/static/img/<section>/<slug>.png and falls back to a monogram tile when a
file is missing, so it is safe to run for as few or as many families as you like.

Sources, in priority order:
  1. SteamGridDB (best art) — needs a free key:  set STEAMGRIDDB_KEY env.
     Get one at https://www.steamgriddb.com/profile/preferences/api
  2. Wikipedia page images (no key) — fallback.

The search term for each family is derived from its slug ("free_fire" ->
"free fire"); override a few in SEARCH_OVERRIDES when the derived name misses.
Every image is normalized to PNG (the site sends X-Content-Type-Options:
nosniff): transparent logos go on a light plate, opaque art is square-cropped.

Run:  STEAMGRIDDB_KEY=xxxx python scripts/fetch_game_images.py
Refresh the SLUGS lists from the live catalog (/api/v1/catalog) when families
change.
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

IMG_ROOT = Path(__file__).resolve().parents[1] / "webapp" / "auth" / "img"
WIKI_API = "https://en.wikipedia.org/w/api.php"
SGDB_API = "https://www.steamgriddb.com/api/v2"
UA = "PhantomCatalogImageFetcher/1.0 (https://phantom-app.net)"
MAX_SIDE = 360
STEAMGRIDDB_KEY = os.environ.get("STEAMGRIDDB_KEY", "").strip()
G2BULK_KEY = os.environ.get("G2BULK_KEY", "").strip()
G2BULK_BASE = os.environ.get("G2BULK_BASE", "https://api.g2bulk.com").rstrip("/")
# Skip a family when its image already exists, so a re-run only fills gaps and
# never overwrites art that is already in place.
SKIP_EXISTING = os.environ.get("REFETCH_ALL", "").strip() not in ("1", "true", "yes")
_G2_GAMES: list[tuple[str, str]] | None = None


def _slugify(name: str) -> str:
    import re
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(name).lower())).strip("_")


def _g2bulk_games() -> list[tuple[str, str]]:
    """G2Bulk's own game catalogue images, as (slugified-name, image_url)."""
    global _G2_GAMES
    if _G2_GAMES is not None:
        return _G2_GAMES
    _G2_GAMES = []
    if not G2BULK_KEY:
        return _G2_GAMES
    try:
        req = urllib.request.Request(G2BULK_BASE + "/v1/games", headers={"x-api-key": G2BULK_KEY, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            games = json.loads(resp.read().decode("utf-8")).get("games") or []
        _G2_GAMES = [(_slugify(g.get("name") or ""), g.get("image_url")) for g in games if g.get("image_url")]
    except Exception as exc:
        print("[warn] G2Bulk games fetch failed:", str(exc)[:80])
    return _G2_GAMES


def _g2bulk_thumb(slug: str) -> str | None:
    """Match our family slug to a G2Bulk game (exact, then word-boundary prefix)."""
    games = _g2bulk_games()
    for g2slug, url in games:
        if g2slug == slug:
            return url
    for g2slug, url in games:
        if g2slug.startswith(slug + "_") or slug.startswith(g2slug + "_"):
            return url
    return None

SEARCH_OVERRIDES = {
    "pubg": "PUBG Battlegrounds",
    "eafc_24": "EA Sports FC 24",
    "eafc_mobile": "EA Sports FC Mobile",
    "call_of_duty": "Call of Duty Mobile",
    "free_fire": "Garena Free Fire",
    "wild_rift": "League of Legends Wild Rift",
}

SLUGS: dict[str, list[str]] = {
    "games": [
        "pubg", "free_fire", "mobile_legends", "mobile_legends_adventure", "league_of_legends",
        "legends_of_runeterra", "valorant", "call_of_duty", "clash_of_clans", "honor_of_kings",
        "genshin_impact", "delta_force", "blood_strike", "brawl_stars", "whiteout_survival",
        "war_robots", "yalla_ludo", "jawaker", "eafc_mobile", "eafc_24", "lords_mobile", "super_sus",
        "8_ball_pool", "fortnite", "we_play", "revenge_of_the_sultans", "waki_star",
        "legend_of_neverland", "legend_of_the_phoenix", "solo_leveling_arise", "etheria_restart",
        "honkai_star_rail", "zenless_zone_zero", "racing_master", "dragonheir_silent_gods",
        "devil_may_cry_peak_of_combat", "bleach_soul_resonance", "frag_pro_shooter",
        "lord_of_the_rings_rise_to_war", "bullet_echo", "ghost_story_love_destiny", "knives_out",
        "tarisland", "pixel_gun_3d", "cats_crash_arena_turbo_stars", "revelation_infinite_journey",
        "dunk_city_dynasty", "age_of_empire_mobile", "wild_rift", "undawn", "star_resonance",
        "sword_of_justice", "rainbow_six_mobile", "harry_potter_magic_awaken", "once_human",
        "eggy_party", "haikyu_fly_high", "age_of_magic", "enhypen_world", "ragnarok_origin",
        "path_to_nowhere", "sky_children_of_the_light", "moonlight_blade_m", "punishing_gray_raven",
        "crossfire_legend", "love_nikki", "arknight_endfield", "identity_v", "shining_nikki",
        "honkai_impact_3rd", "acecraft", "farlight_84", "spring_valley", "ragnarok_idle_adventure_plus",
        "black_clover_m", "arena_breakout", "oxide_survival_island", "watcher_of_realms", "heartopia",
        "free_fire_memberships", "teen_patti_gold", "kings_choice", "metal_slug_awakening",
        "dragon_nest_m_classic", "lifeafter", "where_winds_meet", "ragnarok_crush", "ragnarok_x",
        "growtopia", "marvel_mystic_mayhem", "state_of_survival", "love_and_deepspace", "blockman_go",
        "hero_clash", "dragon_raja", "silver_and_blood", "crossout_mobile", "crystal_of_atlan",
        "afk_journey", "sausage_man", "life_makeover", "hatsune_miku", "eve_echoes",
        "heaven_burns_red", "t3_arena", "echocalypse_scarlet_covenant", "project_entropy",
        "civilization_eras_allies", "deadly_dudes", "rememento_white_shadows", "marvel_duel",
        "mecha_break", "duet_night_abyss", "onmyoji_arena", "arena_of_valor", "destiny_rising",
        "stumble_guys", "wuthering_waves", "maplestory_m", "snowbreak_containment_zone",
        "marvel_rivals", "my_singing_monsters", "asphalt_9_legends", "kingshot", "azur_lane",
        "stormshot", "tiles_survive", "sea_of_conquest",
    ],
    "chat-apps": [
        "starmaker", "zepeto", "honey_jar", "party_star", "soul_shell", "soul_star",
        "discord", "imo", "telegram",
    ],
}


def _search_name(slug: str) -> str:
    return SEARCH_OVERRIDES.get(slug) or slug.replace("_", " ")


def _wiki_thumb(name: str) -> str | None:
    params = {
        "action": "query", "titles": name, "prop": "pageimages", "piprop": "thumbnail",
        "pithumbsize": "480", "pilicense": "any", "format": "json", "redirects": "1",
    }
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for page in ((data.get("query") or {}).get("pages") or {}).values():
        thumb = (page.get("thumbnail") or {}).get("source")
        if thumb:
            return thumb
    return None


def _sgdb_thumb(name: str) -> str | None:
    if not STEAMGRIDDB_KEY:
        return None
    headers = {"User-Agent": UA, "Authorization": "Bearer " + STEAMGRIDDB_KEY}
    search = SGDB_API + "/search/autocomplete/" + urllib.parse.quote(name)
    with urllib.request.urlopen(urllib.request.Request(search, headers=headers), timeout=20) as resp:
        found = json.loads(resp.read().decode("utf-8")).get("data") or []
    if not found:
        return None
    game_id = found[0].get("id")
    for kind in ("grids", "logos", "icons"):
        try:
            u = f"{SGDB_API}/{kind}/game/{game_id}"
            with urllib.request.urlopen(urllib.request.Request(u, headers=headers), timeout=20) as resp:
                items = json.loads(resp.read().decode("utf-8")).get("data") or []
            if items:
                return items[0].get("url")
        except Exception:
            continue
    return None


def _save_png(img_url: str, dest: Path) -> None:
    with urllib.request.urlopen(urllib.request.Request(img_url, headers={"User-Agent": UA}), timeout=25) as resp:
        raw = resp.read()
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    size = MAX_SIDE
    if img.getchannel("A").getextrema()[0] < 250:
        canvas = Image.new("RGBA", (size, size), (241, 243, 248, 255))
        pad = int(size * 0.16)
        scaled = img.copy()
        scaled.thumbnail((size - 2 * pad, size - 2 * pad), Image.LANCZOS)
        canvas.alpha_composite(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2))
    else:
        canvas = ImageOps.fit(img, (size, size), method=Image.LANCZOS, centering=(0.5, 0.4)).convert("RGBA")
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, format="PNG", optimize=True)


def main() -> int:
    ok, miss = 0, []
    for section, slugs in SLUGS.items():
        out_dir = IMG_ROOT / section
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n== {section} ({len(slugs)}) ==")
        for slug in slugs:
            dest = out_dir / f"{slug}.png"
            if SKIP_EXISTING and dest.exists():
                continue
            name = _search_name(slug)
            try:
                src = _g2bulk_thumb(slug) or _sgdb_thumb(name) or _wiki_thumb(name)
                if not src:
                    miss.append(f"{section}/{slug}")
                    continue
                _save_png(src, out_dir / f"{slug}.png")
                ok += 1
                print(f"[ok]   {slug}")
            except Exception as exc:
                miss.append(f"{section}/{slug}")
                print(f"[skip] {slug:<28} {str(exc)[:60]}")
    print(f"\nDone: {ok} saved, {len(miss)} skipped -> {IMG_ROOT}")
    print("Skipped:", ", ".join(miss) if miss else "none")
    print("SteamGridDB:", "enabled" if STEAMGRIDDB_KEY else "off (set STEAMGRIDDB_KEY)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
