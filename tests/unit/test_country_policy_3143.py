"""Code-system policy, the country code / slot, the supported-country list and
country features come from the country profile (Issue #3143;
docs/design-guides/country-profile-spec.md §7 steps 4-5).

A third, test-only country profile (``XX``) must fail loudly where its data
is missing instead of silently becoming the US.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

import clinosim.country_profile as cp
from clinosim.codes import system_key_for
from clinosim.countries import country_code, country_slot
from clinosim.country_profile import country_profile, supported_countries

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("kind", cp.CODE_SYSTEM_KINDS)
def test_system_key_is_the_profile_code_system(country: str, kind: str) -> None:
    assert system_key_for(kind, country) == country_profile(country).code_system(kind)


def test_system_key_unknown_kind_raises() -> None:
    with pytest.raises(KeyError):
        system_key_for("imaging", "US")


@pytest.mark.parametrize(
    ("spelling", "code", "slot", "legacy"),
    [("US", "US", "us", "us"), ("us", "US", "us", "us"), ("JP", "JP", "jp", "japan"), ("japan", "JP", "jp", "japan")],
)
def test_country_code_and_slot(spelling: str, code: str, slot: str, legacy: str) -> None:
    assert country_code(spelling) == code
    assert country_slot(spelling) == slot
    assert country_slot(spelling, scheme="legacy_japan") == legacy


@pytest.mark.parametrize("unknown", ["FR", ""])
def test_unknown_country_is_not_the_us(unknown: str) -> None:
    with pytest.raises(KeyError):
        country_code(unknown)
    with pytest.raises(KeyError):
        country_slot(unknown)
    with pytest.raises(KeyError):
        system_key_for("lab", unknown)


def test_care_level_and_tdap_follow_the_profile_features() -> None:
    from clinosim.modules.care_level.engine import load_rates

    assert load_rates("JP") and load_rates("US") == {}
    assert country_profile("JP").feature("care_level") and not country_profile("US").feature("care_level")


@pytest.fixture
def third_country(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A locale tree with the real profiles plus a test-only ``xx`` profile
    that inherits every root default and carries no other locale data."""
    real = cp._LOCALE
    for name in ("_root", "us", "jp"):
        (tmp_path / name).mkdir()
        shutil.copy(real / name / "country.yaml", tmp_path / name / "country.yaml")
    (tmp_path / "xx").mkdir()
    (tmp_path / "xx" / "country.yaml").write_text("code: XX\n", encoding="utf-8")
    monkeypatch.setattr(cp, "_LOCALE", tmp_path)
    _clear()
    yield "XX"
    monkeypatch.setattr(cp, "_LOCALE", real)
    _clear()


def _clear() -> None:
    from clinosim import countries

    cp.supported_countries.cache_clear()
    cp._profile.cache_clear()
    countries.country_code.cache_clear()


def test_third_country_is_supported_and_keeps_its_own_code(third_country: str) -> None:
    assert supported_countries() == ("JP", "US", "XX")
    assert country_code(third_country) == "XX"
    assert country_slot(third_country) == "xx"
    # Root defaults, not a US copy: the root code systems are what it inherits.
    assert system_key_for("diagnosis", third_country) == "icd-10-cm"


def test_third_country_fails_loudly_where_its_data_is_missing(third_country: str) -> None:
    from clinosim.locale.loader import load_care_practice, load_naming_rules

    with pytest.raises(FileNotFoundError):
        load_care_practice.__wrapped__(third_country)
    with pytest.raises(KeyError):
        load_naming_rules.__wrapped__(third_country)
