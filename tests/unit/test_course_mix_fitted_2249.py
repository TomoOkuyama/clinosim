"""Fitted course base rates keep recovery the majority path (Issue #2249)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.clinical_course.engine import select_archetype
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.types.patient import PatientPhysiologicalProfile

pytestmark = pytest.mark.unit


class _CaptureRng:
    def choice(self, names, p):
        self.dist = dict(zip(names, p))
        return names[0]


# Smooth-recovery share the authors intend at cohort level.
_INTENDED_SMOOTH = {
    "cerebral_infarction": 0.40,
    "acute_mi": 0.50,
    "diabetic_ketoacidosis": 0.60,
    "urinary_tract_infection": 0.60,
    "bacterial_pneumonia": 0.55,
    "hip_fracture": 0.42,
}


@pytest.mark.parametrize("disease_id", sorted(_INTENDED_SMOOTH))
def test_elderly_admissions_realise_the_intended_smooth_recovery(disease_id: str) -> None:
    proto = load_disease_protocol(disease_id)
    dist = (proto.severity or {}).get("distribution") or {"moderate": 1.0}
    smooth = 0.0
    for severity, weight in dist.items():
        for age in (68, 78, 86):
            rng = _CaptureRng()
            select_archetype(
                severity,
                PatientPhysiologicalProfile(),
                rng,
                proto.course_archetypes,
                proto.archetype_modifiers,
                SimpleNamespace(age=age, chronic_conditions=[]),
            )
            smooth += weight * rng.dist["smooth_recovery"] / 3
    # Within 6 points of the intended share for a typical elderly admission mix.
    assert smooth == pytest.approx(_INTENDED_SMOOTH[disease_id], abs=0.06)
