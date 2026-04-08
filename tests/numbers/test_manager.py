import os
import sys
import asyncio
import pytest

# make sure project root is on import path so "services" package is found
sys.path.insert(0, os.getcwd())

from services.numbers import manager
from services.numbers.service_map import get_provider_service_name, resolve_canonical_service_key

# we will replace manager.PROVIDERS in various tests with simple dummies


class DummyProvider:
    async def get_price(self, service, country=None, state=None):
        return {"success": True, "price": 1.23}

    async def buy_number(self, service, country=None, state=None):
        return {"success": True, "order_id": "42"}

    async def get_rental_prices(self, service, country=None):
        return {"success": True, "options": [{"country": str(country or "1"), "duration": 2, "price": 0.5, "count": 10}]}

    async def rent_number(self, service, country=None, duration=2):
        return {"success": True, "order_id": "99", "number": "700000000"}


@pytest.fixture(autouse=True)
def _patch_providers(monkeypatch):
    # make manager.PROVIDERS point to dummy objects for deterministic tests
    monkeypatch.setitem(manager.PROVIDERS, 'smspool', DummyProvider())
    monkeypatch.setitem(manager.PROVIDERS, 'telabot', DummyProvider())
    monkeypatch.setitem(manager.PROVIDERS, 'textverified', DummyProvider())
    monkeypatch.setitem(manager.PROVIDERS, 'herosms', DummyProvider())
    monkeypatch.setitem(manager.PROVIDERS, 'smsman', DummyProvider())
    monkeypatch.setitem(manager.PROVIDERS, 'pvadeals', DummyProvider())
    monkeypatch.setitem(manager.PROVIDERS, 'alisms', DummyProvider())


def test_service_name_lookup():
    # use the static service map (not dynamic modules) for this simple check
    result = get_provider_service_name("telegram", "smspool")
    assert result
    assert get_provider_service_name("telegram", "pvadeals") == "Telegram"
    assert get_provider_service_name("UNKNOWN", "foo") == "UNKNOWN"


@pytest.mark.asyncio
async def test_dynamic_provider_name(monkeypatch):
    # patch the json-data modules to small predictable structures
    from services.numbers.data import smspool_services, telabot_services, textverified_services

    # give smspool a numeric ID so we can verify the helper returns it
    monkeypatch.setattr(smspool_services, 'DATA', [{'ID': 123, 'name': 'Telegram'}])
    monkeypatch.setattr(telabot_services, 'DATA', {'Telegram': {}})
    monkeypatch.setattr(textverified_services, 'DATA', [{'serviceName': 'Telegram'}])

    # SMSPool now should return the ID as string
    assert await manager.get_provider_service_name_dynamic('telegram', 'smspool') == '123'
    assert await manager.get_provider_service_name_dynamic('TeLeGraM', 'telabot') == 'Telegram'
    assert await manager.get_provider_service_name_dynamic('telegram', 'textverified') == 'Telegram'
    # unknown service returns None
    assert await manager.get_provider_service_name_dynamic('nope', 'smspool') is None
    assert await manager.get_provider_service_name_dynamic('telegram', 'unknown') is None


@pytest.mark.asyncio
async def test_dynamic_provider_name_pvadeals(monkeypatch):
    class _PVADummy:
        async def list_services(self, force_refresh=False):
            return [
                {"_id": "svc1", "name": "Telegram", "country": "USA", "STRprice": 0.2},
                {"_id": "svc2", "name": "WhatsApp", "country": "USA", "STRprice": 0.2},
            ]

    monkeypatch.setitem(manager.PROVIDERS, "pvadeals", _PVADummy())
    assert await manager.get_provider_service_name_dynamic("telegram", "pvadeals") == "Telegram"
    assert await manager.get_provider_service_name_dynamic("nope", "pvadeals") is None


@pytest.mark.asyncio
async def test_dynamic_provider_name_pvadeals_prefers_provider_lookup_over_family_aliases(monkeypatch):
    class _PVADummy:
        async def resolve_service_code(self, value):
            lookup = {
                "google": "svc_google",
                "gmail": "svc_google",
                "youtube": "svc_youtube",
            }
            return lookup.get(str(value).lower())

        async def list_services(self, force_refresh=False):
            return [
                {"_id": "svc_google", "name": "Google (Gmail)", "country": "USA", "STRprice": 1.0},
                {"_id": "svc_youtube", "name": "YouTube", "country": "USA", "STRprice": 0.09},
            ]

    monkeypatch.setitem(manager.PROVIDERS, "pvadeals", _PVADummy())
    assert await manager.get_provider_service_name_dynamic("google", "pvadeals") == "svc_google"
    assert await manager.get_provider_service_name_dynamic("youtube", "pvadeals") == "svc_youtube"


def test_service_name_lookup_does_not_map_google_to_youtube_for_pvadeals():
    assert get_provider_service_name("google", "pvadeals") != "YouTube"


@pytest.mark.asyncio
async def test_dynamic_provider_name_alisms(monkeypatch):
    class _AliDummy:
        async def resolve_service_code(self, value):
            lookup = {"telegram": "tg", "google": "go"}
            return lookup.get(str(value).lower())

    monkeypatch.setitem(manager.PROVIDERS, "alisms", _AliDummy())
    assert await manager.get_provider_service_name_dynamic("telegram", "alisms") == "tg"
    assert await manager.get_provider_service_name_dynamic("google", "alisms") == "go"
    assert await manager.get_provider_service_name_dynamic("missingzzz", "alisms") is None


