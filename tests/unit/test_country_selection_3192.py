"""The healthcare-system file, the health-checkup feature and the country
types come from the country profile (Issue #3192;
docs/design-guides/country-profile-spec.md §3)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

import clinosim.country_profile as cp
from clinosim.country_profile import country_profile

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("country", "stem"), [("US", "us"), ("JP", "japan"), ("jp", "japan")])
def test_healthcare_system_file_is_named_by_the_profile(country: str, stem: str) -> None:
    from clinosim.modules.healthcare_system.loader import load_healthcare_config

    assert country_profile(country).healthcare_system == stem
    assert load_healthcare_config(country).country == country_profile(country).code


def test_health_checkup_feature_matches_the_enricher() -> None:
    from types import SimpleNamespace

    from clinosim.simulator.enrichers import _ENRICHERS, register_builtin_enrichers

    register_builtin_enrichers()
    _health_checkup_enabled = _ENRICHERS["health_checkup"].enabled

    assert country_profile("JP").feature("health_checkup")
    assert not country_profile("US").feature("health_checkup")

    def cfg(country: str) -> SimpleNamespace:
        return SimpleNamespace(country=country, module_enabled=lambda name: True)

    assert _health_checkup_enabled(cfg("JP"))
    assert not _health_checkup_enabled(cfg("US"))
    assert not _health_checkup_enabled(cfg(""))
    assert not _health_checkup_enabled(None)


@pytest.fixture
def third_country(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
    from clinosim.modules.healthcare_system.loader import load_healthcare_config

    cp.supported_countries.cache_clear()
    cp._profile.cache_clear()
    countries.country_code.cache_clear()
    load_healthcare_config.cache_clear()


def test_third_country_passes_the_country_types(third_country: str) -> None:
    from clinosim.modules.encounter.protocol import ScreeningLab
    from clinosim.types.config import PatientProfile

    assert PatientProfile(profile_id="p", disease_id="d", country="XX").country == "XX"
    assert ScreeningLab(test="CBC", age="0-17", countries=["XX", "JP"]).countries == ["XX", "JP"]
    with pytest.raises(ValidationError):
        PatientProfile(profile_id="p", disease_id="d", country="FR")


def test_third_country_without_a_healthcare_system_fails_loudly(third_country: str) -> None:
    from clinosim.modules.healthcare_system.loader import load_healthcare_config

    assert country_profile(third_country).healthcare_system is None
    with pytest.raises(KeyError):
        load_healthcare_config(third_country)


def test_eval_locale_axis_detects_a_profiled_country(third_country: str) -> None:
    from clinosim.eval.axes.locale import _detect_country_from_cohort

    assert _detect_country_from_cohort(object(), "xx") == "XX"  # type: ignore[arg-type]
