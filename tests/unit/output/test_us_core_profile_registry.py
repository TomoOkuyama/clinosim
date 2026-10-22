"""Pin tests for `_US_CORE_PROFILES` registry (Issue #1768 — Cluster E T8a).

US Core v9.0 StructureDefinition URLs are quoted verbatim from
``hl7.fhir.us.core@9.0.0`` IG package (``package/StructureDefinition-us-core-*.json``
``.url`` fixedUri). This test pins the registry URLs and verifies
``_apply_us_core_profile`` attaches them on US output.

Scope: single-profile resource types where no sub-type dispatch is
needed (Patient / Coverage / MedicationRequest / Immunization /
AllergyIntolerance / Procedure / Practitioner / Organization /
Encounter). Condition and Observation require category-dispatched
profile selection and are tracked for T8b follow-up.
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "resource_type,expected_url",
    [
        (
            "Patient",
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient",
        ),
        (
            "Coverage",
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-coverage",
        ),
        (
            "MedicationRequest",
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-medicationrequest",
        ),
        (
            "Immunization",
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-immunization",
        ),
        (
            "AllergyIntolerance",
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-allergyintolerance",
        ),
        (
            "Procedure",
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-procedure",
        ),
        (
            "Practitioner",
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-practitioner",
        ),
        (
            "Organization",
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-organization",
        ),
        (
            "Encounter",
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-encounter",
        ),
    ],
)
def test_us_core_profile_registered_for_resource(resource_type: str, expected_url: str) -> None:
    """Issue #1768: single-profile US Core v9 resource types registered."""
    from clinosim.modules.output.fhir_r4.post_process import _US_CORE_PROFILES

    profiles = _US_CORE_PROFILES.get(resource_type)
    assert profiles is not None, f"{resource_type} missing from _US_CORE_PROFILES registry"
    assert expected_url in profiles, f"{resource_type} profiles={profiles} does not include {expected_url}"


def test_apply_us_core_profile_attaches_url_on_us() -> None:
    """`_apply_us_core_profile` must append the resource-type's US Core
    URL to ``meta.profile`` when absent."""
    from clinosim.modules.output.fhir_r4.post_process import _apply_us_core_profile

    patient = {"resourceType": "Patient", "id": "p1"}
    _apply_us_core_profile(patient)
    profiles = patient.get("meta", {}).get("profile", [])
    assert "http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient" in profiles


def test_apply_us_core_profile_is_idempotent() -> None:
    """Calling twice does not duplicate the URL."""
    from clinosim.modules.output.fhir_r4.post_process import _apply_us_core_profile

    patient = {"resourceType": "Patient", "id": "p1"}
    _apply_us_core_profile(patient)
    _apply_us_core_profile(patient)
    profiles = patient["meta"]["profile"]
    us_core_profiles = [p for p in profiles if "us-core-patient" in p]
    assert len(us_core_profiles) == 1


def test_apply_us_core_profile_preserves_existing_profiles() -> None:
    """An inline-set profile (e.g. ``us-core-race``) must not be dropped."""
    from clinosim.modules.output.fhir_r4.post_process import _apply_us_core_profile

    patient = {
        "resourceType": "Patient",
        "id": "p1",
        "meta": {
            "profile": [
                "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
            ],
        },
    }
    _apply_us_core_profile(patient)
    profiles = patient["meta"]["profile"]
    assert "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race" in profiles
    assert "http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient" in profiles


def test_apply_us_core_profile_skips_unregistered_resource_type() -> None:
    """Resource types not in ``_US_CORE_PROFILES`` leave meta untouched —
    silent no-op mirrors the JP Core helper's behaviour."""
    from clinosim.modules.output.fhir_r4.post_process import _apply_us_core_profile

    composition = {"resourceType": "Composition", "id": "c1"}
    _apply_us_core_profile(composition)
    assert composition == {"resourceType": "Composition", "id": "c1"}


def test_apply_us_core_profile_stacks_on_build_patient_output() -> None:
    """Integration: an actual ``_build_patient`` US Patient receives the
    us-core-patient profile URL alongside any inline-set profile URLs
    (e.g. ``us-core-race`` extension profile, if present)."""
    from clinosim.modules.output.fhir_r4.demographics.patient import _build_patient
    from clinosim.modules.output.fhir_r4.post_process import _apply_us_core_profile

    patient_dict = {
        "patient_id": "POP-000001",
        "name": {"family_name": "Doe", "given_name": "Jane"},
        "sex": "F",
        "date_of_birth": "1970-01-01",
        "race": "white",
        "ethnicity": "not_hispanic",
    }
    resource = _build_patient(patient_dict, "US")
    _apply_us_core_profile(resource)
    profiles = resource.get("meta", {}).get("profile", [])
    assert "http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient" in profiles


def test_apply_us_core_profile_jp_patient_untouched() -> None:
    """Negative: the helper is scoped to US output. Calling it on a JP
    Patient does attach the Patient-type US Core URL (the function is
    country-agnostic — gating is the caller's responsibility in
    ``builder.py``). This test documents that contract so a future
    refactor cannot silently invert it."""
    from clinosim.modules.output.fhir_r4.post_process import _apply_us_core_profile

    jp_patient = {
        "resourceType": "Patient",
        "id": "p1",
        "meta": {
            "profile": [
                "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient",
            ],
        },
    }
    _apply_us_core_profile(jp_patient)
    profiles = jp_patient["meta"]["profile"]
    # The helper is country-agnostic — it DOES append the US Core URL.
    # The caller (`builder.py`) gates by ``is_jp(ctx.country)``.
    assert "http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient" in profiles
    assert "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient" in profiles