@pytest.mark.asyncio
async def test_provider_service_resolution_uses_cache(monkeypatch):
    calls = {"n": 0}

    class _AliDummy:
        async def resolve_service_code(self, value):
            calls["n"] += 1
            return "go" if str(value).lower() == "google" else None

    monkeypatch.setitem(manager.PROVIDERS, "alisms", _AliDummy())
    manager._SERVICE_RESOLUTION_CACHE.clear()

    first = await manager.get_provider_service_resolution_dynamic("google", "alisms")
    second = await manager.get_provider_service_resolution_dynamic("google", "alisms")

    assert first["resolved_provider_service"] == "go"
    assert second["resolved_provider_service"] == "go"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_provider_service_resolution_reuses_live_catalog_cache_across_queries(monkeypatch):
    from services.numbers.data import textverified_services

    calls = {"n": 0}

    class _TextVerifiedDummy:
        async def list_services(self):
            calls["n"] += 1
            return [
                {"serviceName": "PayPal"},
                {"serviceName": "Telegram"},
            ]

    monkeypatch.setattr(textverified_services, "DATA", [])
    monkeypatch.setitem(manager.PROVIDERS, "textverified", _TextVerifiedDummy())
    manager._SERVICE_RESOLUTION_CACHE.clear()
    manager._PROVIDER_SERVICE_LIST_CACHE.clear()

    first = await manager.get_provider_service_resolution_dynamic("paypal", "textverified")
    second = await manager.get_provider_service_resolution_dynamic("telegram", "textverified")

    assert first["resolved_provider_service"] == "PayPal"
    assert second["resolved_provider_service"] == "Telegram"
    assert calls["n"] == 1



@pytest.mark.asyncio
async def test_dynamic_provider_name_matches_composite_smspool_service(monkeypatch):
    from services.numbers.data import smspool_services

    monkeypatch.setattr(
        smspool_services,
        "DATA",
        [
            {"ID": 1371, "name": "ClaudeAI / Anthropic"},
            {"ID": 2000, "name": "OpenAI / ChatGPT"},
        ],
    )

    assert await manager.get_provider_service_name_dynamic("Anthropic", "smspool") == "1371"
    assert await manager.get_provider_service_name_dynamic("ClaudeAI", "smspool") == "1371"
    assert await manager.get_provider_service_name_dynamic("claude", "smspool") == "1371"
    assert await manager.get_provider_service_name_dynamic("ChatGPT", "smspool") == "2000"


@pytest.mark.asyncio
async def test_dynamic_provider_name_smsman_uses_family_aliases(monkeypatch):
    class _SMSManDummy:
        async def resolve_service_code(self, value):
            return "1371" if str(value).lower() == "claudeaianthropic" else None

    monkeypatch.setitem(manager.PROVIDERS, "smsman", _SMSManDummy())
    assert await manager.get_provider_service_name_dynamic("claude", "smsman") == "1371"


@pytest.mark.asyncio
async def test_provider_lookup_does_not_resolve_swagbucks_to_generic_pay(monkeypatch):
    class _HeroDummy:
        async def resolve_service_code(self, value):
            if str(value).lower() == "pay":
                return "pay"
            return None

    monkeypatch.setitem(manager.PROVIDERS, "herosms", _HeroDummy())
    manager._SERVICE_RESOLUTION_CACHE.clear()

    resolution = await manager.get_provider_service_resolution_dynamic("swagbucks", "herosms")
    assert resolution["resolved_provider_service"] is None
    assert resolution["provider_reason"] == "service_not_supported"


def test_business_approved_commercial_variants_only():
    assert resolve_canonical_service_key("swagbucks") == "swagbucks"
    assert resolve_canonical_service_key("inboxdollars") == "swagbucks"
    assert resolve_canonical_service_key("inboxpounds") == "swagbucks"
    assert resolve_canonical_service_key("mypoints") == "swagbucks"
    assert resolve_canonical_service_key("ysense") == "swagbucks"
    assert resolve_canonical_service_key("adgatesurvey") == "swagbucks"
    assert resolve_canonical_service_key("tadapoll") == "swagbucks"
    assert resolve_canonical_service_key("walmart4") == "walmart"
    assert resolve_canonical_service_key("webullpay") == "webull"


@pytest.mark.asyncio
async def test_dynamic_provider_name_smsman(monkeypatch):
    class _SMSManDummy:
        async def resolve_service_code(self, value):
            return "77" if str(value).lower() == "telegram" else None

    monkeypatch.setitem(manager.PROVIDERS, "smsman", _SMSManDummy())
    assert await manager.get_provider_service_name_dynamic("telegram", "smsman") == "77"


@pytest.mark.asyncio
async def test_provider_resolution_diagnostics_for_missing_service(monkeypatch):
    from services.numbers.data import smspool_services

    monkeypatch.setattr(smspool_services, "DATA", [{"ID": 1, "name": "Telegram"}])
    resolution = await manager.get_provider_service_resolution_dynamic("missingzzz", "smspool")
    assert resolution["resolved_provider_service"] is None
    assert resolution["provider_reason"] == "service_not_supported"
    assert resolution["canonical_service"] == "missingzzz"
    assert "missingzzz" in resolution["provider_candidates"]


@pytest.mark.asyncio
async def test_get_all_prices(monkeypatch):
    # ensure manager.GET uses PROVIDERS dict patched by fixture
    # also monkeypatch dynamic name lookup to return a fixed api name
    async def fake_name(s, p):
        return 'telegram'
    monkeypatch.setattr(manager, 'get_provider_service_name_dynamic', fake_name)
    monkeypatch.setattr(manager.settings, "numbers_service_markup_percent", 0.0)
    res = await manager.get_all_prices('telegram', None, None)
    assert 'smspool' in res
    assert res['smspool']['price'] == 1.23


