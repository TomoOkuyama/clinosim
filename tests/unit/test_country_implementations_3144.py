"""Country algorithms are named implementations selected by the country
profile (Issue #3144; docs/design-guides/country-profile-spec.md §4, §7 step 6).
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from clinosim.codes.drugs import drug_system_key
from clinosim.codes.procedures import country_procedure_code, procedure_code
from clinosim.country_profile import (
    CountryProfile,
    country_profile,
    implementation,
    load_profile_data,
    validate_implementations,
)
from clinosim.modules.identity.providers.jp import JPIdentityProvider
from clinosim.modules.identity.providers.us import USIdentityProvider
from clinosim.modules.identity.registry import get_provider
from clinosim.modules.output.fhir_r4.labs.coding_strategy import (
    CoreLaboStrategy,
    LegacyLOINCStrategy,
    UncodedStrategy,
    select_lab_coding_strategy,
)

pytestmark = pytest.mark.unit

KINDS = {
    "identity_provider": {"US": "us", "JP": "jp"},
    "triage_scale": {"US": "esi", "JP": "jtas"},
    "lab_coding": {"US": "loinc", "JP": "jp_clins"},
    "drug_system": {"US": "profile_code_system", "JP": "jp_code_format"},
}


@pytest.mark.parametrize("kind", sorted(KINDS))
@pytest.mark.parametrize("country", ["US", "JP"])
def test_profiles_select_the_named_implementation(kind: str, country: str) -> None:
    assert country_profile(country).implementation(kind) == KINDS[kind][country]
    assert callable(implementation(kind, country))


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_an_unregistered_name_fails_at_profile_load(kind: str) -> None:
    data = load_profile_data("US")
    data["implementations"] = {**data["implementations"], kind: "no_such_implementation"}
    with pytest.raises(ValueError, match="unregistered"):
        validate_implementations(CountryProfile.model_validate(data))


def test_an_undeclared_kind_is_rejected() -> None:
    data = load_profile_data("US")
    data["implementations"] = {**data["implementations"], "teleporter": "x"}
    with pytest.raises(ValidationError):
        CountryProfile.model_validate(data)


def test_identity_provider() -> None:
    assert isinstance(get_provider("US"), USIdentityProvider)
    assert isinstance(get_provider("jp"), JPIdentityProvider)
    assert get_provider("JP") is get_provider("japan")
    with pytest.raises(KeyError):
        get_provider("FR")


def test_triage_scale() -> None:
    from clinosim.modules.triage.engine import triage_scale

    assert triage_scale("US") == "ESI"
    assert triage_scale("japan") == "JTAS"


def test_lab_coding_strategy() -> None:
    assert isinstance(select_lab_coding_strategy("CRP", "US"), LegacyLOINCStrategy)
    assert isinstance(select_lab_coding_strategy("CRP", "JP"), CoreLaboStrategy)
    assert isinstance(select_lab_coding_strategy("no-such-analyte", "JP"), UncodedStrategy)


def test_drug_system_key() -> None:
    assert drug_system_key("1234567", "US") == "rxnorm"
    # JP dispatches on the code format (YJ 12 characters).
    assert drug_system_key("2149039F1022", "JP") == "yj"


def test_procedure_code_by_code_system() -> None:
    assert country_procedure_code("US", {"cpt": "31500", "k-codes": "J044"}) == "31500"
    assert country_procedure_code("JP", {"cpt": "31500", "k-codes": "J044"}) == "J044"
    assert procedure_code("no_such_type", "JP") == ""


def test_triage_draw_unchanged_by_scale() -> None:
    from clinosim.modules.triage.engine import pick_triage_level

    a = pick_triage_level("moderate", "ESI", np.random.default_rng(3))
    b = pick_triage_level("moderate", "JTAS", np.random.default_rng(3))
    assert a == b
