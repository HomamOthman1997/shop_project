from types import SimpleNamespace

import pytest

import handlers.start as start_handler


class _Message:
    def __init__(self):
        self.from_user = SimpleNamespace(id=123)
        self.answers = []

    async def answer(self, text, **_kwargs):
        self.answers.append(text)


@pytest.mark.asyncio
async def test_website_link_payload_links_only_on_main_bot(monkeypatch):
    message = _Message()

    async def consume(payload, *, telegram_id):
        assert payload == "link_" + ("a" * 32)
        assert telegram_id == 123
        return {"ok": True}

    monkeypatch.setattr(start_handler, "consume_telegram_link", consume)

    handled = await start_handler._handle_website_link_payload(
        message,
        payload="link_" + ("a" * 32),
        current_bot_id=10,
        main_bot_id=10,
        lang="en",
    )

    assert handled is True
    assert "linked" in message.answers[0].lower()


@pytest.mark.asyncio
async def test_website_link_payload_rejects_other_bots(monkeypatch):
    message = _Message()

    handled = await start_handler._handle_website_link_payload(
        message,
        payload="link_" + ("a" * 32),
        current_bot_id=11,
        main_bot_id=10,
        lang="en",
    )

    assert handled is True
    assert "main" in message.answers[0].lower()


@pytest.mark.asyncio
async def test_website_account_gate_sends_website_login_without_forcing_link(monkeypatch):
    message = _Message()

    async def missing(_telegram_id):
        return None

    monkeypatch.setattr(start_handler, "find_website_account_by_telegram_id", missing)
    monkeypatch.setattr(start_handler, "_website_login_url", lambda: "https://phantom-app.net/login")

    blocked = await start_handler._require_website_account_gate(
        message,
        current_bot_id=10,
        main_bot_id=10,
        is_numbers_runtime_bot=False,
        is_digital_products_runtime_bot=False,
        is_card_ex_runtime_bot=False,
        lang="ar",
    )

    assert blocked is True
    assert "إلزامي" in message.answers[0]
    assert "اختياري" in message.answers[0]


@pytest.mark.asyncio
async def test_website_account_gate_allows_linked_user(monkeypatch):
    message = _Message()

    async def found(_telegram_id):
        return {"_id": "account-1"}

    monkeypatch.setattr(start_handler, "find_website_account_by_telegram_id", found)

    blocked = await start_handler._require_website_account_gate(
        message,
        current_bot_id=10,
        main_bot_id=10,
        is_numbers_runtime_bot=False,
        is_digital_products_runtime_bot=False,
        is_card_ex_runtime_bot=False,
        lang="ar",
    )

    assert blocked is False
    assert message.answers == []