@pytest.mark.asyncio
async def test_get_all_prices_exposes_smsman_s6_placeholder_in_testing_mode(monkeypatch):
    class _SMSManDummy:
        async def get_price_variants(self, service, country=None, state=None, limit=2):
            return []

    monkeypatch.setitem(manager.PROVIDERS, "smsman", _SMSManDummy())
    monkeypatch.setattr(manager.settings, "numbers_show_all_providers_for_testing", True)

    result = await manager.get_all_prices("gmail", "1", None)
    assert "smsman" in result
    assert "smsman_s6" in result
    assert result["smsman_s6"]["testing_visible"] is True
    assert result["smsman_s6"]["provider_reason"] == "second_lane_unavailable"


@pytest.mark.asyncio
async def test_get_all_prices_alisms_uses_provider_resolved_api_service(monkeypatch):
    class _AliDummy:
        async def get_price(self, service, country=None, state=None):
            assert service == "gmail"
            return {"success": True, "price": 0.17, "api_service_name": "jewa"}

    monkeypatch.setitem(manager.PROVIDERS, "alisms", _AliDummy())
    monkeypatch.setattr(manager.settings, "numbers_service_markup_percent", 0.0)

    result = await manager.get_all_prices("gmail", "1", None)
    assert result["alisms"]["price"] == 0.17
    assert result["alisms"]["api_service_name"] == "jewa"


@pytest.mark.asyncio
async def test_get_all_rental_prices_filters_options_by_provider_balance(monkeypatch):
    class _RentalDummy:
        async def get_rental_prices(self, service, country=None):
            return {
                "success": True,
                "options": [
                    {"country": "US", "duration": 24, "price": 1.8, "count": 1},
                    {"country": "US", "duration": 72, "price": 2.9, "count": 1},
                    {"country": "US", "duration": 168, "price": 3.4, "count": 1},
                ],
            }

    async def _fake_balance(_provider):
        return 3.0

    monkeypatch.setitem(manager.PROVIDERS, "textverified", _RentalDummy())
    monkeypatch.setattr(manager, "_provider_balance", _fake_balance)
    monkeypatch.setattr(manager.settings, "numbers_service_markup_percent", 0.0)

    result = await manager.get_all_rental_prices("gmail", "US")
    assert "textverified" in result
    options = result["textverified"]["options"]
    assert [int(row["duration"]) for row in options] == [24, 72]
    assert all(float(row["price"]) <= 3.0 for row in options)


@pytest.mark.asyncio
async def test_get_all_rental_prices_keeps_provider_visible_when_no_affordable_option(monkeypatch):
    class _RentalDummy:
        async def get_rental_prices(self, service, country=None):
            return {
                "success": True,
                "options": [
                    {"country": "US", "duration": 24, "price": 1.8, "count": 1},
                    {"country": "US", "duration": 72, "price": 2.9, "count": 1},
                ],
            }

    async def _fake_balance(_provider):
        return 1.5

    monkeypatch.setitem(manager.PROVIDERS, "textverified", _RentalDummy())
    monkeypatch.setattr(manager, "_provider_balance", _fake_balance)
    monkeypatch.setattr(manager.settings, "numbers_service_markup_percent", 0.0)

    result = await manager.get_all_rental_prices("gmail", "US")
    assert "textverified" in result
    assert result["textverified"]["available_for_buy"] is False
    assert result["textverified"]["provider_reason"] == "provider_balance_low"


@pytest.mark.asyncio
async def test_get_all_prices_uses_provider_country_iso_field(monkeypatch):
    class _HeroDummy:
        async def get_price(self, service, country=None, state=None):
            return {
                "success": True,
                "price": 0.13,
                "api_service_name": "tg",
                "provider_country_iso": "KE",
            }

    monkeypatch.setitem(manager.PROVIDERS, "herosms", _HeroDummy())
    monkeypatch.setattr(manager.settings, "profit_policy_enabled", False)

    async def fake_resolution(service_key, provider_code):
        return {
            "requested_service": service_key,
            "canonical_service": service_key,
            "display_name": service_key,
            "provider_code": provider_code,
            "provider_mapped_value": "tg",
            "provider_candidates": [service_key],
            "resolved_provider_service": "tg",
            "provider_reason": "resolved_static_mapping",
        }

    monkeypatch.setattr(manager, "get_provider_service_resolution_dynamic", fake_resolution)
    result = await manager.get_all_prices("telegram", None, None)
    assert result["herosms"]["provider_country_iso"] == "KE"


@pytest.mark.asyncio
async def test_get_all_prices_fetches_live_each_time(monkeypatch):
    calls = {"n": 0}

    class _Provider:
        async def get_price(self, service, country=None, state=None):
            calls["n"] += 1
            return {"success": True, "price": 1.0}

    monkeypatch.setitem(manager.PROVIDERS, "smspool", _Provider())

    async def fake_name(s, p):
        return "tg"

    monkeypatch.setattr(manager, "get_provider_service_name_dynamic", fake_name)

    r1 = await manager.get_all_prices("telegram", "1", "none")
    r2 = await manager.get_all_prices("telegram", "1", "none")
    assert r1 and r2
    # direct provider pricing is now preferred over stale cache snapshots.
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_get_all_rental_prices(monkeypatch):
    async def fake_name(s, p):
        return "tg"

    async def _fake_balance(_provider):
        return 999.0

    monkeypatch.setattr(manager, "get_provider_service_name_dynamic", fake_name)
    monkeypatch.setattr(manager, "_provider_balance", _fake_balance)
    res = await manager.get_all_rental_prices("telegram", "1")
    assert "herosms" in res
    assert res["herosms"]["options"][0]["duration"] == 2


