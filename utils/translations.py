from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "translations_clean_snapshot.json"

_CP1252_REVERSE: dict[str, int] = {}
for _b in range(256):
    try:
        _CP1252_REVERSE[bytes([_b]).decode("cp1252")] = _b
    except Exception:
        continue


def _repair_mojibake(value: str) -> str:
    if not isinstance(value, str) or not value:
        return value
    markers = ("Ã", "â", "Ø", "Ù", "ð", "Ð", "�")
    current = value
    for _ in range(3):
        if not any(marker in current for marker in markers):
            break
        raw_bytes = bytearray()
        for ch in current:
            code = ord(ch)
            if code <= 0xFF:
                raw_bytes.append(code)
                continue
            mapped = _CP1252_REVERSE.get(ch)
            if mapped is None:
                return current
            raw_bytes.append(mapped)
        try:
            fixed = bytes(raw_bytes).decode("utf-8", errors="strict")
        except Exception:
            return current
        if not fixed or fixed == current:
            break
        current = fixed
    return current


def _load_translations() -> dict[str, dict[str, str]]:
    raw = json.loads(_DATA_PATH.read_text(encoding="utf-8-sig"))
    data: dict[str, dict[str, str]] = {}
    for lang, entries in raw.items():
        if not isinstance(entries, dict):
            continue
        data[str(lang)] = {
            str(key): _repair_mojibake(str(value))
            for key, value in entries.items()
        }
    return data


translations = _load_translations()


@lru_cache(maxsize=1024)
def _t_base(lang: str, key: str) -> str:
    lang_code = str(lang or "en").strip().lower()
    if lang_code not in translations:
        lang_code = "en"
    current = translations.get(lang_code, {})
    fallback = translations.get("en", {})
    value = current.get(key)
    if value is None:
        value = fallback.get(key)
    if value is None:
        return key
    return str(value)


def t(lang: str, key: str, **kwargs) -> str:
    value = _t_base(lang, key)
    if not kwargs:
        rendered = value
    else:
        try:
            rendered = value.format(**kwargs)
        except Exception:
            rendered = value
    lang_code = str(lang or "en").strip().lower()
    rendered = str(rendered).replace("$", "💲")
    if lang_code.startswith("ar"):
        rendered = rendered.replace("SYP", "محلي")
        rendered = rendered.replace("USD", "💲")
    else:
        rendered = rendered.replace("SYP", "local")
        rendered = rendered.replace("USD", "💲")
    return rendered
