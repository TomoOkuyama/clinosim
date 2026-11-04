"""DiseaseProtocol runs the course_archetypes / archetype_modifiers checks
itself, so every constructed protocol is checked (Issue #2566)."""

from __future__ import annotations

import pytest

from clinosim.modules.disease.protocol import DiseaseProtocol

_BASE = {"disease_id": "test_disease", "icd_codes": {}, "incidence": {}, "severity": {}}


def test_valid_course_archetypes_and_modifiers_pass() -> None:
    DiseaseProtocol(
        **_BASE,
        course_archetypes={"smooth_recovery": {"trajectory": {"inflammation_level": {0: 0.1}}}},
        archetype_modifiers=[{"condition": "age >= 65", "effect": {"smooth_recovery": -0.1}}],
    )


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (
            {"course_archetypes": {"smooth_recovery": {"trajectory": {"neurological_status": {0: -0.05}}}}},
            "neurological_status",
        ),
        (
            {"archetype_modifiers": [{"condition": "no_such_condition", "effect": {}}]},
            "unknown archetype_modifier condition",
        ),
        (
            {
                "course_archetypes": {"smooth_recovery": {}},
                "archetype_modifiers": [{"condition": "age >= 65", "effect": {"rapid_decline": 0.1}}],
            },
            "not in the disease's archetypes",
        ),
        ({"archetype_modifiers": [{"condition": "age >= 65", "effect": {"smooth_recovery": "x"}}]}, "non-numeric"),
    ],
)
def test_construction_rejects_unwired_course_blocks(fields: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        DiseaseProtocol(**_BASE, **fields)
