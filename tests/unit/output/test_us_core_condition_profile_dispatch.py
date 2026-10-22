"""Issue #1768 Cluster E T8b-1: US Core v9 Condition profile dispatch.

US Core v9 publishes two Condition profiles keyed on category:

* `us-core-condition-encounter-diagnosis` — for a Condition whose
  `category.coding[].code = "encounter-diagnosis"` (per-encounter
  reason for visit).
* `us-core-condition-problems-health-concerns` — for a Condition whose
  `category.coding[].code = "problem-list-item"` (patient-level
  problem list entry).

The `_apply_us_core_profile` hook from T8a attached a single-URL
profile per resource type and skipped Condition. T8b-1 extends it so
Condition dispatches to the correct variant by inspecting the
category coding.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.post_process import _apply_us_core_profile

_ENCOUNTER_DIAGNOSIS_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-encounter-diagnosis"
_PROBLEMS_HEALTH_CONCERNS_URL = (
    "http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-problems-health-concerns"
)
_HL7_CONDITION_CATEGORY = "http://terminology.hl7.org/CodeSystem/condition-category"


def _condition(category_code: str) -> dict:
    """Build a minimal Condition resource with the given category code."""
    return {
        "resourceType": "Condition",
        "id": "cond-1",
        "category": [
            {
                "coding": [
                    {
                        "system": _HL7_CONDITION_CATEGORY,
                        "code": category_code,
                    }
                ],
            }
        ],
    }


def test_encounter_diagnosis_condition_gets_encounter_diagnosis_profile() -> None:
    cond = _condition("encounter-diagnosis")
    _apply_us_core_profile(cond)
    profiles = cond.get("meta", {}).get("profile", [])
    assert _ENCOUNTER_DIAGNOSIS_URL in profiles
    assert _PROBLEMS_HEALTH_CONCERNS_URL not in profiles


def test_problem_list_item_condition_gets_problems_health_concerns_profile() -> None:
    cond = _condition("problem-list-item")
    _apply_us_core_profile(cond)
    profiles = cond.get("meta", {}).get("profile", [])
    assert _PROBLEMS_HEALTH_CONCERNS_URL in profiles
    assert _ENCOUNTER_DIAGNOSIS_URL not in profiles


def test_condition_with_no_category_gets_no_us_core_profile() -> None:
    """A Condition without a recognized category code must leave
    ``meta.profile`` untouched — asserting a profile without the
    corresponding category coding would violate the data-completeness
    precondition (`feedback_profile_assertion_requires_data_completeness`)."""
    cond = {"resourceType": "Condition", "id": "cond-2"}
    _apply_us_core_profile(cond)
    assert "meta" not in cond or not cond.get("meta", {}).get("profile")


def test_condition_with_unknown_category_gets_no_us_core_profile() -> None:
    """A Condition with a category code outside the two US Core variants
    (e.g. the HL7 Core ``health-concern`` or an unmapped simulator
    category) does not get a profile claim — same rationale."""
    cond = _condition("health-concern")
    _apply_us_core_profile(cond)
    profiles = cond.get("meta", {}).get("profile", []) if cond.get("meta") else []
    assert _ENCOUNTER_DIAGNOSIS_URL not in profiles
    assert _PROBLEMS_HEALTH_CONCERNS_URL not in profiles


def test_condition_dispatch_is_idempotent() -> None:
    cond = _condition("encounter-diagnosis")
    _apply_us_core_profile(cond)
    _apply_us_core_profile(cond)
    us_core = [p for p in cond["meta"]["profile"] if "us-core" in p]
    assert len(us_core) == 1


def test_condition_dispatch_preserves_other_profiles() -> None:
    cond = _condition("problem-list-item")
    cond["meta"] = {
        "profile": [
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
        ],
    }
    _apply_us_core_profile(cond)
    profiles = cond["meta"]["profile"]
    assert "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race" in profiles
    assert _PROBLEMS_HEALTH_CONCERNS_URL in profiles


@pytest.mark.parametrize(
    "category_code,expected_url",
    [
        ("encounter-diagnosis", _ENCOUNTER_DIAGNOSIS_URL),
        ("problem-list-item", _PROBLEMS_HEALTH_CONCERNS_URL),
    ],
)
def test_condition_dispatch_matrix(category_code: str, expected_url: str) -> None:
    cond = _condition(category_code)
    _apply_us_core_profile(cond)
    assert expected_url in cond["meta"]["profile"]