@pytest.mark.asyncio
async def test_get_all_rental_prices_fetches_live_each_time(monkeypatch):
    calls = {"n": 0}

    class _ProviderOk:
        async def get_rental_prices(self, service, country=None):
            calls["n"] += 1
            return {"success": True, "options": [{"country": str(country or "1"), "duration": 24, "price": 1.0, "count": 5}]}

    monkeypatch.setitem(manager.PROVIDERS, "herosms", _ProviderOk())

    async def fake_name(s, p):
        return "tg"

    async def _fake_balance(_provider):
        return 999.0

    monkeypatch.setattr(manager, "get_provider_service_name_dynamic", fake_name)
    monkeypatch.setattr(manager, "_provider_balance", _fake_balance)

    first = await manager.get_all_rental_prices("telegram", "1")
    assert "herosms" in first
    second = await manager.get_all_rental_prices("telegram", "1")
    assert "herosms" in second
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_get_all_rental_prices_marks_testing_visible_when_balance_low(monkeypatch):
    class _ProviderOk:
        async def get_rental_prices(self, service, country=None):
            return {"success": True, "options": [{"country": str(country or "1"), "duration": 24, "price": 1.0, "count": 5}]}

        async def get_balance(self):
            return 0.0

    monkeypatch.setitem(manager.PROVIDERS, "pvadeals", _ProviderOk())

    async def fake_name(s, p):
        return "tg"

    monkeypatch.setattr(manager, "get_provider_service_name_dynamic", fake_name)
    monkeypatch.setattr(manager.settings, "numbers_show_all_providers_for_testing", True)

    res = await manager.get_all_rental_prices("telegram", "1")
    assert "pvadeals" in res
    assert res["pvadeals"]["available_for_buy"] is False
    assert res["pvadeals"]["testing_visible"] is True
    assert res["pvadeals"]["provider_reason"] == "provider_balance_low"


@pytest.mark.asyncio
async def test_get_all_rental_prices_smspool_open_only(monkeypatch):
    called = []

    async def fake_name(s, p):
        called.append((s, p))
        return "tg"

    async def _fake_balance(_provider):
        return 999.0

    monkeypatch.setattr(manager, "get_provider_service_name_dynamic", fake_name)
    monkeypatch.setattr(manager, "_provider_balance", _fake_balance)
    res = await manager.get_all_rental_prices(manager.SMSPOOL_OPEN_RENTAL_SERVICE_KEY, "1")
    assert set(res.keys()) == {"smspool", "textverified", "pvadeals"}
    # manager should not resolve per-provider names in open-rental mode
    assert called == []


def test_provider_capability_matrix_rules():
    assert manager.provider_allows_temp("herosms", state_selected=False) is True
    assert manager.provider_allows_temp("herosms", state_selected=True) is False
    assert manager.provider_allows_temp("smsman", state_selected=True) is False
    assert manager.provider_allows_temp("telabot", state_selected=True) is True
    assert manager.provider_allows_temp("pvadeals", state_selected=False) is True
    assert manager.provider_allows_temp("pvadeals", state_selected=True) is False
    assert manager.provider_allows_temp("alisms", state_selected=False) is True
    assert manager.provider_allows_temp("alisms", state_selected=True) is False

    assert manager.provider_allows_rental("herosms", service_key="paypal", country_iso="US") is True
    assert manager.provider_allows_rental("smspool", service_key="paypal", country_iso="US") is False
    assert manager.provider_allows_rental("pvadeals", service_key="paypal", country_iso="US") is True
    assert manager.provider_allows_rental("alisms", service_key="paypal", country_iso="US") is False
    assert manager.provider_allows_rental(
        "smspool",
        service_key=manager.RENTAL_UNLIMITED_SERVICE_KEY,
        country_iso="US",
    ) is True
    assert manager.provider_allows_rental(
        "herosms",
        service_key=manager.RENTAL_UNLIMITED_SERVICE_KEY,
        country_iso="US",
    ) is False
    assert manager.provider_allows_rental(
        "textverified",
        service_key=manager.RENTAL_UNLIMITED_SERVICE_KEY,
        country_iso="DE",
    ) is False
    assert manager.provider_allows_rental(
        "herosms",
        service_key="paypal",
        country_iso="US",
        state_selected=True,
    ) is False
    assert manager.provider_allows_rental(
        "textverified",
        service_key="paypal",
        country_iso="US",
        state_selected=True,
    ) is True


@pytest.mark.asyncio
async def test_buy_number_dry_run():
    price = await manager.buy_number_from_provider(
        "smspool", "telegram", None, None, dry_run=True
    )
    assert price == 1.23


@pytest.mark.asyncio
async def test_buy_number_real():
    data = await manager.buy_number_from_provider(
        "smspool", "telegram", None, None, dry_run=False
    )
    assert data["success"] is True






@pytest.mark.asyncio
async def test_credentials_checks(monkeypatch):
    # avoid real network call for textverified by forcing auth failure
    async def fake_auth(self):
        return None
    monkeypatch.setattr(
        "services.numbers.providers.textverified_provider.TextVerifiedProvider._auth",
        fake_auth,
    )
    from services.numbers.providers.smspool_provider import SMSPoolProvider
    from services.numbers.providers.telabot_provider import TelabotProvider
    from services.numbers.providers.textverified_provider import TextVerifiedProvider
    from config import settings

    # clear credentials
    monkeypatch.setattr(settings, "smspool_key", None)
    monkeypatch.setattr(settings, "telabot_user", None)
    monkeypatch.setattr(settings, "telabot_key", None)
    monkeypatch.setattr(settings, "tv_user", None)
    monkeypatch.setattr(settings, "tv_key", None)

    smspool = SMSPoolProvider()
    telabot = TelabotProvider()
    textv = TextVerifiedProvider()

    # sms pool should return missing_api_key
    r1 = await smspool.get_price("foo")
    assert r1["success"] is False
    assert r1.get("raw") == "missing_api_key"

    # telabot _get should warn and return error
    r2 = await telabot.get_price("bar")
    assert r2["success"] is False

