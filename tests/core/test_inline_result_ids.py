import os
import sys

sys.path.insert(0, os.getcwd())

from services.numbers.handlers.numbers_inline import _safe_result_id


def test_safe_result_id_is_within_telegram_limit():
    very_long_key = "swagbucksinboxdollarsinboxpoundsmypointsysensenoonesadgatesurveytadapollpay"
    rid = _safe_result_id("ser", very_long_key)
    assert len(rid.encode("utf-8")) <= 64


def test_safe_result_id_is_stable_for_same_input():
    source = "twitterx"
    assert _safe_result_id("ser", source) == _safe_result_id("ser", source)
