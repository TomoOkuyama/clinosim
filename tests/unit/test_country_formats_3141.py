"""Language, timezone, name / address / phone formats and identifiers come
from the country profile and locale YAML (Issue #3141;
docs/design-guides/country-profile-spec.md §7 step 2)."""

from __future__ import annotations

import re

import numpy as np
import pytest

from clinosim.country_profile import country_profile
from clinosim.locale.loader import load_addresses
from clinosim.locale.patterns import draw_pattern, format_hash_pattern
from clinosim.modules.output.fhir_r4.lib.common import build_address
from clinosim.modules.output.fhir_r4.lib.fhir_time import tz_suffix_for_country

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("country", "tag"), [("US", "en-US"), ("JP", "ja-JP")])
def test_language_tag(country: str, tag: str) -> None:
    assert country_profile(country).language_tag == tag


@pytest.mark.parametrize("country", ["US", "JP"])
def test_timezone_suffix_is_the_profile_timezone(country: str) -> None:
    assert tz_suffix_for_country(country) == country_profile(country).timezone


def test_name_order() -> None:
    assert country_profile("US").formats.name_parts("Smith", "John") == ("John", "Smith")
    assert country_profile("JP").formats.name_parts("田中", "太郎") == ("田中", "太郎")


def test_physician_prefix() -> None:
    assert country_profile("US").formats.physician_name_prefix == "Dr."
    assert country_profile("JP").formats.physician_name_prefix == ""


def test_draw_pattern_reproduces_the_rng_stream() -> None:
    pattern = {
        "fields": [{"name": "a", "choice": "pool"}, {"name": "n", "integer": [1, 500]}],
        "format": "{n} {a}",
    }
    rng, ref = np.random.default_rng(7), np.random.default_rng(7)
    out = draw_pattern(pattern, {"pool": ["X", "Y", "Z"]}, rng)
    a = str(ref.choice(["X", "Y", "Z"]))
    n = int(ref.integers(1, 500))
    assert out == f"{n} {a}"
    assert rng.random() == ref.random()  # same number of draws


def test_draw_pattern_case_selected_by_a_drawn_value() -> None:
    pattern = {
        "fields": [{"name": "k", "choice": "keys"}],
        "then": {
            "by": "k",
            "cases": {
                "a": {"format": "A{k}"},
                "default": {"fields": [{"name": "n", "integer": [5, 6]}], "format": "{k}{n}"},
            },
        },
    }
    assert draw_pattern(pattern, {"keys": ["a"]}, np.random.default_rng(0)) == "Aa"
    assert draw_pattern(pattern, {"keys": ["b"]}, np.random.default_rng(0)) == "b5"


PHONE_SHAPES = {
    "US": {
        "mobile": r"\(\d{3}\) \d{3}-\d{4}",
        "landline": r"\(\d{3}\) \d{3}-\d{4}",
        "staff_work": r"\(\d{3}\) \d{3}-\d{4}",
    },
    "JP": {
        "mobile": r"0[789]0-\d{4}-\d{4}",
        "landline": r"(03-\d{4}|0\d{1,2}-\d{3})-\d{4}",
        "staff_work": r"03-\d{4}-\d{4}",
    },
}


@pytest.mark.parametrize("country", ["US", "JP"])
def test_phone_patterns_have_the_country_shape(country: str) -> None:
    phone = load_addresses(country)["phone"]
    rng = np.random.default_rng(42)
    for kind, shape in PHONE_SHAPES[country].items():
        for _ in range(50):
            assert re.fullmatch(shape, draw_pattern(phone[kind], phone, rng)), kind


def test_ward_phone_hash_pattern() -> None:
    h = 123_456_789
    assert format_hash_pattern(load_addresses("JP")["phone"]["ward"], h) == "03-2345-6789"
    assert format_hash_pattern(load_addresses("US")["phone"]["ward"], h) == "(555) 345-6789"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_street_and_apartment_lines(country: str) -> None:
    data = load_addresses(country)
    rng = np.random.default_rng(1)
    street = draw_pattern(data["street_line"], data, rng)
    apartment = draw_pattern(data["apartment_line"], data, rng)
    if country == "US":
        assert re.fullmatch(r"\d{1,3} .+", street) and re.fullmatch(r", Apt \d{1,2}", apartment)
    else:
        assert re.fullmatch(r".+\d丁目\d{1,2}-\d{1,2}", street) and re.fullmatch(r" .+\d{3,4}", apartment)


def test_fhir_address_shape() -> None:
    us = build_address({"state": "MA", "city": "Boston", "line1": "1 Main St", "postal_code": "02101"}, "US")
    assert us is not None
    assert us["line"] == ["1 Main St"] and us["state"] == "MA" and "text" not in us
    jp = build_address(
        {"state": "東京都", "city": "世田谷区", "line1": "本町1丁目2-3", "postal_code": "154-0001"}, "JP"
    )
    assert jp is not None
    assert jp["line"] == ["東京都世田谷区本町1丁目2-3"] and jp["text"] == jp["line"][0]
    assert jp["state"] == "13"  # JIS X 0401
