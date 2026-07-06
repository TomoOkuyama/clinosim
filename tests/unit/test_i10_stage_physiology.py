"""FP-I10: hypertension stage is a real physiological consumer (BP baseline), not a no-op.

I10 "Stage 1"/"Stage 2" now maps to a severity_score (STAGE_SEVERITY) that scales the
baseline blood-pressure elevation, so a higher-stage hypertensive has measurably higher
BP in the output — closing a C2 (degenerate-element) gap.
"""

from datetime import date

import numpy as np
import pytest

from clinosim.locale.loader import load_demographics
from clinosim.modules.patient.activator import STAGE_SEVERITY, activate_patient
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_DEMO = load_demographics("US")


def _person(chronic):
    return PersonRecord(
        person_id="P1", household_id="H1", age=60, sex="M",
        date_of_birth=date(1964, 1, 1), chronic_conditions=list(chronic),
    )


def _activate(chronic, seed):
    return activate_patient(_person(chronic), np.random.default_rng(seed), _DEMO)


def test_i10_in_stage_severity():
    assert "I10" in STAGE_SEVERITY
    assert set(STAGE_SEVERITY["I10"]) == {"Stage 1", "Stage 2"}


def test_i10_severity_score_from_stage_not_generic():
    valid = set(STAGE_SEVERITY["I10"].values())
    for seed in range(40):
        p = _activate(["I10"], seed)
        i10 = next(c for c in p.chronic_conditions if c.code == "I10")
        assert i10.severity_score in valid, (
            f"I10 severity_score {i10.severity_score} not a stage value {valid} "
            f"(stage={i10.stage!r})"
        )


def test_baseline_bp_is_stage_graded():
    # Collect baseline systolic by stage across seeds (same age/sex).
    by_stage: dict[str, list[int]] = {"Stage 1": [], "Stage 2": []}
    for seed in range(200):
        p = _activate(["I10"], seed)
        i10 = next(c for c in p.chronic_conditions if c.code == "I10")
        by_stage[i10.stage].append(p.baseline_vitals.systolic_bp)
    assert by_stage["Stage 1"] and by_stage["Stage 2"], "both stages should occur"
    mean1 = sum(by_stage["Stage 1"]) / len(by_stage["Stage 1"])
    mean2 = sum(by_stage["Stage 2"]) / len(by_stage["Stage 2"])
    assert mean2 > mean1, f"Stage 2 systolic {mean2:.1f} should exceed Stage 1 {mean1:.1f}"


def test_hypertensive_baseline_exceeds_normotensive():
    htn = [_activate(["I10"], s).baseline_vitals.systolic_bp for s in range(100)]
    normo = [_activate([], s).baseline_vitals.systolic_bp for s in range(100)]
    assert sum(htn) / len(htn) > sum(normo) / len(normo)
