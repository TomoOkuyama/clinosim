"""Country-only algorithms live in their country package and are selected by
the country profile (Issue #3194; docs/design-guides/country-profile-spec.md §4).
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim import countries
from clinosim.country_profile import IMPLEMENTATION_MODULES, country_profile, implementation, load_profile_data

pytestmark = pytest.mark.unit

# Every implementation name the JP profile selects that no other profile uses
# is JP-only and must come from clinosim.countries.jp.
JP_ONLY = {
    "identity_provider": "jp",
    "triage_scale": "jtas",
    "lab_coding": "jp_clins",
    "drug_system": "jp_code_format",
    "drug_order_code": "jp_route_product",
    "copay_rule": "jp_age_income",
}


def test_countries_package_keeps_its_api() -> None:
    from clinosim.countries import country_code, country_slot, is_jp, lang_for

    assert countries.__file__.endswith("countries/__init__.py")
    assert (is_jp("jp"), country_code("japan"), country_slot("JP"), lang_for("JP")) == (True, "JP", "jp", "ja")


@pytest.mark.parametrize(("kind", "name"), sorted(JP_ONLY.items()))
def test_jp_only_implementations_live_in_the_jp_package(kind: str, name: str) -> None:
    assert country_profile("JP").implementation(kind) == name
    assert name not in {country_profile("US").implementation(kind), load_profile_data("US")["implementations"][kind]}
    fn = implementation(kind, "JP")
    assert fn.__module__.startswith("clinosim.countries.jp."), fn.__module__


def test_country_package_modules_are_registered_explicitly() -> None:
    import pkgutil

    import clinosim.countries.jp as jp

    modules = {f"clinosim.countries.jp.{m.name}" for m in pkgutil.iter_modules(jp.__path__)}
    assert modules <= set(IMPLEMENTATION_MODULES)


def test_protocol_drug_order_code() -> None:
    from clinosim.modules.order.engine import protocol_drug_order_code, protocol_drug_order_code_system

    spec = {"drug": "ceftriaxone", "route": "IV"}
    us = protocol_drug_order_code(spec, "US")
    jp = protocol_drug_order_code(spec, "JP")
    assert us.isdigit() and protocol_drug_order_code_system(spec, "US") == "rxnorm"
    assert jp and not jp.isdigit() and protocol_drug_order_code_system(spec, "JP") == "yj"
    assert protocol_drug_order_code({"drug": "no-such-drug"}, "US") == ""


def test_copay_rules() -> None:
    us = implementation("copay_rule", "US")
    jp = implementation("copay_rule", "JP")
    assert us(date(1950, 1, 1), date(2025, 4, 1), "P", "medicare", "US") == 30
    assert us(None, date(2025, 4, 1), "P", "late_elderly", "US") == 10
    # JP: a 4-year-old pays 20% before school entry; without a birth date the
    # category rate applies.
    assert jp(date(2021, 6, 1), date(2025, 6, 1), "P", "national", "JP") == 20
    assert jp(None, date(2025, 6, 1), "P", "late_elderly", "JP") == 10
    assert jp(None, date(2025, 6, 1), "P", "national", "JP") == 30
