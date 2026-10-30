"""The realised sepsis course mix stays near its intended rates (Issue #2243)."""

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


def test_typical_sepsis_admissions_mostly_recover() -> None:
    proto = load_disease_protocol("sepsis")
    # About two thirds severe and a third aged 80+, like the admitted cohort.
    cases = [("severe", 82), ("severe", 74), ("moderate", 85), ("severe", 68), ("moderate", 70), ("severe", 88)]
    mix: dict[str, float] = {}
    for severity, age in cases:
        rng = _CaptureRng()
        select_archetype(
            severity,
            PatientPhysiologicalProfile(),
            rng,
            proto.course_archetypes,
            proto.archetype_modifiers,
            SimpleNamespace(age=age, chronic_conditions=[]),
        )
        for k, v in rng.dist.items():
            mix[k] = mix.get(k, 0.0) + v / len(cases)
    recovering = mix["smooth_recovery"] + mix["dip_then_recovery"]
    deteriorating = mix["gradual_deterioration"] + mix["sudden_deterioration"]
    assert recovering >= 0.40
    assert deteriorating <= 0.30
