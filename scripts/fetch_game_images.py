"""One-time fetch of game thumbnail images into the local web assets folder.

Uses the Wikipedia page-image API (no API key) for a curated set of popular
games, normalizes every image to PNG (the site sends `X-Content-Type-Options:
nosniff`, so the file extension/MIME must match the real bytes), and writes them
to webapp/auth/img/games/<slug>.png. The customer storefront renders
/auth/static/img/games/<slug>.png and falls back to the accent mark when a file
is missing, so it is safe to run this for as few or as many games as you like.

Run:  python scripts/fetch_game_images.py
Add more games by extending SLUG_TITLES with the catalog family slug -> a
Wikipedia article title.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

OUT_DIR = Path(__file__).resolve().parents[1] / "webapp" / "auth" / "img" / "games"
WIKI_API = "https://en.wikipedia.org/w/api.php"
UA = "PhantomCatalogImageFetcher/1.0 (https://phantom-app.net)"
MAX_SIDE = 360

# catalog family slug -> Wikipedia article title (curated for confident matches)
SLUG_TITLES: dict[str, str] = {
    "pubg": "PUBG: Battlegrounds",
    "free_fire": "Garena Free Fire",
    "mobile_legends": "Mobile Legends: Bang Bang",
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
    "yalla_ludo": "Yalla Ludo",
    "super_sus": "Super Sus",
    "blood_strike": "Blood Strike (video game)",
    "whiteout_survival": "Whiteout Survival",
}


def _wiki_thumb(title: str) -> str | None:
    params = {
        "action": "query",
        "titles": title,
        "prop": "pageimages",
        "piprop": "thumbnail",
        "pithumbsize": "480",
        "pilicense": "any",
        "format": "json",
        "redirects": "1",
    }
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        thumb = (page.get("thumbnail") or {}).get("source")
        if thumb:
            return thumb
    return None


def _download_png(img_url: str, dest: Path) -> bool:
    req = urllib.request.Request(img_url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    size = MAX_SIDE
    transparent = img.getchannel("A").getextrema()[0] < 250
    if transparent:
        # Logo on transparent bg: place on a light plate (dark logos stay visible)
        # and fit with padding so it isn't cropped.
        canvas = Image.new("RGBA", (size, size), (241, 243, 248, 255))
        pad = int(size * 0.16)
        scaled = img.copy()
        scaled.thumbnail((size - 2 * pad, size - 2 * pad), Image.LANCZOS)
        canvas.alpha_composite(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2))
    else:
        # Opaque box art / icon: fill the square (center-crop, biased slightly up).
        canvas = ImageOps.fit(img, (size, size), method=Image.LANCZOS, centering=(0.5, 0.4)).convert("RGBA")
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, format="PNG", optimize=True)
    return True


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok, miss = [], []
    for slug, title in SLUG_TITLES.items():
        try:
            thumb = _wiki_thumb(title)
            if not thumb:
                miss.append((slug, "no image"))
                continue
            _download_png(thumb, OUT_DIR / f"{slug}.png")
            ok.append(slug)
            print(f"[ok]   {slug:<24} <- {title}")
        except Exception as exc:  # keep going; missing images degrade gracefully
            miss.append((slug, str(exc)[:80]))
            print(f"[skip] {slug:<24} {exc}")
    print(f"\nDone: {len(ok)} saved, {len(miss)} skipped -> {OUT_DIR}")
    if miss:
        print("Skipped:", ", ".join(s for s, _ in miss))
    return 0


if __name__ == "__main__":
    sys.exit(main())
