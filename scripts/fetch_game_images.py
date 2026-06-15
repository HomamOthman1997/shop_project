"""One-time fetch of catalog thumbnail images into the local web assets folder.

Pulls a square thumbnail per catalog family (games + chat apps) and writes it to
webapp/auth/img/<section>/<slug>.png. The storefront renders
/auth/static/img/<section>/<slug>.png and falls back to a monogram tile when a
file is missing, so it is safe to run for as few or as many families as you like.

Sources, in priority order:
  1. SteamGridDB (best art) — only if a key is provided:  set STEAMGRIDDB_KEY env.
     Get a free key at https://www.steamgriddb.com/profile/preferences/api
  2. Wikipedia page images (no key) — used as the fallback / default.

Every image is normalized to PNG (the site sends X-Content-Type-Options: nosniff,
so extension/MIME must match): transparent logos go on a light plate, opaque box
art is center-cropped to a square.

Run:  python scripts/fetch_game_images.py
Add families by extending SECTIONS[...]["titles"] with: catalog family slug -> a
search title (Wikipedia article title / game name).
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

SECTIONS: dict[str, dict[str, str]] = {
    "games": {
        "pubg": "PUBG: Battlegrounds",
        "free_fire": "Free Fire (video game)",
        "mobile_legends": "Mobile Legends: Bang Bang",
        "mobile_legends_adventure": "Mobile Legends: Bang Bang",
        "league_of_legends": "League of Legends",
        "legends_of_runeterra": "Legends of Runeterra",
        "valorant": "Valorant",
        "call_of_duty": "Call of Duty: Mobile",
        "clash_of_clans": "Clash of Clans",
        "clash_royale": "Clash Royale",
        "honor_of_kings": "Honor of Kings",
        "genshin_impact": "Genshin Impact",
        "honkai_star_rail": "Honkai: Star Rail",
        "zenless_zone_zero": "Zenless Zone Zero",
        "brawl_stars": "Brawl Stars",
        "fortnite": "Fortnite",
        "8_ball_pool": "8 Ball Pool (video game)",
        "lords_mobile": "Lords Mobile",
        "war_robots": "War Robots",
        "solo_leveling_arise": "Solo Leveling: Arise",
        "delta_force": "Delta Force (video game)",
        "eafc_mobile": "EA Sports FC Mobile",
        "eafc_24": "EA Sports FC 24",
        "roblox": "Roblox",
    },
    "chat-apps": {
        "discord": "Discord",
        "bigo_live": "Bigo Live",
        "likee": "Likee",
        "tango": "Tango (application)",
        "imo": "Imo (software)",
        "nimo_tv": "Nimo TV",
        "tiktok": "TikTok",
        "telegram": "Telegram (software)",
        "soul_chill": "",
        "poppo_live": "",
        "chamet": "",
        "yoho": "",
        "sugo": "",
    },
}


def _wiki_thumb(title: str) -> str | None:
    if not title:
        return None
    params = {
        "action": "query", "titles": title, "prop": "pageimages",
        "piprop": "thumbnail", "pithumbsize": "480", "pilicense": "any",
        "format": "json", "redirects": "1",
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
    if not STEAMGRIDDB_KEY or not name:
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
    total_ok, total_miss = 0, []
    for section, titles in SECTIONS.items():
        out_dir = IMG_ROOT / section
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n== {section} ==")
        for slug, title in titles.items():
            try:
                src = _sgdb_thumb(title) or _wiki_thumb(title)
                if not src:
                    total_miss.append(f"{section}/{slug}")
                    print(f"[skip] {slug:<26} (no image)")
                    continue
                _save_png(src, out_dir / f"{slug}.png")
                total_ok += 1
                print(f"[ok]   {slug:<26} <- {title}")
            except Exception as exc:
                total_miss.append(f"{section}/{slug}")
                print(f"[skip] {slug:<26} {str(exc)[:70]}")
    print(f"\nDone: {total_ok} saved, {len(total_miss)} skipped -> {IMG_ROOT}")
    if total_miss:
        print("Skipped:", ", ".join(total_miss))
    print("SteamGridDB:", "enabled" if STEAMGRIDDB_KEY else "off (set STEAMGRIDDB_KEY for better coverage)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