@pytest.mark.asyncio
async def test_telabot_no_fallback(monkeypatch):
    # when the API list_services returns nothing we expect failure rather
    # than using any cached data
    from services.numbers.providers.telabot_provider import TelabotProvider
    prov = TelabotProvider()
    async def fake_list():
        return {}
    monkeypatch.setattr(prov, 'list_services', fake_list)
    res = await prov.get_price('whatever')
    assert res['success'] is False


def test_config_settings():
    # ensure required attributes exist on settings object
    from config import settings

    assert hasattr(settings, "smspool_key")
    assert hasattr(settings, "telabot_user")
    assert hasattr(settings, "tv_user")
    assert hasattr(settings, "herosms_key")
    assert hasattr(settings, "smsman_key")
    assert hasattr(settings, "pvadeals_key")


async def _make_resp(status=200, text="", json_data=None):
    # create a dummy response context manager and a session that returns it
    class DummyResp:
        def __init__(self):
            self.status = status
        async def text(self):
            return text
        async def json(self):
            if isinstance(json_data, Exception):
                raise json_data
            return json_data
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummySession:
        def __init__(self, resp):
            self._resp = resp
        def get(self, *args, **kwargs):
            return self._resp
        def post(self, *args, **kwargs):
            return self._resp

    return DummySession(DummyResp())


@pytest.mark.asyncio
async def test_smspool_bad_status(monkeypatch):
    from services.numbers.providers.smspool_provider import SMSPoolProvider
    from services.numbers.core.session_manager import SessionManager

    # craft a response that returns 404 and HTML body
    resp = await _make_resp(status=404, text="<html>not found</html>")
    async def fake_get():
        return resp
    monkeypatch.setattr(SessionManager, "get_session", fake_get)

    prov = SMSPoolProvider()
    result = await prov.get_price("telegram")
    assert result["success"] is False
    assert "status 404" in result["raw"]


@pytest.mark.asyncio
async def test_smspool_nonjson(monkeypatch):
    from services.numbers.providers.smspool_provider import SMSPoolProvider
    from services.numbers.core.session_manager import SessionManager

    # response status 200 but body not JSON
    resp = await _make_resp(status=200, text="<html>oops</html>", json_data=Exception("no json"))
    async def fake_get():
        return resp
    monkeypatch.setattr(SessionManager, "get_session", fake_get)

    prov = SMSPoolProvider()
    result = await prov.get_price("telegram")
    assert result["success"] is False
    assert result["raw"] == "invalid_response"



# verify sms pool uses correct pricing endpoint and form data
@pytest.mark.asyncio
async def test_smspool_endpoint_usage(monkeypatch):
    from services.numbers.providers.smspool_provider import SMSPoolProvider
    from services.numbers.core.session_manager import SessionManager

    called = {}

    class DummyResp:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def json(self):
            # return a minimal list that mimics the real pricing endpoint
            return [{"service": "foo", "price": "1"}]
        async def text(self):
            return "{}"

    class DummySession:
        def post(self, *args, **kwargs):
            called['args'] = args
            called['kwargs'] = kwargs
            return DummyResp()

    async def fake_get_session():
        return DummySession()
    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    prov = SMSPoolProvider()
    await prov.get_price("foo")

    assert called['args'][0].endswith('/request/pricing')
    assert 'data' in called['kwargs'] and 'key' in called['kwargs']['data']


@pytest.mark.asyncio
async def test_smspool_numeric_id(monkeypatch):
    from services.numbers.providers.smspool_provider import SMSPoolProvider
    from services.numbers.core.session_manager import SessionManager

    # service id as int - provider should convert to str to match JSON keys
    service_id = 471
    called = {}

    class DummyResp:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def json(self):
            # list containing one matching service
            return [{"service": service_id, "price": "5.5"}]
        async def text(self):
            return "{}"

    class DummySession:
        def post(self, *args, **kwargs):
            called['args'] = args
            called['kwargs'] = kwargs
            return DummyResp()

    async def fake_get_session():
        return DummySession()

    monkeypatch.setattr(SessionManager, "get_session", fake_get_session)
    prov = SMSPoolProvider()
    res = await prov.get_price(service_id)
    assert res['success'] is True
    assert res['price'] == 5.5
    # ensure post url still correct and we computed with str
    assert called['args'][0].endswith('/request/pricing')

@pytest.mark.asyncio
async def test_smspool_not_found(monkeypatch):
    from services.numbers.providers.smspool_provider import SMSPoolProvider
    from services.numbers.core.session_manager import SessionManager

    # return a list that does not include the requested service
    class DummyResp2:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def json(self):
            return [{"service": "other", "price": "9.9"}]
        async def text(self):
            return "[]"

    class DummySession2:
        def post(self, *args, **kwargs):
            return DummyResp2()

    async def fake_get_session2():
        return DummySession2()
    monkeypatch.setattr(SessionManager, "get_session", fake_get_session2)
    prov = SMSPoolProvider()
    res = await prov.get_price("missing")
    assert res["success"] is False
    assert isinstance(res.get("raw"), list)

