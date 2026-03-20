import aiohttp
import asyncio
import json
import os
import pprint
import re
from difflib import SequenceMatcher

from dotenv import load_dotenv

# ==============================
# CONFIG
# ==============================

ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

DATA_DIR = "../data"

SMSPOOL_KEY = (os.getenv("SMSPOOL_KEY") or "").strip()
TELABOT_KEY = (os.getenv("TELABOT_KEY") or "").strip()
TELABOT_USER = (os.getenv("TELABOT_USER") or "").strip()
TEXTVERIFIED_KEY = (os.getenv("TV_KEY") or os.getenv("TEXTVERIFIED_KEY") or "").strip()
TEXTVERIFIED_USER = (os.getenv("TV_USER") or os.getenv("TEXTVERIFIED_USER") or "").strip()
HEROSMS_KEY = (os.getenv("HEROSMS_KEY") or "").strip()
HEROSMS_BASE_URL = (os.getenv("HEROSMS_BASE_URL") or "https://hero-sms.com/stubs/handler_api.php").strip()


def _assert_required_env() -> None:
    missing = []
    if not SMSPOOL_KEY:
        missing.append("SMSPOOL_KEY")
    if not TELABOT_USER:
        missing.append("TELABOT_USER")
    if not TELABOT_KEY:
        missing.append("TELABOT_KEY")
    if not TEXTVERIFIED_USER:
        missing.append("TV_USER (or TEXTVERIFIED_USER)")
    if not TEXTVERIFIED_KEY:
        missing.append("TV_KEY (or TEXTVERIFIED_KEY)")
    if missing:
        raise RuntimeError(f"Missing required env keys: {', '.join(missing)}")


# ==============================
# NORMALIZER
# ==============================

def normalize(name: str) -> str:
    return (
        str(name or "")
        .lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
        .replace(".", "")
        .replace("(", "")
        .replace(")", "")
        .replace("[", "")
        .replace("]", "")
        .replace("&", "")
        .strip()
    )


# ==============================
# GENERIC FETCH
# ==============================

async def fetch_json(session, url, method="GET", **kwargs):
    try:
        async with session.request(method, url, **kwargs) as resp:
            text = await resp.text()

            if resp.status != 200:
                print(f"HTTP {resp.status} -> {url}")
                print("RESPONSE:", text)
                return None

            try:
                return json.loads(text)
            except Exception:
                print(f"Invalid JSON from {url}")
                return None

    except Exception as e:
        print(f"Request failed: {e}")
        return None


# ==============================
# SMSpool
# ==============================

async def get_smspool_services(session):
    url = "https://api.smspool.net/request/services"
    params = {"key": SMSPOOL_KEY}
    return await fetch_json(session, url, params=params)


# ==============================
# Telabot
# ==============================

async def get_telabot_services(session):
    url = "https://www.tellabot.com/api_command.php"
    params = {
        "cmd": "list_services",
        "user": TELABOT_USER,
        "api_key": TELABOT_KEY,
    }
    return await fetch_json(session, url, params=params)


# ==============================
# TextVerified
# ==============================

