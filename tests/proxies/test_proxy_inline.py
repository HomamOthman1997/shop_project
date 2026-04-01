import os
import sys

sys.path.insert(0, os.getcwd())

from services.proxies.handlers.proxy_inline import (
    _parse_locator_and_search,
    _article,
    _match_index_key,
    _non_any_values,
    _proxy_country_iso,
    _proxy_country_title,
    _proxy_state_code,
)


def test_proxy_country_title_and_iso():
    assert _proxy_country_iso("UNITED STATES") == "US"
    assert _proxy_country_title("UNITED STATES") == "United States 🇺🇸"
    assert _proxy_country_iso("Germany") == "DE"
    assert _proxy_country_title("Germany") == "Germany 🇩🇪"


def test_proxy_country_any_title_and_article_thumbnail():
    assert _proxy_country_iso("Any") == ""
    assert _proxy_country_title("Any") == "Any Country"
    article = _article(
        "pc_test",
        "United States 🇺🇸",
        "Code: US",
        "/proxy_country_us",
        thumb_url="https://flagcdn.com/w80/us.png",
    )
    assert article.title == "United States 🇺🇸"
    assert article.description == "Code: US"
    assert article.thumbnail_url == "https://flagcdn.com/w80/us.png"


def test_proxy_state_code_for_us_states():
    assert _proxy_state_code("UNITED STATES", "California") == "CA"
    assert _proxy_state_code("USA", "Colorado") == "CO"
    assert _proxy_state_code("UNITED STATES", "Massachusett") == "MA"
    assert _proxy_state_code("Canada", "Ontario") == ""


def test_parse_locator_and_search_supports_quoted_country():
    assert _parse_locator_and_search('"UNITED STATES"') == ("UNITED STATES", "")
    assert _parse_locator_and_search('"UNITED STATES" new') == ("UNITED STATES", "new")
    assert _parse_locator_and_search("VU5JVEVEIFNUQVRFUw new") == ("VU5JVEVEIFNUQVRFUw", "new")


def test_non_any_values_filters_placeholder_entries():
    assert _non_any_values(["Any", "California", "", "Nevada"]) == ["California", "Nevada"]


def test_match_index_key_is_case_insensitive():
    mapping = {
        "United States": ["California"],
        "Germany": ["Berlin"],
    }
    assert _match_index_key(mapping, "UNITED STATES") == "United States"
    assert _match_index_key(mapping, "germany") == "Germany"


def test_match_index_key_returns_raw_value_when_not_found():
    mapping = {"United States": ["California"]}
    assert _match_index_key(mapping, "Canada") == "Canada"
