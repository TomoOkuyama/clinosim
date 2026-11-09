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
    assert len(conditions) == 52
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


_MINIMAL = {
    "condition_id": "x",
    "icd10_code": "R10.9",
    "chief_complaint": {"en": "pain"},
    "encounter_type": "emergency",
    "department": "emergency_medicine",
}


def test_condition_sections_are_typed() -> None:
    """Condition-specific sections (workup, treatment, ...) are declared fields."""
    proto = EncounterConditionProtocol.model_validate(
        {**_MINIMAL, "workup": {"labs": [{"test": "CBC", "probability": 0.5}]}}
    )
    assert proto.workup is not None and proto.workup.labs[0].test == "CBC"


@pytest.mark.parametrize(
    "extra",
    [{"workupp": {}}, {"workup": {"labs": [{"test": "CBC", "probabilty": 0.5}]}}],
)
def test_unknown_keys_are_rejected(extra: dict) -> None:
    """A misspelled key fails at load instead of being silently ignored (Issue #2845)."""
    with pytest.raises(ValueError):
        EncounterConditionProtocol.model_validate({**_MINIMAL, **extra})
