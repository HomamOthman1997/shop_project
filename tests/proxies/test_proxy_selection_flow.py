import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.proxies.catalog_cache import filter_offers
from services.proxies.handlers import proxy_flow
from services.proxies.keyboards.proxy_kb import (
    proxy_entry_kb,
    proxy_offer_actions_kb,
    proxy_offer_duration_kb,
    proxy_offers_kb,
    proxy_order_actions_kb,
    proxy_provider_kb,
    proxy_search_kb,
)


def test_proxy_filter_offers_supports_provider_and_period():
    offers = [
        {"country": "UNITED STATES", "state": "NY", "provider": "4g", "carrier": "AT&T", "period": "Rotation 30m"},
        {"country": "Any", "state": "Any", "provider": "9proxy", "carrier": "9proxy", "period": "Traffic/GB plan"},
    ]
    filtered = filter_offers(
        offers,
        country="UNITED STATES",
        state="NY",
    )
    assert filtered == offers
    narrowed = filter_offers(
        offers,
        country="UNITED STATES",
        state="NY",
        carrier="AT&T",
        period="Rotation 30m",
    )
    assert narrowed == [offers[0]]


def test_provider_error_text_masks_provider_balance_shortage():
    text = proxy_flow._provider_error_text(
        "en",
        {"title": "REQUEST_ERROR", "details": "Your balance is insufficient"},
    )
    assert text == "Provider is temporarily unavailable. Please try again after 30 minutes."


def test_proxy_location_mode_prefers_state_over_city_and_falls_back_to_city():
    data = {
        "proxy_country": "UNITED STATES",
        "proxy_catalog": [
            {"country": "UNITED STATES", "state": "NY", "city": "New York"},
            {"country": "UNITED STATES", "state": "CA", "city": "Los Angeles"},
        ],
    }
    assert proxy_flow._location_mode(data) == "state"
    assert proxy_flow._state_required(data) is True
    assert proxy_flow._city_required(data) is False

    data = {
        "proxy_country": "GERMANY",
        "proxy_catalog": [
            {"country": "GERMANY", "state": "", "city": "Berlin"},
            {"country": "GERMANY", "state": "Any", "city": "Hamburg"},
        ],
    }
    assert proxy_flow._location_mode(data) == "city"
    assert proxy_flow._state_required(data) is False
    assert proxy_flow._city_required(data) is True


def test_proxy_search_keyboard_supports_state_or_city_and_listing():
    kb = proxy_search_kb("en", quick_country_options=[("United States", "proxy:quick_country:usa"), ("Germany", "proxy:quick_country:de")])
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [btn.text for btn in buttons]
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
    assert "Search Country" in texts
    assert "United States" in texts
    assert "proxy:quick_country:usa" in callbacks
    assert "proxy:pick_provider" not in callbacks
    assert "proxy:pick_period" not in callbacks
    search_btn = next(btn for btn in buttons if btn.text == "Search Country")
    assert search_btn.style == "primary"

    kb = proxy_search_kb(
        "en",
        country="UNITED STATES",
        require_state=True,
        quick_location_options=[("New York", "proxy:quick_state:us:ny"), ("California", "proxy:quick_state:us:ca")],
    )
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [btn.text for btn in buttons]
    callbacks = [btn.callback_data for btn in buttons if btn.callback_data]
    assert "Search State/City" in texts
    assert "proxy:pick_provider" not in callbacks
    search_btn = next(btn for btn in buttons if btn.text == "Search State/City")
    assert search_btn.style == "primary"
    assert search_btn.switch_inline_query_current_chat == 'proxy state "UNITED STATES" '
    assert "New York" not in texts
    assert "proxy:quick_state:us:ny" not in callbacks

    kb = proxy_search_kb(
        "en",
        country="UNITED STATES",
        state="NY",
        require_state=True,
        protocol="http",
        provider_options=[("AT&T (10)", "AT&T"), ("T-Mobile (12)", "T-Mobile")],
    )
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [btn.text for btn in buttons]
    callbacks = [btn.callback_data for btn in buttons if btn.callback_data]
    assert "AT&T (10)" in texts
    assert "T-Mobile (12)" in texts
    assert "proxy:pick_provider" not in callbacks
    assert "proxy:pick_period" not in callbacks
    provider_rows = [row for row in kb.inline_keyboard if row and row[0].callback_data and row[0].callback_data.startswith("proxy:set_provider:")]
    assert all(len(row) == 1 for row in provider_rows)

    kb = proxy_search_kb(
        "en",
        country="GERMANY",
        require_city=True,
    )
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "Search State/City" in texts

    kb = proxy_search_kb(
        "en",
        country="GERMANY",
        city="Berlin",
        protocol="http",
        provider="T-Mobile",
        require_city=True,
        period_options=[("Rotation 30m", "Rotation 30m"), ("Rotation 60m", "Rotation 60m")],
    )
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "Rotation 30m" in texts


