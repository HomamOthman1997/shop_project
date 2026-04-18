import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.numbers.handlers import numbers_inline


class _DummyUser:
    def __init__(self, uid: int):
        self.id = uid


class _DummyInlineQuery:
    def __init__(self, query: str, uid: int = 1):
        self.query = query
        self.from_user = _DummyUser(uid)
        self.results = None

    async def answer(self, results, **kwargs):
        self.results = results


def test_strip_prefix_tokens_repeated():
    assert numbers_inline._strip_prefix_tokens("service service gmail", "service") == "gmail"
    assert numbers_inline._strip_prefix_tokens("country country us", "country") == "us"


def test_iso_to_flag():
    assert numbers_inline._iso_to_flag("US") == "🇺🇸"
    assert numbers_inline._iso_to_flag("gb") == "🇬🇧"
    assert numbers_inline._iso_to_flag("") == ""


@pytest.mark.asyncio
async def test_country_search_hides_flag(monkeypatch):
    async def fake_countries():
        return [
            {"code": "1", "iso": "US", "name": "United States", "aliases": ["usa", "america"]},
            {"code": "2", "iso": "GB", "name": "United Kingdom", "aliases": ["uk", "britain"]},
        ]

    monkeypatch.setattr(numbers_inline, "_get_search_countries", fake_countries)
    iq = _DummyInlineQuery("country united", uid=101)
    await numbers_inline.handle_smart_search(iq)
    assert iq.results
    assert "Any Country" in iq.results[0].title
    titles = [r.title for r in iq.results]
    assert "United States" in titles or "⚡ United States" in titles
    assert "United Kingdom" in titles or "⚡ United Kingdom" in titles
    assert all(not title.startswith("🇺🇸 ") and not title.startswith("🇬🇧 ") for title in titles)


@pytest.mark.asyncio
async def test_service_search_title_without_redundant_service_prefix(monkeypatch):
    async def _fake_icon(*args, **kwargs):
        return "https://example.com/icon.png"

    monkeypatch.setattr(numbers_inline, "resolve_service_icon_url", _fake_icon)
    monkeypatch.setattr(
        numbers_inline,
        "SERVICE_MAP",
        {"gmail": {"display_name": "Gmail / Google"}, "telegram": {"display_name": "Telegram"}},
    )
    iq = _DummyInlineQuery("service service gmail", uid=202)
    await numbers_inline.handle_smart_search(iq)
    assert iq.results
    assert all(not str(r.title).startswith("Service:") for r in iq.results)


@pytest.mark.asyncio
async def test_service_search_fallback_not_listed(monkeypatch):
    async def _fake_icon(*args, **kwargs):
        return "https://example.com/icon.png"

    monkeypatch.setattr(numbers_inline, "resolve_service_icon_url", _fake_icon)
    monkeypatch.setattr(numbers_inline, "SERVICE_MAP", {})
    iq = _DummyInlineQuery("service unknownzzz", uid=301)
    await numbers_inline.handle_smart_search(iq)
    assert iq.results
    assert iq.results[0].title == "Service Not Listed"
    assert iq.results[0].input_message_content.message_text == "/select_service_query:unknownzzz"


@pytest.mark.asyncio
async def test_service_search_respects_query_order(monkeypatch):
    async def _fake_icon(*args, **kwargs):
        return "https://example.com/icon.png"

    monkeypatch.setattr(numbers_inline, "resolve_service_icon_url", _fake_icon)
    monkeypatch.setattr(
        numbers_inline,
        "SERVICE_MAP",
        {
            "abcservice": {"display_name": "ABC Service"},
            "acbservice": {"display_name": "ACB Service"},
        },
    )
    iq = _DummyInlineQuery("service abc", uid=302)
    await numbers_inline.handle_smart_search(iq)
    titles = [r.title for r in iq.results]
    assert "ABC Service" in titles
    assert "ACB Service" not in titles


@pytest.mark.asyncio
async def test_service_search_matches_aliases(monkeypatch):
    async def _fake_icon(*args, **kwargs):
        return "https://example.com/icon.png"

    monkeypatch.setattr(numbers_inline, "resolve_service_icon_url", _fake_icon)
    monkeypatch.setattr(
        numbers_inline,
        "SERVICE_MAP",
        {
            "anthropic": {
                "display_name": "ClaudeAI / Anthropic",
                "aliases": ["claude", "claudeai", "anthropic"],
            }
        },
    )
    iq = _DummyInlineQuery("service claude", uid=303)
    await numbers_inline.handle_smart_search(iq)
    titles = [r.title for r in iq.results]
    assert "ClaudeAI / Anthropic" in titles
