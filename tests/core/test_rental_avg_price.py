import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.numbers.handlers.core_numbers import _avg_price, _monthly_price


def test_avg_price_uses_1d_3d_7d_only():
    options = [
        {"duration": 24, "price": 1.0},
        {"duration": 72, "price": 3.0},
        {"duration": 168, "price": 7.0},
        {"duration": 48, "price": 2.0},  # must be ignored in target average
    ]
    avg, count, is_target = _avg_price(options)
    assert is_target is True
    assert count == 3
    assert avg == pytest.approx((1.0 + 3.0 + 7.0) / 3.0)


def test_avg_price_takes_min_per_target_duration():
    options = [
        {"duration": 24, "price": 2.2},
        {"duration": 24, "price": 1.8},
        {"duration": 72, "price": 4.5},
        {"duration": 72, "price": 4.0},
        {"duration": 168, "price": 8.0},
        {"duration": 168, "price": 7.5},
    ]
    avg, count, is_target = _avg_price(options)
    assert is_target is True
    assert count == 3
    assert avg == pytest.approx((1.8 + 4.0 + 7.5) / 3.0)


def test_avg_price_falls_back_when_target_durations_missing():
    options = [
        {"duration": 48, "price": 1.2},
        {"duration": 96, "price": 2.4},
    ]
    avg, count, is_target = _avg_price(options)
    assert is_target is False
    assert count == 2
    assert avg == pytest.approx((1.2 + 2.4) / 2.0)


def test_monthly_price_prefers_direct_30d():
    options = [
        {"duration": 24, "price": 1.0},
        {"duration": 720, "price": 9.9},
        {"duration": 720, "price": 8.8},
    ]
    monthly, ok = _monthly_price(options)
    assert ok is True
    assert monthly == pytest.approx(8.8)


def test_monthly_price_missing():
    options = [
        {"duration": 24, "price": 1.0},
        {"duration": 72, "price": 3.0},
    ]
    monthly, ok = _monthly_price(options)
    assert ok is False
    assert monthly == 0.0
