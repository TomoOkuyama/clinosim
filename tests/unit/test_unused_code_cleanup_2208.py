"""Unused code and configuration found in the docs audit (Issue #2208)."""

from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.unit


def test_metadata_records_the_simulation_period() -> None:
    from clinosim.simulator.engine import run_beta
    from clinosim.types.config import SimulatorConfig

    ds = run_beta(
        SimulatorConfig(country="US", catchment_population=50, random_seed=3, time_range=("2025-01", "2025-02"))
    )
    assert ds.metadata.simulation_period_start == date(2025, 1, 1)
    assert ds.metadata.simulation_period_end == date(2025, 2, 28)


def test_ckd_exclusion_prefixes_are_unique() -> None:
    from clinosim.modules.diagnosis.lab_derived_dx import CKD_STAGE_45_ICD_PREFIXES

    assert len(CKD_STAGE_45_ICD_PREFIXES) == len(set(CKD_STAGE_45_ICD_PREFIXES))


def test_healthcare_config_carries_only_read_fields() -> None:
    from clinosim.types.config import HealthcareSystemConfig

    assert set(HealthcareSystemConfig.model_fields) == {"country", "lab_frequency_multiplier"}


def test_validate_runs_the_consistency_checks(monkeypatch, capsys) -> None:
    import sys

    from clinosim.modules.validator import consistency
    from clinosim.simulator import cli

    called = {}

    def fake(dataset, country="US"):
        called["country"] = country
        return consistency.ConsistencyReport()

    monkeypatch.setattr(consistency, "run_consistency_checks", fake)
    monkeypatch.setattr(sys, "argv", ["clinosim", "validate", "--population", "50", "--country", "JP"])
    cli.main()
    assert called == {"country": "JP"}
