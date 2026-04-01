import os
import sys

sys.path.insert(0, os.getcwd())

from utils.translations import t, translations


def test_translations_load_expected_languages():
    assert sorted(translations.keys()) == ["ar", "en"]
    assert len(translations["en"]) >= 300
    assert len(translations["ar"]) >= 300


def test_translation_samples_are_human_readable():
    assert "Add Bot To Channel" in t("en", "add_bot_to_channel")
    assert "إضافة البوت" in t("ar", "add_bot_to_channel")
    assert "Back" in t("en", "back")
    assert "رجوع" in t("ar", "back")
    assert "Numbers" in t("en", "btn_numbers")
    assert "الأرقام" in t("ar", "btn_numbers")
    assert "بانتظار وصول الكود" in t("ar", "temp_waiting_code")
    assert "بحث البروكسي" in t("ar", "proxy_panel_title")


def test_numbers_purchase_notices_arabic_are_not_corrupted():
    refunded = t("ar", "numbers_purchase_refunded_notice")
    confirmed = t("ar", "numbers_purchase_charge_confirmed_notice")

    assert "????" not in refunded
    assert "????" not in confirmed
    assert "الرصيد الحالي" in refunded
    assert "الرصيد الحالي" in confirmed


def test_numbers_us_state_prompt_arabic_is_not_corrupted():
    prompt = t("ar", "numbers_us_state_prompt")

    assert "????" not in prompt
    assert "الولايات المتحدة" in prompt
    assert "Any State" in prompt
