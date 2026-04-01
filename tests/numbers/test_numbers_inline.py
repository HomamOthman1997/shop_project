import os
import sys

import pytest
from aiogram import types

sys.path.insert(0, os.getcwd())

from services.numbers.handlers import numbers_inline


class DummyInlineQuery:
    def __init__(self, query: str):
        self.query = query
        self.from_user = types.User(id=123, is_bot=False, first_name="u")
        self.results = None

    async def answer(self, results, **kwargs):
        self.results = results


@pytest.mark.asyncio
async def test_country_inline_titles_are_compact(monkeypatch):
    async def fake_countries():
        return [
            {"code": "1", "iso": "US", "name": "United States", "aliases": ["usa", "us"]},
            {"code": "2", "iso": "CA", "name": "Canada", "aliases": ["ca"]},
        ]

    monkeypatch.setattr(numbers_inline, "_get_search_countries", fake_countries)

    query = DummyInlineQuery("country us")
    await numbers_inline.handle_smart_search(query)

    titles = [item.title for item in query.results]
    assert "USA 🇺🇸" in titles
    assert any(title.startswith("Canada") for title in titles)
    assert all(getattr(item, "thumbnail_url", None) not in (None, "") for item in query.results)


@pytest.mark.asyncio
async def test_state_inline_titles_show_name_only():
    query = DummyInlineQuery("state california")
    await numbers_inline.handle_smart_search(query)

    titles = [item.title for item in query.results]
    assert "California" in titles
    assert getattr(query.results[0], "thumbnail_url", None) not in (None, "")
    assert all(getattr(item, "description", None) in (None, "") for item in query.results)


@pytest.mark.asyncio
async def test_tvstate_inline_titles_show_name_only():
    query = DummyInlineQuery("tvstate california")
    await numbers_inline.handle_smart_search(query)

    titles = [item.title for item in query.results]
    assert "California" in titles
    assert all(getattr(item, "thumbnail_url", None) not in (None, "") for item in query.results)
    assert all(getattr(item, "description", None) in (None, "") for item in query.results)
