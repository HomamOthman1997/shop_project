from services.numbers.provider_quality import (
    provider_quality,
    provider_quality_rows,
    provider_recommendation_bonus,
)


def test_owner_provider_quality_classification():
    assert provider_quality("smspool").tier == "excellent"
    assert provider_quality("textverified").tier == "excellent"
    assert provider_quality("herosms").tier == "excellent"
    assert provider_quality("telabot").tier == "excellent"
    assert provider_quality("nonvoip").tier == "excellent"
    assert provider_quality("pvadeals").tier == "trusted"
    assert provider_quality("vaksms").tier == "mixed"
    assert provider_quality("pvapins").tier == "mixed"
    assert provider_quality("smsready").tier == "unclassified"


def test_provider_quality_bonus_keeps_unclassified_below_tested_sources():
    assert provider_recommendation_bonus("telabot") > provider_recommendation_bonus("smsready")
    assert provider_recommendation_bonus("pvadeals") > provider_recommendation_bonus("pvapins")


def test_telegram_quality_bonus_is_service_specific():
    assert provider_recommendation_bonus("textverified") > 0
    assert provider_recommendation_bonus("textverified", "telegram") < 0
    assert provider_recommendation_bonus("telabot", "telegram") > provider_recommendation_bonus("textverified", "telegram")


def test_provider_quality_rows_include_smsready_as_unclassified():
    rows = {row["provider"]: row for row in provider_quality_rows()}
    assert rows["smsready"]["tier"] == "unclassified"
    assert rows["telabot"]["tier"] == "excellent"