@pytest.mark.asyncio
async def test_smspool_country_filter(monkeypatch):
    from services.numbers.providers.smspool_provider import SMSPoolProvider
    from services.numbers.core.session_manager import SessionManager

    # two entries for same service, different country short_name
    service_id = 471
    class DummyResp3:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def json(self):
            return [
                {"service": service_id, "price": "1.0", "country": 1, "short_name": "US"},
                {"service": service_id, "price": "2.0", "country": 2, "short_name": "CA"},
            ]
        async def text(self):
            return "[]"

    class DummySession3:
        def post(self, *args, **kwargs):
            return DummyResp3()

    async def fake_get_session3():
        return DummySession3()
    monkeypatch.setattr(SessionManager, "get_session", fake_get_session3)
    prov = SMSPoolProvider()
    res = await prov.get_price(service_id, country="US")
    assert res["success"] is True
    assert res["price"] == 1.0
    res2 = await prov.get_price(service_id, country="2")
    assert res2["price"] == 2.0

@pytest.mark.asyncio
async def test_telabot_optional_params(monkeypatch):
    from services.numbers.providers.telabot_provider import TelabotProvider

    captured = {}
    async def fake_get(self, params):
        captured['params'] = params.copy()
        return {"message": [{"id": "1", "mdn": "123", "status": "Reserved"}]}

    monkeypatch.setattr(TelabotProvider, "_get", fake_get)
    prov = TelabotProvider()
    await prov.buy_number("serviceX", state="CA", mdn="5551234", areacode="415", markup=50)

    assert captured['params']['cmd'] == 'request'
    assert captured['params']['service'] == 'serviceX'
    assert captured['params']['state'] == 'CA'
    assert captured['params']['mdn'] == '5551234'
    assert captured['params']['areacode'] == '415'
    assert captured['params']['markup'] == 50


@pytest.mark.asyncio
async def test_telabot_get_price_list_response(monkeypatch):
    """When the raw API returns status/message list, get_price should still
    locate the requested service and report a price."""
    from services.numbers.providers.telabot_provider import TelabotProvider

    prov = TelabotProvider()

    async def fake_list():
        return {"status": "ok", "message": [{"name": "WhatsApp", "price": "1.7"}]}

    monkeypatch.setattr(prov, 'list_services', fake_list)
    res = await prov.get_price('WhatsApp')
    assert res['success'] is True
    assert res['price'] == 1.7
    assert res['api_service_name'] == 'WhatsApp'


@pytest.mark.asyncio
async def test_textverified_area_code_fallback(monkeypatch):
    """If TextVerified requires an area code we should transparently try a
    handful of defaults and return the cheapest working price."""
    from services.numbers.providers.textverified_provider import TextVerifiedProvider
    from services.numbers.core.session_manager import SessionManager
    import json

    prov = TextVerifiedProvider()
    # stub auth to always succeed
    async def fake_auth(self):
        return "tok"
    monkeypatch.setattr(TextVerifiedProvider, '_auth', fake_auth)

    # Dummy response/ session classes
    class DummyResp:
        def __init__(self, status, json_data):
            self.status = status
            self._json = json_data
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def text(self):
            return json.dumps(self._json)
        async def json(self):
            return self._json
    class DummySession:
        def __init__(self):
            self.last_payload = None
        def post(self, url, headers=None, json=None):
            self.last_payload = json.copy() if isinstance(json, dict) else json
            # first attempt with areaCode flag False (or missing) is rejected
            if not json.get('areaCode'):
                return DummyResp(400, {"raw_text": "Area code pricing option is required."})
            # any payload with areaCode=True returns a fixed price
            return DummyResp(200, {"price": "2.5"})
    sess = DummySession()
    async def fake_get_session():
        return sess
    monkeypatch.setattr(SessionManager, 'get_session', fake_get_session)

    # first call without state should eventually succeed
    result = await prov.get_price('whatsapp')
    assert result['success'] is True
    assert result['price'] == 2.5
    assert result['api_service_name'] == 'whatsapp'

    # calling with a state code should set the boolean flag and include the code
    sess.last_payload = None
    res2 = await prov.get_price('whatsapp', state='NY')
    assert res2['success'] is True
    assert sess.last_payload is not None
    assert sess.last_payload.get('areaCode') is True
    assert 'specificAreaCode' not in sess.last_payload

    # --- account/balance helpers ------------------------------------------------
    # stub session.get so that get_account() returns a fake balance
    class DummyGetResp(DummyResp):
        def __init__(self, status, json_data):
            super().__init__(status, json_data)
    class DummySession2(DummySession):
        def get(self, url, headers=None, params=None):
            # simply return a successful account payload
            return DummyGetResp(200, {"username": "foo", "currentBalance": 10})
    sess2 = DummySession2()
    async def fake_get_session2():
        return sess2
    monkeypatch.setattr(SessionManager, 'get_session', fake_get_session2)

    acct = await prov.get_account()
    assert acct and acct.get('username') == 'foo'
    bal = await prov.get_balance()
    assert bal == 10.0


def test_service_keyboard_top_and_search(monkeypatch):
    """keyboard should include top services + search + back buttons."""
    from services.numbers.keyboards.core_numbers_kb import service_kb

    # stub the underlying helpers to supply predictable lists
    import utils.services_keyboard as sku
    monkeypatch.setattr(sku, 'load_top_services', lambda: ['one','two','three','four','five','six','seven','eight','nine','ten'])
    monkeypatch.setattr(sku, 'load_full_services', lambda: ['one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve'])

    kb = service_kb()
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [btn.text for btn in buttons]

    assert "One" in texts and "Ten" in texts
    assert any(getattr(btn, "switch_inline_query_current_chat", None) == "service " for btn in buttons)
    assert any(getattr(btn, "callback_data", None) == "flow:country:back" for btn in buttons)


