"""Country profile: validated, root-merged, cached (Issue #3140; docs/design-guides/country-profile-spec.md §3-§4).

Step 1 of the migration: the profiles hold today's behaviour and nothing in
production reads them yet, so these tests pin each value to the code that
decides it today.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clinosim.codes import system_key_for, system_keys
from clinosim.countries import is_jp, is_us, lang_for
from clinosim.country_profile import (
    CODE_SYSTEM_KINDS,
    CountryProfile,
    country_profile,
    deep_merge,
    implementation,
    load_profile_data,
    register_implementation,
    supported_countries,
    validate_implementations,
)
from clinosim.datafiles import load_data_yaml
from clinosim.modules.output.fhir_r4.lib.fhir_time import tz_suffix_for_country

pytestmark = pytest.mark.unit

COUNTRIES = ("US", "JP")


def test_supported_countries_are_the_profile_directories() -> None:
    assert supported_countries() == ("JP", "US")


@pytest.mark.parametrize("spelling", ["US", "us", " us "])
def test_country_code_is_normalised(spelling: str) -> None:
    assert country_profile(spelling) is country_profile("US")


def test_japan_spellings_resolve_to_jp() -> None:
    assert country_profile("japan").code == "JP" and country_profile("jp").code == "JP"


@pytest.mark.parametrize("unknown", ["FR", "", "_root", "_template"])
def test_an_unknown_country_raises(unknown: str) -> None:
    with pytest.raises(KeyError):
        country_profile(unknown)


def test_deep_merge_merges_maps_and_replaces_lists_and_scalars() -> None:
    root = {"a": 1, "m": {"x": 1, "y": {"z": 1}}, "l": [1, 2]}
    over = {"a": 2, "m": {"y": {"w": 2}}, "l": [3]}
    assert deep_merge(root, over) == {"a": 2, "m": {"x": 1, "y": {"z": 1, "w": 2}}, "l": [3]}
    assert root == {"a": 1, "m": {"x": 1, "y": {"z": 1}}, "l": [1, 2]}  # inputs untouched


def test_unknown_keys_are_rejected() -> None:
    data = load_profile_data("US")
    with pytest.raises(ValidationError):
        CountryProfile.model_validate({**data, "colour": "blue"})
    with pytest.raises(ValidationError):
        CountryProfile.model_validate({**data, "features": {**data["features"], "teleportation": True}})


def test_an_unknown_code_system_is_rejected() -> None:
    data = load_profile_data("US")
    with pytest.raises(ValidationError):
        CountryProfile.model_validate({**data, "code_systems": {**data["code_systems"], "lab": "no-such-system"}})


@pytest.mark.parametrize("country", COUNTRIES)
def test_language_and_timezone_match_today(country: str) -> None:
    p = country_profile(country)
    assert p.language == lang_for(country)
    assert p.timezone == tz_suffix_for_country(country)


@pytest.mark.parametrize("country", COUNTRIES)
@pytest.mark.parametrize("kind", CODE_SYSTEM_KINDS)
def test_code_systems_match_today_and_exist(country: str, kind: str) -> None:
    key = country_profile(country).code_system(kind)
    assert key == system_key_for(kind, country)
    assert key in system_keys()


def test_fhir_profiles() -> None:
    assert country_profile("US").uses("us_core") and not country_profile("US").uses("jp_core")
    jp = country_profile("JP")
    assert all(jp.uses(p) for p in ("jp_core", "jp_clins", "jp_echeckup")) and not jp.uses("us_core")
    with pytest.raises(KeyError):
        jp.uses("uk_core")


@pytest.mark.parametrize("country", COUNTRIES)
def test_features_match_today(country: str) -> None:
    p = country_profile(country)
    assert p.feature("care_level") is is_jp(country)  # enrichers.register_builtin_enrichers
    assert p.feature("maternal_tdap") is is_us(country)  # immunization.generate_pregnancy_tdap
    assert p.feature("health_checkup") is True
    with pytest.raises(KeyError):
        p.feature("teleportation")


@pytest.mark.parametrize("country", COUNTRIES)
def test_formats_match_the_formatting_yaml(country: str) -> None:
    fmt = load_data_yaml(f"clinosim/locale/{country.lower()}/formatting.yaml")
    p = country_profile(country)
    for key in ("name_order", "date_format", "time_format", "datetime_format"):
        assert getattr(p.formats, key) == fmt[key], key


@pytest.mark.parametrize("country", COUNTRIES)
def test_egfr_implementations_match_the_equation_yaml(country: str) -> None:
    eq = load_data_yaml(f"clinosim/locale/{country.lower()}/egfr_equation.yaml")
    p = country_profile(country)
    assert p.implementation("egfr_equation") == eq["adult"]["type"]
    assert p.implementation("pediatric_egfr_equation") == eq["pediatric"]["type"]


@pytest.mark.parametrize("country", COUNTRIES)
def test_implementation_returns_the_registered_callable(country: str) -> None:
    from clinosim.modules.physiology import egfr

    adult = egfr.egfr_equations(country)["adult"]
    fn = implementation("egfr_equation", country)
    assert fn(1.0, 60, "M", adult) == egfr._adult(1.0, 60, "M", adult)


def test_a_profile_naming_an_unregistered_implementation_fails() -> None:
    data = load_profile_data("JP")
    data["implementations"] = {**data["implementations"], "egfr_equation": "no_such_equation"}
    with pytest.raises(ValueError, match="no_such_equation"):
        validate_implementations(CountryProfile.model_validate(data))


def test_registering_a_name_twice_fails() -> None:
    with pytest.raises(ValueError):
        register_implementation("egfr_equation", "jsn")(lambda *a: 0.0)