def test_proxy_search_keyboard_protocol_and_duration_steps():
    kb = proxy_search_kb(
        "en",
        country="UNITED STATES",
        state="NY",
        require_state=True,
        protocol_options=[("HTTP", "http"), ("SOCKS", "socks")],
    )
    rows = kb.inline_keyboard
    texts = [btn.text for row in rows for btn in row]
    assert "HTTP" in texts
    assert "SOCKS" in texts
    assert rows[0][0].text == "HTTP"
    assert len(rows[0]) == 1
    assert rows[1][0].text == "SOCKS"
    assert len(rows[1]) == 1

    kb = proxy_search_kb(
        "en",
        country="UNITED STATES",
        state="NY",
        require_state=True,
        protocol="http",
        provider="T-Mobile",
        period="Rotation 30s",
        duration_options=[("3 Hour - 0.70$", "0.03"), ("1 Day - 1.20$", "1")],
    )
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "3 Hour - 0.70$" in texts
    assert "1 Day - 1.20$" in texts


def test_duration_option_map_and_price_markup():
    data = {
        "proxy_country": "UNITED STATES",
        "proxy_state": "NY",
        "proxy_provider": "T-Mobile",
        "proxy_period": "Rotation 30s",
        "proxy_catalog": [
            {
                "country": "UNITED STATES",
                "state": "NY",
                "city": "Any",
                "carrier": "T-Mobile",
                "provider": "4g",
                "period": "Rotation 30s",
                "base_price": 1.0,
                "price": 1.1,
                "raw": {
                    "duration_options": [
                        {"value": "0.03", "label": "3 Hour", "price": 0.7},
                        {"value": "1", "label": "1 Day", "price": 1.0},
                    ]
                },
            }
        ],
    }
    options = proxy_flow._duration_option_map(data)
    assert options["0.03"][0] == "3 Hour"
    assert options["0.03"][1] == 0.77
    priced = proxy_flow._offers_with_duration_price({**data, "proxy_duration_value": "0.03", "proxy_protocol": "socks"}, data["proxy_catalog"])
    assert priced[0]["base_price"] == 0.7
    assert priced[0]["price"] == 0.77
    assert priced[0]["protocol"] == "socks"


def test_available_proxy_period_options_hide_load_and_price():
    data = {
        "proxy_country": "UNITED STATES",
        "proxy_state": "NY",
        "proxy_provider": "T-Mobile",
        "proxy_catalog": [
            {
                "country": "UNITED STATES",
                "state": "NY",
                "city": "Any",
                "carrier": "T-Mobile",
                "provider": "4g",
                "period": "Rotation 30m",
                "price": 0.5,
                "raw": {"usage": 22},
            },
            {
                "country": "UNITED STATES",
                "state": "NY",
                "city": "Any",
                "carrier": "T-Mobile",
                "provider": "4g",
                "period": "Rotation 30m",
                "price": 0.6,
                "raw": {"usage": 8},
            },
        ],
    }
    options = proxy_flow._available_proxy_period_options(data)
    assert options == [("Rotation 30m", "Rotation 30m")]


def test_available_proxy_provider_options_keep_raw_provider_names():
    data = {
        "proxy_country": "UNITED STATES",
        "proxy_state": "NY",
        "proxy_catalog": [
            {"country": "UNITED STATES", "state": "NY", "city": "Any", "carrier": "5G T-mobile", "provider": "4g"},
            {"country": "UNITED STATES", "state": "NY", "city": "Any", "carrier": "5G AT&T", "provider": "4g"},
            {"country": "UNITED STATES", "state": "NY", "city": "Any", "carrier": "T-MOBILE", "provider": "4g"},
        ],
    }
    options = proxy_flow._available_proxy_provider_options(data)
    assert ("5G AT&T", "5G AT&T") in options
    assert ("5G T-mobile", "5G T-mobile") in options
    assert ("T-MOBILE", "T-MOBILE") in options


