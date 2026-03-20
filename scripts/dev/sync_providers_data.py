import asyncio
import aiohttp
import json
import os

from dotenv import load_dotenv

ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "."))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

SMSPOOL_KEY = (os.getenv("SMSPOOL_KEY") or "").strip()
DATA_DIR = "shop_project/services/numbers/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)


def _assert_required_env() -> None:
    if not SMSPOOL_KEY:
        raise RuntimeError("Missing required env key: SMSPOOL_KEY")


async def fetch_available_countries():
    print("Fetching countries from SMSPool...")
    url = "https://api.smspool.net/country/retrieve_all"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data={"key": SMSPOOL_KEY}) as resp:
            if resp.status != 200:
                print(f"Failed to fetch countries: {resp.status}")
                return
            raw_countries = await resp.json()
            formatted = []
            for c in raw_countries:
                name = str(c.get("name") or "")
                if not name:
                    continue
                formatted.append(
                    {
                        "code": str(c.get("ID", "")),
                        "name": name,
                        "aliases": [name.lower()],
                    }
                )

            with open(f"{DATA_DIR}/countries.json", "w", encoding="utf-8") as f:
                json.dump(formatted, f, indent=4, ensure_ascii=False)
            print(f"Saved {len(formatted)} countries.")


async def fetch_us_states():
    print("Writing US states list...")
    states = [
        {"code": "AL", "name": "Alabama"},
        {"code": "AK", "name": "Alaska"},
        {"code": "AZ", "name": "Arizona"},
        {"code": "AR", "name": "Arkansas"},
        {"code": "CA", "name": "California"},
        {"code": "CO", "name": "Colorado"},
        {"code": "CT", "name": "Connecticut"},
        {"code": "DE", "name": "Delaware"},
        {"code": "FL", "name": "Florida"},
        {"code": "GA", "name": "Georgia"},
        {"code": "HI", "name": "Hawaii"},
        {"code": "ID", "name": "Idaho"},
        {"code": "IL", "name": "Illinois"},
        {"code": "IN", "name": "Indiana"},
        {"code": "IA", "name": "Iowa"},
        {"code": "KS", "name": "Kansas"},
        {"code": "KY", "name": "Kentucky"},
        {"code": "LA", "name": "Louisiana"},
        {"code": "ME", "name": "Maine"},
        {"code": "MD", "name": "Maryland"},
        {"code": "MA", "name": "Massachusetts"},
        {"code": "MI", "name": "Michigan"},
        {"code": "MN", "name": "Minnesota"},
        {"code": "MS", "name": "Mississippi"},
        {"code": "MO", "name": "Missouri"},
        {"code": "MT", "name": "Montana"},
        {"code": "NE", "name": "Nebraska"},
        {"code": "NV", "name": "Nevada"},
        {"code": "NH", "name": "New Hampshire"},
        {"code": "NJ", "name": "New Jersey"},
        {"code": "NM", "name": "New Mexico"},
        {"code": "NY", "name": "New York"},
        {"code": "NC", "name": "North Carolina"},
        {"code": "ND", "name": "North Dakota"},
        {"code": "OH", "name": "Ohio"},
        {"code": "OK", "name": "Oklahoma"},
        {"code": "OR", "name": "Oregon"},
        {"code": "PA", "name": "Pennsylvania"},
        {"code": "RI", "name": "Rhode Island"},
        {"code": "SC", "name": "South Carolina"},
        {"code": "SD", "name": "South Dakota"},
        {"code": "TN", "name": "Tennessee"},
        {"code": "TX", "name": "Texas"},
        {"code": "UT", "name": "Utah"},
        {"code": "VT", "name": "Vermont"},
        {"code": "VA", "name": "Virginia"},
        {"code": "WA", "name": "Washington"},
        {"code": "WV", "name": "West Virginia"},
        {"code": "WI", "name": "Wisconsin"},
        {"code": "WY", "name": "Wyoming"},
    ]

    with open(f"{DATA_DIR}/states_us.json", "w", encoding="utf-8") as f:
        json.dump(states, f, indent=4, ensure_ascii=False)
    print("Saved 50 US states.")


async def main():
    _assert_required_env()
    await fetch_available_countries()
    await fetch_us_states()


if __name__ == "__main__":
    asyncio.run(main())
