"""FP-YAML-2b Task 2: select_archetype applies YAML archetype_modifiers."""

from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.clinical_course.engine import select_archetype

pytestmark = pytest.mark.unit


def _profile(immune=0.5, treat=1.0):
    return SimpleNamespace(immune_reactivity=immune, treatment_sensitivity=treat)


def _patient(age):
    return SimpleNamespace(
        age=age,
        chronic_conditions=[],
        current_medications=[],
        bmi=22.0,
        smoking_status="never",
        alcohol_use="none",
    )


ARCHS = {
    "smooth_recovery": {"probability": 0.6},
    "gradual_deterioration": {"probability": 0.2},
    "treatment_resistant": {"probability": 0.2},
}
MODS = [
    {"condition": "age >= 80", "effect": {"gradual_deterioration": 0.30, "smooth_recovery": -0.30}}
]


def _rate(age):
    rng = np.random.default_rng(11)
    picks = [
        select_archetype(
            "moderate",
            _profile(),
            rng,
            protocol_archetypes=ARCHS,
            protocol_modifiers=MODS,
            patient=_patient(age),
        )
        for _ in range(400)
    ]
    return picks.count("gradual_deterioration") / len(picks)


def test_yaml_modifier_raises_deterioration_for_elderly():
    assert _rate(85) > _rate(50)


def test_deterministic():
    a = select_archetype(
        "moderate", _profile(), np.random.default_rng(5),
        protocol_archetypes=ARCHS, protocol_modifiers=MODS, patient=_patient(85),
    )
    b = select_archetype(
        "moderate", _profile(), np.random.default_rng(5),
        protocol_archetypes=ARCHS, protocol_modifiers=MODS, patient=_patient(85),
    )
    assert a == b