class DummyState:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.state = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, value):
        self.state = value


class DummyMessage:
    def __init__(self):
        self.message_id = 321
        self.chat = type("Chat", (), {"id": 123})()
        self.bot = type("Bot", (), {})()


class DummyCallback:
    def __init__(self, data="proxy:buy"):
        self.data = data
        self.message = DummyMessage()
        self.from_user = type("User", (), {"id": 99})()
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))


@pytest.mark.asyncio
async def test_proxy_buy_menu_opens_type_menu(monkeypatch):
    callback = DummyCallback("proxy:buy")
    state = DummyState({"proxy_lang": "en", "proxy_category": "unlimited"})
    calls = {}

    async def _fake_render(message, current_state, lang):
        calls["render"] = (message.message_id, lang)

    monkeypatch.setattr(proxy_flow, "_render_proxy_type_menu", _fake_render)
    monkeypatch.setattr(proxy_flow, "get_user", lambda _user_id: {"language": "en"})

    await proxy_flow.proxy_buy_menu(callback, state)

    assert calls["render"] == (321, "en")
    assert state.data["proxy_country"] is None
    assert state.data["proxy_panel_msg"] == 321
    assert state.data["proxy_type_msg"] == 321
    assert state.state == proxy_flow.ProxyFlow.menu


@pytest.mark.asyncio
async def test_proxy_type_menu_aliases_buy_menu(monkeypatch):
    callback = DummyCallback("proxy:type_menu")
    state = DummyState({"proxy_lang": "en"})
    called = {"buy": 0}

    async def _fake_buy(cb, st):
        called["buy"] += 1
        assert cb is callback
        assert st is state

    monkeypatch.setattr(proxy_flow, "proxy_buy_menu", _fake_buy)

    await proxy_flow.proxy_type_menu(callback, state)

    assert called["buy"] == 1


@pytest.mark.asyncio
async def test_proxy_select_type_loads_catalog_and_renders_panel(monkeypatch):
    callback = DummyCallback("proxy:type:unlimited")
    state = DummyState({"proxy_lang": "en"})
    calls = {}

    async def _fake_edit(message, text, reply_markup=None):
        calls.setdefault("edit", []).append((message.message_id, text, reply_markup))

    async def _fake_refresh(current_state):
        calls["refresh"] = True
        return [{"offer_id": "1"}]

    async def _fake_panel(message, current_state):
        calls["panel"] = message.message_id

    monkeypatch.setattr(proxy_flow, "_safe_edit_text", _fake_edit)
    monkeypatch.setattr(proxy_flow, "_refresh_catalog_in_state", _fake_refresh)
    monkeypatch.setattr(proxy_flow, "_render_proxy_panel", _fake_panel)
    monkeypatch.setattr(proxy_flow, "get_user", lambda _user_id: {"language": "en"})

    await proxy_flow.proxy_select_type(callback, state)

    assert calls["refresh"] is True
    assert calls["panel"] == 321
    assert state.data["proxy_category"] == "unlimited"
    assert state.data["proxy_panel_msg"] == 321
    assert state.state == proxy_flow.ProxyFlow.menu


@pytest.mark.asyncio
async def test_proxy_select_type_rejects_suspended_category(monkeypatch):
    callback = DummyCallback("proxy:type:consumptive")
    state = DummyState({"proxy_lang": "en"})

    monkeypatch.setattr(proxy_flow, "get_user", lambda _user_id: {"language": "en"})

    await proxy_flow.proxy_select_type(callback, state)

    assert callback.answers
    assert callback.answers[-1][1].get("show_alert") is True