async def get_textverified_token(session):
    url = "https://www.textverified.com/api/pub/v2/auth"

    headers = {
        "X-API-USERNAME": TEXTVERIFIED_USER,
        "X-API-KEY": TEXTVERIFIED_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    async with session.post(url, headers=headers, json={}) as resp:
        text = await resp.text()

        if resp.status != 200:
            print("TextVerified AUTH ERROR:", text)
            return None

        data = json.loads(text)
        return data.get("token")


async def get_textverified_services(session, token):
    url = "https://www.textverified.com/api/pub/v2/services"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    params = {
        "reservationType": "verification",
        "numberType": "mobile",
    }

    return await fetch_json(session, url, headers=headers, params=params)


# ==============================
# HeroSMS
# ==============================

async def get_herosms_services(session):
    if not HEROSMS_KEY:
        return []
    params = {"action": "getServicesList", "api_key": HEROSMS_KEY}
    data = await fetch_json(session, HEROSMS_BASE_URL, params=params)
    if isinstance(data, dict) and isinstance(data.get("services"), list):
        return data.get("services")
    return []


# ==============================
# HYBRID MATCHING
# ==============================

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def hybrid_match(name, provider_dict):
    """Strict then fuzzy match."""
    norm = normalize(name)

    if norm in provider_dict:
        return provider_dict[norm]

    best_match = None
    best_score = 0

    for key in provider_dict:
        score = similarity(norm, key)
        if score > best_score:
            best_score = score
            best_match = key

    if best_score >= 0.85 and best_match is not None:
        return provider_dict[best_match]

    return None


# ==============================
# BUILD FULL SERVICE MAP
# ==============================

def build_full_map(smspool, telabot, textverified, herosms):
    full_map = {}

    smspool_norm = {normalize(k): v for k, v in smspool.items()}
    telabot_norm = {normalize(k): v for k, v in telabot.items()}
    textverified_norm = {normalize(k): v for k, v in textverified.items()}
    herosms_norm = {normalize(k): v for k, v in herosms.items()}

    all_services = set(smspool_norm.keys()) | set(telabot_norm.keys()) | set(textverified_norm.keys()) | set(herosms_norm.keys())

    for service in all_services:
        entry = {"providers": {}}

        if service in smspool_norm:
            entry["providers"]["smspool"] = smspool_norm[service]

        match_telabot = hybrid_match(service, telabot_norm)
        if match_telabot:
            entry["providers"]["telabot"] = match_telabot

        match_tv = hybrid_match(service, textverified_norm)
        if match_tv:
            entry["providers"]["textverified"] = match_tv

        match_hs = hybrid_match(service, herosms_norm)
        if match_hs:
            entry["providers"]["herosms"] = match_hs

        full_map[service] = entry

    return full_map


# ==============================
# MAIN UPDATE FUNCTION
# ==============================

async def update_services():
    _assert_required_env()
    print("Fetching provider services...\n")

    os.makedirs(DATA_DIR, exist_ok=True)

    async with aiohttp.ClientSession() as session:
        token = await get_textverified_token(session)

        smspool_raw, telabot_raw, textverified_raw, herosms_raw = await asyncio.gather(
            get_smspool_services(session),
            get_telabot_services(session),
            get_textverified_services(session, token) if token else asyncio.sleep(0, result=None),
            get_herosms_services(session),
        )

    smspool_raw = smspool_raw if isinstance(smspool_raw, list) else []
    telabot_raw = telabot_raw if isinstance(telabot_raw, dict) else {}
    textverified_raw = textverified_raw if isinstance(textverified_raw, list) else []
    herosms_raw = herosms_raw if isinstance(herosms_raw, list) else []

    with open(f"{DATA_DIR}/smspool_services.json", "w", encoding="utf-8") as f:
        json.dump(smspool_raw, f, indent=2, ensure_ascii=False)

    with open(f"{DATA_DIR}/telabot_services.json", "w", encoding="utf-8") as f:
        json.dump(telabot_raw, f, indent=2, ensure_ascii=False)

    with open(f"{DATA_DIR}/textverified_services.json", "w", encoding="utf-8") as f:
        json.dump(textverified_raw, f, indent=2, ensure_ascii=False)
    with open(f"{DATA_DIR}/herosms_services.json", "w", encoding="utf-8") as f:
        json.dump(herosms_raw, f, indent=2, ensure_ascii=False)

    print("Raw provider files saved.")

    for name, data in [
        ("smspool_services", smspool_raw),
        ("telabot_services", telabot_raw),
        ("textverified_services", textverified_raw),
        ("herosms_services", herosms_raw),
    ]:
        py_path = os.path.join(DATA_DIR, f"{name}.py")
        with open(py_path, "w", encoding="utf-8") as pyf:
            pyf.write(f"# Auto-generated from {name}.json\n")
            pyf.write("DATA = ")
            pyf.write(pprint.pformat(data, width=120, compact=False))
            pyf.write("\n")

    try:
        with open(f"{DATA_DIR}/service_map.json", "r", encoding="utf-8") as f:
            service_map_raw = json.load(f)
        with open(f"{DATA_DIR}/service_map.py", "w", encoding="utf-8") as pyf:
            pyf.write("# Auto-generated from service_map.json\n")
            pyf.write("DATA = ")
            pyf.write(pprint.pformat(service_map_raw, width=120, compact=False))
            pyf.write("\n")
    except FileNotFoundError:
        pass

    print("Python modules generated.")

    smspool_dict = {normalize(item.get("name", "")): item.get("ID") for item in smspool_raw if item.get("name")}
    telabot_dict = {normalize(k): v for k, v in telabot_raw.items()}
    textverified_dict = {
        normalize(item.get("serviceName", "")): item.get("serviceName")
        for item in textverified_raw
        if item.get("serviceName")
    }

    def _herosms_aliases(name: str) -> set[str]:
        aliases = {normalize(name)}
        parts = re.split(r"[,\+/\|\;\(\)\[\]\-]", str(name or ""))
        for part in parts:
            token = normalize(part)
            if token and len(token) >= 4:
                aliases.add(token)
        return aliases

    herosms_dict = {}
    for item in herosms_raw:
        code = str(item.get("code") or "").strip()
        name = str(item.get("name") or "").strip()
        if not code or not name:
            continue
        for alias in _herosms_aliases(name):
            herosms_dict[alias] = code

    full_map = build_full_map(smspool_dict, telabot_dict, textverified_dict, herosms_dict)

    with open(f"{DATA_DIR}/full_service_map.json", "w", encoding="utf-8") as f:
        json.dump(full_map, f, indent=2, ensure_ascii=False)

    print("full_service_map.json generated successfully!")


# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    asyncio.run(update_services())