def test_service_keyboard_rental_has_open_button(monkeypatch):
    """Rental keyboard should include SMSPool open rental button for supported countries."""
    from services.numbers.keyboards.core_numbers_kb import service_kb
    import utils.services_keyboard as sku

    monkeypatch.setattr(sku, "load_top_services", lambda: ["one", "two"])
    monkeypatch.setattr(sku, "load_full_services", lambda: ["one", "two", "three"])

    kb = service_kb(num_type="rental", country_code="1")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert f"flow:service:{manager.SMSPOOL_OPEN_RENTAL_SERVICE_KEY}" in callbacks


def test_service_keyboard_rental_hides_open_for_other_countries(monkeypatch):
    from services.numbers.keyboards.core_numbers_kb import service_kb
    import utils.services_keyboard as sku

    monkeypatch.setattr(sku, "load_top_services", lambda: ["one", "two"])
    monkeypatch.setattr(sku, "load_full_services", lambda: ["one", "two", "three"])

    kb = service_kb(num_type="rental", country_code="90")  # Turkey
    first_btn = kb.inline_keyboard[0][0]
    assert first_btn.callback_data != f"flow:service:{manager.SMSPOOL_OPEN_RENTAL_SERVICE_KEY}"


def test_rental_options_keyboard_per_provider_list():
    from services.numbers.keyboards.core_numbers_kb import rental_options_kb

    options = [
        {"provider": "smspool", "duration_label": "1d", "price": 6.0, "count": 17, "provider_note": "US [P1]"},
        {"provider": "smspool", "duration": 48, "price": 8.0, "count": 9},
    ]
    kb = rental_options_kb(options, lang="en")
    rows = kb.inline_keyboard
    assert rows[0][0].callback_data == "rentopt:0"
    assert rows[1][0].callback_data == "rentopt:1"
    all_callbacks = [btn.callback_data for row in rows for btn in row]
    assert "flow:rental_providers:back" in all_callbacks


def test_rental_options_keyboard_herosms_grid_and_sorted():
    from services.numbers.keyboards.core_numbers_kb import rental_options_kb

    options = [
        {"provider": "herosms", "duration": 72, "price": 2.10, "count": 10},   # idx 0
        {"provider": "herosms", "duration": 24, "price": 1.20, "count": 10},   # idx 1
        {"provider": "herosms", "duration": 168, "price": 4.00, "count": 10},  # idx 2
        {"provider": "herosms", "duration": 12, "price": 0.90, "count": 10},   # idx 3
        {"provider": "herosms", "duration": 48, "price": 1.70, "count": 10},   # idx 4
    ]
    kb = rental_options_kb(options, lang="en")
    rows = kb.inline_keyboard

    # Sorted by duration asc: idx 3,1,4,0,2 and shown in 2-column grid.
    assert rows[0][0].callback_data == "rentopt:3"
    assert rows[0][1].callback_data == "rentopt:1"
    assert rows[1][0].callback_data == "rentopt:4"
    assert rows[1][1].callback_data == "rentopt:0"
    assert rows[2][0].callback_data == "rentopt:2"
    all_callbacks = [btn.callback_data for row in rows for btn in row]
    assert "flow:rental_providers:back" in all_callbacks


def test_rental_providers_keyboard_monthly_label():
    from services.numbers.keyboards.core_numbers_kb import rental_providers_kb

    kb = rental_providers_kb(
        [
            {
                "provider": "textverified",
                "avg_price": 8.5,
                "pricing_mode": "monthly",
                "country_label": "US",
            }
        ],
        lang="en",
    )
    first_text = kb.inline_keyboard[0][0].text
    assert "Monthly price (US)" in first_text
    assert "8.50 💲" in first_text


def test_rental_providers_keyboard_shows_testing_visible_unavailable_rows(monkeypatch):
    from services.numbers.keyboards.core_numbers_kb import rental_providers_kb

    from config import settings
    monkeypatch.setattr(settings, "numbers_show_all_providers_for_testing", True)

    kb = rental_providers_kb(
        [
            {
                "provider": "textverified",
                "avg_price": 0.0,
                "pricing_mode": "avg",
                "country_label": "US",
                "testing_visible": True,
                "available_for_buy": False,
                "provider_reason": "provider_balance_low",
            }
        ],
        lang="en",
        provider_options={"textverified": []},
    )
    assert len(kb.inline_keyboard) >= 3
    assert kb.inline_keyboard[0][0].callback_data == "renthead:textverified"


def test_rental_providers_keyboard_hides_unavailable_rows_when_testing_mode_off(monkeypatch):
    from services.numbers.keyboards.core_numbers_kb import rental_providers_kb

    from config import settings

    monkeypatch.setattr(settings, "numbers_show_all_providers_for_testing", False)

    kb = rental_providers_kb(
        [
            {
                "provider": "textverified",
                "avg_price": 0.0,
                "pricing_mode": "avg",
                "country_label": "US",
                "testing_visible": True,
                "available_for_buy": False,
                "provider_reason": "provider_balance_low",
            }
        ],
        lang="en",
        provider_options={"textverified": []},
    )
    assert len(kb.inline_keyboard) == 2
    assert kb.inline_keyboard[0][0].callback_data == "flow:service:back"

