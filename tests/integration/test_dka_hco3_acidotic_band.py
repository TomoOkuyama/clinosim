"""Integration test: DKA admission HCO3 must land in the acidotic band.

Issue #1988 — the clinical eval axis `condition_lab_coherence.dka_hco3`
reports 15% of DKA Condition emissions have no HCO3 observation at or
below 18 mEq/L within the ±7-day pairing window, violating the ADA
severity criterion (HCO3 < 18 defines mild-to-severe DKA on
presentation).

Root cause (see Issue #1988 investigation): the inpatient day-loop
advances physiological state by one full day before resolving the
admission ABG/BMP orders, so the "admission" HCO3 reflects state after
~1 day of recovery (ph_status recovered from the authored -0.35 toward
-0.20, HCO3 climbing from ~13 to ~17.5). With observation noise sigma
~0.7 mEq/L on top, 10-15% of the resulting admission HCO3 draws exceed
18 — contradicting the DKA diagnosis the same encounter emits.

This test runs a small forced DKA cohort and asserts that the first
chronological HCO3 observation per encounter is < 18 mEq/L in every
case. Pre-fix the test fails on roughly 10-15% of patients. Post-fix
(admission orders resolved against pre-day-0-update state) all first
HCO3 draws land in the acidotic band.
"""

from __future__ import annotations

import pytest

from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig

pytestmark = pytest.mark.integration


def _first_hco3_values(dataset) -> list[float]:
    """Return the earliest-timestamped HCO3 lab value per encounter."""
    out: list[float] = []
    for rec in dataset.patients:
        hco3 = sorted((r.result_datetime, r.value) for r in rec.lab_results if (r.lab_name or "") == "HCO3")
        if hco3:
            out.append(float(hco3[0][1]))
    return out


def test_dka_moderate_admission_hco3_in_acidotic_band() -> None:
    """Moderate DKA: first HCO3 draw must be < 18 mEq/L for every patient.

    ADA severity criterion: HCO3 < 18 mEq/L defines mild-to-severe DKA
    on presentation. Pre-fix (Issue #1988) this holds on only
    ~85-90% of cases because the admission lab draw is resolved against
    end-of-day-0 state, not admission state.
    """
    scenario = ForcedScenario(
        disease_id="diabetic_ketoacidosis",
        count=30,
        severity="moderate",
    )
    config = SimulatorConfig(random_seed=4242, country="US", catchment_population=30)
    dataset = run_forced(scenario, config)

    first_hco3 = _first_hco3_values(dataset)
    assert first_hco3, "forced DKA scenario produced no HCO3 observations"
    over = [v for v in first_hco3 if v >= 18.0]
    assert not over, (
        "DKA admission HCO3 must be < 18 mEq/L (ADA severity criterion); "
        f"{len(over)}/{len(first_hco3)} violations: {over[:10]}"
    )


def test_dka_severe_admission_hco3_well_below_18() -> None:
    """Severe DKA (pH < 7.0) must emit HCO3 well below 18 — p95 <= 15 per ADA."""
    scenario = ForcedScenario(
        disease_id="diabetic_ketoacidosis",
        count=20,
        severity="severe",
    )
    config = SimulatorConfig(random_seed=909, country="US", catchment_population=20)
    dataset = run_forced(scenario, config)

    first_hco3 = _first_hco3_values(dataset)
    assert first_hco3, "forced severe DKA scenario produced no HCO3 observations"
    over = [v for v in first_hco3 if v >= 18.0]
    assert not over, (
        f"severe DKA admission HCO3 must be < 18 mEq/L; {len(over)}/{len(first_hco3)} violations: {over[:10]}"
    )
