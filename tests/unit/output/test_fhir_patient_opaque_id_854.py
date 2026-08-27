"""Issue #854 Bucket C row 18 (PR-patient): Patient opaque id +
population-slug identifier round-trip + cascade across ALL downstream
`Patient.reference` cross-referencers.

Post-#854 every `Patient.id` is ``pt-<12hex>`` (15 chars, fixed).
Structural key = the CIF ``patient_id`` verbatim (a simulation-slug
``POP-{n:06d}``, not a clinical identifier). The slug is preserved on
`Patient.identifier[]` under `POPULATION_SLUG_KEY_SYSTEM` so consumers
who key on the human-readable generation id (iris4h-ai clinical
cockpit, integration tests) can still recover it.

44 cross-ref sites across 29 modules
(Observation/MedicationRequest/MedicationAdministration/Procedure/
DiagnosticReport/ImagingStudy/DocumentReference/Composition/
ClinicalImpression/CareTeam/Condition/AllergyIntolerance/Encounter/
Immunization/FamilyMemberHistory/Coverage/HAI/blood_type/
smoking_alcohol/care_level/inline_bb...) route through the shared
`patient_ref` helper — never string-format the CIF ``patient_id``
directly.
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.demographics.patient import (
    PATIENT_ID_PREFIX,
    POPULATION_SLUG_KEY_SYSTEM,
    patient_ref,
    resolve_patient_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_PT_PATTERN = re.compile(r"^pt-[0-9a-f]{12}$")


# === Resolver contract ===


def test_resolve_patient_id_opaque_shape() -> None:
    """Fixed 15 chars: ``pt-`` (3) + 12 hex."""
    result = resolve_patient_id("POP-000002")
    assert _OPAQUE_PT_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 15


def test_resolve_patient_id_deterministic() -> None:
    key = "POP-000002"
    assert resolve_patient_id(key) == resolve_patient_id(key)


def test_patient_id_prefix() -> None:
    assert PATIENT_ID_PREFIX == "pt-"


def test_population_slug_key_system_uri() -> None:
    assert POPULATION_SLUG_KEY_SYSTEM == "urn:clinosim:identifier:population-slug"


def test_distinct_slugs_produce_distinct_ids() -> None:
    a = resolve_patient_id("POP-000001")
    b = resolve_patient_id("POP-000002")
    assert a != b


# === patient_ref helper ===


def test_patient_ref_returns_reference_dict() -> None:
    ref = patient_ref("POP-000002")
    assert ref == {"reference": f"Patient/{resolve_patient_id('POP-000002')}"}
    assert ref["reference"].startswith("Patient/pt-")


def test_patient_ref_deterministic() -> None:
    a = patient_ref("POP-000002")
    b = patient_ref("POP-000002")
    assert a == b