@pytest.mark.asyncio
async def test_state_selection_edits_message(monkeypatch):
    """selecting a state should update the existing message instead of sending a new one"""
    from services.numbers.handlers.core_numbers import handle_inline_state_selection
    from aiogram import types

    # dummy bot to capture edit_message_text calls
    class DummyBot:
        def __init__(self):
            self.edited = {}
        async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode=None):
            self.edited = {
                'chat_id': chat_id,
                'message_id': message_id,
                'text': text,
                'kb': reply_markup,
                'parse_mode': parse_mode,
            }
            class R: pass
            return R()

    class DummyMsg:
        def __init__(self):
            self.text = '/select_state_NY'
            self.chat = types.Chat(id=123, type='private')
            self.from_user = types.User(id=1, is_bot=False, first_name='u')
            self.bot = DummyBot()
        async def delete(self):
            pass
        async def answer(self, text, reply_markup=None, parse_mode=None):
            class R: pass
            r = R()
            r.message_id = 999
            return r

    class DummyState:
        def __init__(self):
            self._data = {'last_msg_id': 555}
            self.state = None
        async def get_data(self):
            return self._data
        async def update_data(self, **kw):
            self._data.update(kw)
        async def set_state(self, s):
            self.state = s

    msg = DummyMsg()
    state = DummyState()
    await handle_inline_state_selection(msg, state)
    assert state._data['state'] == 'NY'
    assert msg.bot.edited.get('message_id') == 555
    assert 'Choose a service' in msg.bot.edited.get('text', '')
    assert msg.bot.edited.get('parse_mode') == 'HTML'


@pytest.mark.asyncio
async def test_reseller_id_fallback():
    """Main-bot number orders always use the user itself as reseller_id."""
    import services.numbers.handlers.core_numbers_buy as hb

    rid = await hb._resolve_user_reseller(123, 999)
    assert rid == 123


@pytest.mark.asyncio
async def test_balance_handler_and_topup_removed(monkeypatch):
    """Balance text path works and owner topup action is disabled."""
    from handlers.main_menu import balance_handler
    import handlers.main_menu as menu
    import handlers.admin_services as admin
    from aiogram import types

    class DummyBot:
        async def get_me(self):
            class Me:
                id = 777
            return Me()

    class DummyMsg:
        def __init__(self, text, user_id=42, username='test'):
            self.text = text
            self.from_user = types.User(id=user_id, is_bot=False, first_name='u', username=username)
            self.chat = types.Chat(id=1, type='private')
            self.bot = DummyBot()
            self.reply = ""

        async def answer(self, txt, reply_markup=None):
            self.reply = txt
            class R:
                pass
            r = R()
            r.message_id = 123
            return r

    async def fake_get_user(_uid):
        return {"telegram_id": _uid, "language": "en"}

    async def fake_is_reseller(_uid, bot_id=None):
        return False

    async def fake_resolve(_user_doc, *, bot_id, user_id):
        return 555

    async def fake_user_wallet(_uid, _rid):
        return 7.5

    monkeypatch.setattr(menu, "get_user", fake_get_user)
    monkeypatch.setattr(menu, "is_reseller", fake_is_reseller)
    monkeypatch.setattr(menu, "_resolve_user_reseller", fake_resolve)
    monkeypatch.setattr(menu, "get_user_wallet_balance", fake_user_wallet)

    msg = DummyMsg('/balance', user_id=99, username='abc')
    await balance_handler(msg)
    assert "Your balance is 💲 7.50." in msg.reply

    result = await admin._execute_owner_action(action="topup", payload="@abc 10", actor_id=1)
    assert result == "Unknown action."


def test_telabot_helpers():
    from services.numbers.providers.telabot_provider import TelabotProvider

    prov = TelabotProvider()
    # monkeypatch its _get to return predictable values
    async def fake(params):
        if params.get("cmd") == "list_services":
            return {"foo": {"price": "1.23"}}
        if params.get("cmd") == "balance":
            return {"balance": 42}
        return {}

    import asyncio
    prov._get = fake
    loop = asyncio.get_event_loop()
    assert loop.run_until_complete(prov.list_services()) == {"foo": {"price": "1.23"}}
    assert loop.run_until_complete(prov.get_balance()) == {"balance": 42}


def test_data_wrappers_import():
    # the Python wrapper modules should expose a DATA attribute of the
    # appropriate type; the files themselves are not re-opened in this test.
    from services.numbers.data import (
        smspool_services,
        telabot_services,
        textverified_services,
        service_map,
    )

    assert isinstance(smspool_services.DATA, list)
    assert isinstance(telabot_services.DATA, dict)
    assert isinstance(textverified_services.DATA, list)
    assert isinstance(service_map.DATA, dict)


def test_provider_factory_smsman():
    from services.numbers.provider_factory import ProviderFactory
    from services.numbers.providers.smsman_provider import SMSManProvider

    inst = ProviderFactory.get("smsman")
    assert isinstance(inst, SMSManProvider)

# note: original_get could also be used if needed but manager directly calls ProviderFactory.get


# ---------- inline handler tests -----------------------------------------

class DummyInlineQuery:
    def __init__(self, query):
        self.query = query
        self.results = None
    async def answer(self, results, **kwargs):
        self.results = results


def test_inline_query_limits(monkeypatch):
    # simulate SERVICE_MAP with many entries so search could return >50
    from services.numbers.handlers import numbers_inline

    big_map = {f'k{i}': {'display_name': f'name{i}'} for i in range(100)}
    monkeypatch.setattr(numbers_inline, 'SERVICE_MAP', big_map)

    # blank search_text case (should return first 20)
    iq = DummyInlineQuery('service')
    import asyncio
    asyncio.get_event_loop().run_until_complete(numbers_inline.handle_smart_search(iq))
    assert iq.results is not None
    assert len(iq.results) <= 50

    # non-empty query matching all entries
    iq2 = DummyInlineQuery('service k')
    asyncio.get_event_loop().run_until_complete(numbers_inline.handle_smart_search(iq2))
    assert len(iq2.results) <= 50