@pytest.mark.asyncio
async def test_select_proxy_state_falls_back_to_city_for_city_only_country():
    message = type(
        "Msg",
        (),
        {
            "text": f"/proxy_state_{proxy_flow.encode_token('GERMANY')}~{proxy_flow.encode_token('Berlin')}",
            "message_id": 111,
            "chat": type("Chat", (), {"id": 222})(),
            "bot": type("Bot", (), {})(),
            "delete": staticmethod(lambda: None),
        },
    )()
    state = DummyState(
        {
            "proxy_lang": "en",
            "proxy_category": "unlimited",
            "proxy_catalog": [
                {"country": "GERMANY", "state": "Any", "city": "Berlin", "provider": "4g", "carrier": "Carrier", "period": "Rotation 30m"}
            ],
        }
    )

    async def _fake_delete():
        return None

    message.delete = _fake_delete

    captured = {}

    async def _fake_render(msg, current_state):
        captured["rendered"] = msg.message_id

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(proxy_flow, "_render_proxy_panel", _fake_render)
    try:
        await proxy_flow.select_proxy_state(message, state)
    finally:
        monkeypatch.undo()

    assert captured["rendered"] == 111
    assert state.data["proxy_country"] == "GERMANY"
    assert state.data["proxy_state"] is None
    assert state.data["proxy_city"] == "Berlin"


def test_proxy_keyboards_use_live_back_callbacks():
    entry_callbacks = [btn.callback_data for row in proxy_entry_kb("en").inline_keyboard for btn in row if btn.callback_data]
    assert "proxy:type_menu" in entry_callbacks

    provider_callbacks = [btn.callback_data for row in proxy_provider_kb(["A"], "en").inline_keyboard for btn in row if btn.callback_data]
    assert "proxy:back_step" in provider_callbacks

    offers_callbacks = [btn.callback_data for row in proxy_offers_kb([{"offer_id": "1"}], "en").inline_keyboard for btn in row if btn.callback_data]
    assert "proxy:back_step" in offers_callbacks

    offer_action_callbacks = [btn.callback_data for row in proxy_offer_actions_kb("en").inline_keyboard for btn in row if btn.callback_data]
    assert "proxy:list" in offer_action_callbacks

    duration_callbacks = [btn.callback_data for row in proxy_offer_duration_kb([("1 Day", "1")], "en").inline_keyboard for btn in row if btn.callback_data]
    assert "proxy:list" in duration_callbacks

    order_callbacks = [btn.callback_data for row in proxy_order_actions_kb("oid-1", "en").inline_keyboard for btn in row if btn.callback_data]
    assert "proxy:my_orders" in order_callbacks

    reconfigure_callbacks = [
        btn.callback_data
        for row in proxy_order_actions_kb("oid-1", "en", can_reconfigure=True).inline_keyboard
        for btn in row
        if btn.callback_data
    ]
    assert "proxy:order:reconfigure:oid-1" in reconfigure_callbacks


def test_proxy_offer_text_combines_state_and_city():
    text = proxy_flow._proxy_offer_text(
        "en",
        {"carrier": "AT&T", "country": "UNITED STATES", "state": "Texas", "city": "Dallas", "period": "Rotation 30m"},
        "http",
    )
    assert "State/City: Texas / Dallas" in text
    ar_text = proxy_flow._proxy_offer_text(
        "ar",
        {"carrier": "AT&T", "country": "UNITED STATES", "state": "Texas", "city": "Dallas", "period": "Rotation 30m"},
        "http",
    )
    assert "الولاية/المدينة: Texas / Dallas" in ar_text


@pytest.mark.asyncio
async def test_proxy_back_step_clears_last_filter(monkeypatch):
    callback = DummyCallback("proxy:back_step")
    state = DummyState(
        {
            "proxy_lang": "en",
            "proxy_category": "unlimited",
            "proxy_country": "UNITED STATES",
            "proxy_state": "Texas",
            "proxy_protocol": "http",
            "proxy_provider": "4g",
            "proxy_period": "Rotation 30m",
        }
    )
    rendered = {}

    async def _fake_render(message, current_state):
        rendered["message_id"] = message.message_id

    monkeypatch.setattr(proxy_flow, "_render_proxy_panel", _fake_render)

    await proxy_flow.proxy_back_step(callback, state)

    assert rendered["message_id"] == 321
    assert state.data["proxy_period"] is None
    assert state.data["proxy_provider"] == "4g"
