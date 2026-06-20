"""Unit tests for encounter protocol Pydantic validation (AD-18)."""

import pytest

from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,
    load_all_encounter_conditions,
    load_encounter_condition,
)

pytestmark = pytest.mark.unit


def test_well_formed_yaml_validates() -> None:
    """A shipped encounter YAML loads, validates, and returns a dict."""
    data = load_encounter_condition("abdominal_pain_nonspecific")
    assert isinstance(data, dict)
    assert data["condition_id"] == "abdominal_pain_nonspecific"
    assert data["icd10_code"] == "R10.9"


def test_all_shipped_conditions_validate() -> None:
    """Every shipped encounter YAML passes validation (no silent skips)."""
    conditions = load_all_encounter_conditions()
    assert len(conditions) == 46
    for cid, data in conditions.items():
        # model_validate is what the loaders run; re-assert it stays valid.
        EncounterConditionProtocol.model_validate(data)
        assert isinstance(cid, str)


def test_malformed_dict_raises_not_silently_passes() -> None:
    """A malformed protocol (missing required field) raises, not swallowed."""
    bad = {
        "condition_id": "broken",
        # icd10_code missing
        "chief_complaint": {"en": "x"},
        "encounter_type": "emergency",
        "department": "emergency_medicine",
    }
    with pytest.raises(Exception):
        EncounterConditionProtocol.model_validate(bad)


def test_extra_fields_are_allowed() -> None:
    """Permissive extra='allow' keeps condition-specific sections."""
    proto = EncounterConditionProtocol.model_validate(
        {
            "condition_id": "x",
            "icd10_code": "R10.9",
            "chief_complaint": {"en": "pain"},
            "encounter_type": "emergency",
            "department": "emergency_medicine",
            "workup": {"labs": ["CBC"]},
        }
    )
    assert proto.model_dump()["workup"] == {"labs": ["CBC"]}
