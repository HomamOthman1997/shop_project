from services.numbers.shared.temp_order import _provider_temp_wait_timeout_sec


def test_provider_temp_wait_timeout_defaults_to_global_timeout():
    assert _provider_temp_wait_timeout_sec("telabot") == 900


def test_provider_temp_wait_timeout_uses_pvadeals_twenty_minute_timeout():
    assert _provider_temp_wait_timeout_sec("pvadeals") == 1200


def test_provider_temp_wait_timeout_keeps_longer_provider_timeout():
    assert _provider_temp_wait_timeout_sec("pvadeals", 1800) == 1800
