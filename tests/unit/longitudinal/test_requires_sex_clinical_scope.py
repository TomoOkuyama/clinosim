"""Phase 4b.2.β Task 1 — `ClinicalScope.requires_sex` attribute gating.

Mirrors the Python helper `_annual_chronic_onset`'s sex-locking at the
attribute-scope level: a yaml with ``requires_sex: "M"`` excludes
female patients from the engine's event dispatch before any rate math,
instead of relying on a per-ICD runtime guard.
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.modules.longitudinal.engine import _attribute_in_scope
from clinosim.modules.longitudinal.loader import AttributeSpec, ClinicalScope
from clinosim.modules.longitudinal.patterns.event import EventSpec
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _spec(sex: str) -> AttributeSpec:
    return AttributeSpec(
        attribute_id="n40_onset",
        pattern="event",
        clinical_scope=ClinicalScope(requires_age_band=[18, 120], requires_sex=sex),
        body=EventSpec(event_name="n40_onset", emits_icd="N40", base_annual_rate=0.08),
    )


def _person(sex: str) -> PersonRecord:
    return PersonRecord(
        person_id="PX",
        household_id="H1",
        sex=sex,
        age=64,
        date_of_birth=date(1960, 1, 1),
        chronic_conditions=[],
    )


def test_requires_sex_male_passes_for_male_person():
    assert _attribute_in_scope(_spec("M"), _person("M"), 2024) is True


def test_requires_sex_male_rejects_female_person():
    assert _attribute_in_scope(_spec("M"), _person("F"), 2024) is False


def test_requires_sex_empty_defaults_to_any():
    assert _attribute_in_scope(_spec(""), _person("F"), 2024) is True
    assert _attribute_in_scope(_spec(""), _person("M"), 2024) is True


def test_sex_locked_event_does_not_fire_for_opposite_sex():
    """Review Focus #3: N40 BPH on a female patient — the attribute
    is excluded from `in_scope`, so the engine never dispatches it."""
    female = _person("F")
    assert _attribute_in_scope(_spec("M"), female, 2024) is False
