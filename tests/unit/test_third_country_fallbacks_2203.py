"""A third country is not silently treated as the US (Issue #2203)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.modules.population import mortality

pytestmark = pytest.mark.unit

_LOCALE = Path(__file__).resolve().parents[2] / "clinosim" / "locale"


def test_country_with_its_own_life_table_block_uses_it(monkeypatch) -> None:
    table = {
        "annual_mortality_qx": {"us": {"male": {80: 0.08}}, "de": {"male": {80: 0.05}}},
        "community_death_share": {"us": 0.72, "de": 0.6},
    }
    monkeypatch.setattr(mortality, "_life_table", lambda: table)
    assert mortality.qx_for("DE", "M", 82) == 0.05
    assert mortality.community_death_share("DE") == 0.6


def test_country_without_a_block_falls_back_to_us(monkeypatch) -> None:
    table = {"annual_mortality_qx": {"us": {"male": {80: 0.08}}}, "community_death_share": {"us": 0.72}}
    monkeypatch.setattr(mortality, "_life_table", lambda: table)
    assert mortality.qx_for("DE", "M", 82) == 0.08


def test_us_core_profiles_only_for_the_us() -> None:
    from clinosim.modules.output.fhir_r4 import builder

    src = Path(builder.__file__).read_text()
    assert "elif is_us(country):" in src and "elif is_us(ctx.country):" in src


def test_template_demographics_uses_the_loader_schema() -> None:
    us = yaml.safe_load((_LOCALE / "us" / "demographics.yaml").read_text())
    tpl_text = (_LOCALE / "_template" / "demographics.yaml").read_text()
    tpl = yaml.safe_load(tpl_text)
    unknown = set(tpl) - set(us)
    assert not unknown, f"template keys no loader reads: {sorted(unknown)}"
    for required in (
        "age_distribution",
        "sex_ratio",
        "blood_type",
        "chronic_prevalence",
        "disease_incidence",
        "ed_visit_not_admitted",
        "care_seeking",
        "lifestyle_distribution",
        "physiology",
    ):
        assert required in tpl, required
