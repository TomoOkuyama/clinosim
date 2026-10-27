"""Audit-threshold floor pins for the HAI WBC + CRP lab-lift coefficients.

Issue #1987: ``clinosim audit run`` on US s=342 p=10000 reported CLABSI
WBC Δp50 = 1428 < required 3000 and CRP Δp50 = 28.5 < required 50 —
the hai_lab_lift.yaml coefficients plus a 2-day ramp were under-tuned,
so the closed-form delta at full ramp did not leave enough margin for
cross-cohort median dilution (observations that fall before onset or
during ramp pull the CLABSI-cohort median back toward baseline).

The tests here pin that each hai_type's YAML coefficient, applied to a
representative inpatient state via the production closed-form
``_hai_lift_delta`` at the ``apply_hai_lab_lift`` fallback draw-hour,
clears that hai_type's own clinical-acceptance floor defined in
``modules/hai/audit.py``. Importing the floor from the audit spec keeps
the two in lockstep — if the audit threshold is retuned, this test
reads the new value automatically; if the lift coefficient is lowered
below the audit floor, the test fails loudly instead of letting a
silent FAIL slip into the clinical axis.

The ramp dilution the audit's cross-cohort median actually sees is not
captured here (that would require a full engine run); the margin check
below enforces ≥ 1.3× headroom over the audit floor at full ramp so a
future retune has to leave room for ramp dilution.
"""

from __future__ import annotations

import pytest

from clinosim.audit.registry import discover, get_registered
from clinosim.modules.hai.lab_lift import _hai_lift_delta, load_hai_lab_lift_config
from clinosim.types.clinical import PhysiologicalState

# Fallback draw-hour used by ``apply_hai_lab_lift`` when a lab result has
# no order back-reference. Peak-WBC circadian is ~1.0 at 10:00, nadir
# ~0.9 at 04:00; 06:00 ≈ 0.913 — the production default.
_DRAW_HOUR = 6

# Representative inpatient baseline inflammation level (matches the
# calibration comment in hai_lab_lift.yaml and the integration-test
# fixtures). Baseline WBC p50 from the s=342 cohort (~10,920) corresponds
# to infl≈0.33 under the physiology formula; using 0.4 is the
# conservative upper end of the baseline band.
_BASELINE_INFL = 0.4

# Headroom factor over the audit floor at full ramp, so cross-cohort
# median dilution (pre-onset + ramp-partial observations in the CLABSI
# cohort) still leaves the final cohort median above the floor.
_HEADROOM = 1.3


def _audit_floor(hai_type: str, analyte: str) -> float:
    # Other audit tests clear the registry with _reset_for_test(); discover()
    # re-registers every module audit spec regardless of prior import state.
    discover()
    spec = get_registered()["hai"]
    return float(spec.clinical_acceptance[hai_type][f"{analyte}_delta_p50"])


@pytest.mark.unit
@pytest.mark.parametrize("hai_type", ["clabsi", "vap", "cauti"])
def test_lift_coefficient_clears_wbc_audit_floor_with_margin(hai_type: str) -> None:
    """Peak lift must produce a WBC delta ≥ 1.3× the audit floor."""
    _, lift_table = load_hai_lab_lift_config()
    lift = lift_table[hai_type]
    state = PhysiologicalState(inflammation_level=_BASELINE_INFL)
    delta = _hai_lift_delta(state, "WBC", lift, draw_hour=_DRAW_HOUR)
    floor = _audit_floor(hai_type, "WBC")
    assert delta >= floor * _HEADROOM, (
        f"{hai_type}: peak WBC delta {delta:.0f} < {_HEADROOM}× audit floor "
        f"({floor} × {_HEADROOM} = {floor * _HEADROOM:.0f}); "
        f"raise hai_lab_lift.yaml[{hai_type}] (keep eff_infl ≤ 0.8 to stay "
        "below the WBC leukopenia inflection)."
    )


@pytest.mark.unit
@pytest.mark.parametrize("hai_type", ["clabsi", "vap", "cauti"])
def test_lift_coefficient_clears_crp_audit_floor_with_margin(hai_type: str) -> None:
    """Peak lift must produce a CRP delta ≥ 1.3× the audit floor."""
    _, lift_table = load_hai_lab_lift_config()
    lift = lift_table[hai_type]
    state = PhysiologicalState(inflammation_level=_BASELINE_INFL)
    delta = _hai_lift_delta(state, "CRP", lift, draw_hour=_DRAW_HOUR)
    floor = _audit_floor(hai_type, "CRP")
    assert delta >= floor * _HEADROOM, (
        f"{hai_type}: peak CRP delta {delta:.1f} < {_HEADROOM}× audit floor "
        f"({floor} × {_HEADROOM} = {floor * _HEADROOM:.1f}); "
        f"raise hai_lab_lift.yaml[{hai_type}]."
    )


@pytest.mark.unit
def test_clabsi_and_vap_coefficients_pinned_at_audit_safe_value() -> None:
    """Issue #1987 fix pins CLABSI + VAP at 0.40 so eff_infl=0.80 — the
    WBC peak of the physiology formula (just below the leukopenia
    inflection at WBC_HIGH_INFLAMMATION_THRESHOLD=0.8). Any downstream
    retune that lowers these below 0.40 risks reopening the audit FAIL."""
    _, lift_table = load_hai_lab_lift_config()
    assert lift_table["clabsi"] >= 0.40, "CLABSI lift < 0.40 — Issue #1987 FAIL will recur (WBC Δp50 < 3000)."
    assert lift_table["vap"] >= 0.40, (
        "VAP lift < 0.40 — same reasoning as CLABSI (bacterial pneumonia, strong systemic response)."
    )
