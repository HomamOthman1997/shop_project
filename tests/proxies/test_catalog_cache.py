import os
import sys

sys.path.insert(0, os.getcwd())

from services.proxies.catalog_cache import build_index, decode_token, encode_token, filter_offers


def test_encode_decode_roundtrip():
    original = "New York"
    token = encode_token(original)
    assert token
    assert decode_token(token) == original


def test_build_index_and_filter():
    offers = [
        {"country": "US", "state": "NY", "city": "New York", "price": 3.0},
        {"country": "US", "state": "CA", "city": "San Diego", "price": 2.0},
        {"country": "TR", "state": "Istanbul", "city": "Istanbul", "price": 1.0},
    ]

    index = build_index(offers)
    assert index["countries"] == ["TR", "US"]
    assert index["states_by_country"]["US"] == ["CA", "NY"]
    assert index["cities_by_country_state"][("US", "NY")] == ["New York"]

    us_only = filter_offers(offers, country="US")
    assert len(us_only) == 2

    ny_only = filter_offers(offers, country="US", state="NY")
    assert len(ny_only) == 1
    assert ny_only[0]["city"] == "New York"

    none = filter_offers(offers, country="US", state="NY", city="Los Angeles")
    assert none == []
