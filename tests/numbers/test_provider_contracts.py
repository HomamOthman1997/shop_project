import pytest

from services.numbers.providers.error_normalizer import normalize_provider_error
from services.numbers.providers.herosms_provider import HeroSMSProvider
from services.numbers.providers.pvapins_provider import PVAPinsProvider
from services.numbers.providers.smsready_provider import SMSReadyProvider
from services.numbers.providers.nonvoip_provider import NonVoipProvider
from services.numbers.providers.smspool_provider import SMSPoolProvider
from services.numbers.providers.telabot_provider import TelabotProvider
from services.numbers.providers.textverified_provider import TextVerifiedProvider


def test_provider_contract_methods_exist():
    providers = [
        SMSPoolProvider(),
        TextVerifiedProvider(),
        HeroSMSProvider(),
        NonVoipProvider(),
        SMSReadyProvider(),
        PVAPinsProvider(),
        TelabotProvider(),
    ]
    for provider in providers:
        assert hasattr(provider, "get_price")
        assert hasattr(provider, "buy_number")
        assert hasattr(provider, "get_sms")
        assert hasattr(provider, "cancel")


@pytest.mark.parametrize(
    ("raw", "expected_code"),
    [
        ({"errorDescription": "Out of stock or unavailable."}, "OUT_OF_STOCK"),
        ({"message": "Insufficient balance, the price is: 0.48"}, "PROVIDER_BALANCE_LOW"),
        ({"error_msg": "Wrong token!"}, "AUTH_ERROR"),
        ("temporarily unavailable", "TEMPORARY_FAILURE"),
    ],
)
def test_error_normalizer_codes(raw, expected_code):
    normalized = normalize_provider_error(raw)
    assert normalized["code"] == expected_code
    assert isinstance(normalized["message"], str)
    assert normalized["message"]
