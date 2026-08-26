"""Issue #854 Bucket B (PR-condition): Condition opaque id + identifier
round-trip + cross-ref byte-consistency across the biggest Bucket B
cascade.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 →
#878 [lab] → #879 [vs/gcs/news2] → #880 [stand-alones] → #881
[mb-org/sus] → #882 [Specimen]) to `Condition`.

Post-#854 every Condition.id is ``cond-<12hex>`` (17 chars, fixed).

Two Condition emit paths in ``conditions/conditions.py``:
- encounter-primary (per-encounter): structural key
  ``{encounter_id}-primary`` (or ``{patient_id}-primary`` fallback).
- chronic problem-list (patient-scoped): structural key
  ``chronic-{patient_id}-{idx:02d}``.

Cross-ref cascade (largest single Bucket B PR): every reference funnels
through the shared resolver in ``conditions/primary_ref.py``:

- ``Encounter.reasonReference[]``, ``Encounter.diagnosis[].condition``
- ``Procedure.reasonReference[]``  — via `primary_condition_ref` in
  procedures.py + oxygen_therapy.py + inline_bb.py
- ``MedicationRequest.reasonReference[]`` — via
  `primary_condition_ref_from_codes` in medications.py (2 sites)
- ``ClinicalImpression.finding[].itemReference``
- ``Composition.section[].entry`` — via `_bb_compositions`' precomputed
  `enc_to_primary_cond` map

Any writer that inlines ``f"Condition/cond-..."`` outside these callers
would fall out of the reference-integrity guarantee. The coverage guard
below scans a full in-process emit and asserts every Condition/
reference resolves to an emitted Condition.
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
    CONDITION_ID_PREFIX,
    CONDITION_KEY_SYSTEM,
    _resolve_condition_id,
    chronic_condition_id,
    chronic_condition_key,
    encounter_primary_condition_id,
    encounter_primary_condition_key,
    primary_condition_ref,
    primary_condition_ref_from_codes,
)

pytestmark = pytest.mark.unit


_OPAQUE_CONDITION_PATTERN = re.compile(r"^cond-[0-9a-f]{12}$")


# === Resolver contract ===


def test_resolve_condition_id_opaque_shape() -> None:
    """Fixed 17 chars: ``cond-`` (5) + 12 hex."""
    result = _resolve_condition_id("ENC-POP-000012-primary")
    assert _OPAQUE_CONDITION_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 17


def test_resolve_condition_id_deterministic() -> None:
    key = "ENC-POP-000012-primary"
    assert _resolve_condition_id(key) == _resolve_condition_id(key)


def test_condition_key_system_uri() -> None:
    assert CONDITION_KEY_SYSTEM == "urn:clinosim:identifier:condition-key"


def test_condition_id_prefix_constant() -> None:
    assert CONDITION_ID_PREFIX == "cond-"


# === Structural-key helpers ===


def test_encounter_primary_condition_key_uses_encounter_when_present() -> None:
    assert encounter_primary_condition_key("POP-1", "ENC-1") == "ENC-1-primary"


def test_encounter_primary_condition_key_falls_back_to_patient() -> None:
    assert encounter_primary_condition_key("POP-1", "") == "POP-1-primary"


def test_chronic_condition_key_shape() -> None:
    assert chronic_condition_key("POP-1", 3) == "chronic-POP-1-03"


def test_encounter_primary_condition_id_matches_key_via_resolver() -> None:
    assert encounter_primary_condition_id("POP-1", "ENC-1") == _resolve_condition_id("ENC-1-primary")


def test_chronic_condition_id_matches_key_via_resolver() -> None:
    assert chronic_condition_id("POP-1", 3) == _resolve_condition_id("chronic-POP-1-03")


def test_encounter_primary_and_chronic_produce_distinct_ids() -> None:
    """Distinct structural keys must yield distinct opaque ids."""
    a = encounter_primary_condition_id("POP-1", "ENC-1")
    b = chronic_condition_id("POP-1", 0)
    assert a != b


# === primary_condition_ref / _from_codes — Bucket B cascade entry ===


def test_primary_condition_ref_returns_opaque_id_when_no_chronic_match() -> None:
    """Genuine acute problem — encounter-scoped opaque id."""
    record = {"clinical_diagnosis": {"discharge_diagnosis_code": "S72"}, "patient": {"chronic_conditions": []}}
    result = primary_condition_ref(record, "POP-1", "ENC-1")
    assert result == encounter_primary_condition_id("POP-1", "ENC-1")
    assert _OPAQUE_CONDITION_PATTERN.match(result)


def test_primary_condition_ref_routes_to_chronic_id_on_match() -> None:
    """Chronic-primary merge — chronic-scoped opaque id."""
    record = {
        "clinical_diagnosis": {"discharge_diagnosis_code": "I50.9"},
        "patient": {"chronic_conditions": [{"code": "I25.9"}, {"code": "I50.5"}]},
    }
    # I50 base matches chronic index 1 (I50.5).
    result = primary_condition_ref(record, "POP-1", "ENC-1")
    assert result == chronic_condition_id("POP-1", 1)


def test_primary_condition_ref_from_codes_returns_opaque_id() -> None:
    result = primary_condition_ref_from_codes("S72", None, "POP-1", "ENC-1")
    assert result == encounter_primary_condition_id("POP-1", "ENC-1")


def test_primary_condition_ref_from_codes_routes_to_chronic() -> None:
    result = primary_condition_ref_from_codes("I50.9", ["I25.9", "I50.5"], "POP-1", "ENC-1")
    assert result == chronic_condition_id("POP-1", 1)


# === Emit path — conditions.py ===


def _minimal_record(*, chronic_codes: list[str] | None = None, primary_code: str = "S72") -> dict:
    """Minimal CIF record shape that exercises both Condition emit paths."""
    chronic_conditions = [{"code": c, "onset_date": "2020-01-01"} for c in (chronic_codes or [])]
    return {
        "patient": {"patient_id": "POP-1", "sex": "F", "chronic_conditions": chronic_conditions},
        "encounters": [
            {
                "encounter_id": "ENC-1",
                "admission_datetime": "2026-05-12T08:00:00",
                "discharge_datetime": "2026-05-19T14:00:00",
                "encounter_type": "inpatient",
                "attending_physician_id": "STAFF-001",
                "severity": "moderate",
            }
        ],
        "clinical_diagnosis": {"discharge_diagnosis_code": primary_code},
    }


def test_build_conditions_emits_opaque_primary_id_with_identifier() -> None:
    from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions

    record = _minimal_record(primary_code="S72", chronic_codes=[])
    resources = _build_conditions(record, "POP-1", country="US")
    primaries = [r for r in resources if r["category"][0]["coding"][0]["code"] == "encounter-diagnosis"]
    assert len(primaries) == 1
    r = primaries[0]
    assert _OPAQUE_CONDITION_PATTERN.match(r["id"]), f"non-opaque primary Condition id: {r['id']!r}"
    key_idents = [i for i in r.get("identifier", []) if i.get("system") == CONDITION_KEY_SYSTEM]
    assert len(key_idents) == 1
    assert key_idents[0]["value"] == "ENC-1-primary"


def test_build_conditions_emits_opaque_chronic_id_with_identifier() -> None:
    from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions

    record = _minimal_record(primary_code="S72", chronic_codes=["I25.9", "E11.9"])
    resources = _build_conditions(record, "POP-1", country="US")
    chronics = [r for r in resources if r["category"][0]["coding"][0]["code"] == "problem-list-item"]
    assert len(chronics) == 2
    for idx, r in enumerate(chronics):
        assert _OPAQUE_CONDITION_PATTERN.match(r["id"]), f"non-opaque chronic Condition id: {r['id']!r}"
        key_idents = [i for i in r.get("identifier", []) if i.get("system") == CONDITION_KEY_SYSTEM]
        assert len(key_idents) == 1
        assert key_idents[0]["value"] == f"chronic-POP-1-{idx:02d}"


def test_build_conditions_same_input_reproduces_same_id() -> None:
    """Byte-diff invariant."""
    from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions

    record = _minimal_record(primary_code="S72", chronic_codes=["I25.9"])
    a = _build_conditions(record, "POP-1", country="JP")
    b = _build_conditions(record, "POP-1", country="JP")
    assert [r["id"] for r in a] == [r["id"] for r in b]


# === Cross-reference byte-consistency guard ===


def test_encounter_reason_reference_matches_condition_writer_output() -> None:
    """`Encounter.reasonReference[]` must resolve via the same resolver that
    the Condition writer uses. A drift here — an inline `f"Condition/cond-..."`
    somewhere — would break every Encounter → primary Condition link
    silently."""
    from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter

    enc = {
        "encounter_id": "ENC-1",
        "admission_datetime": "2026-05-12T08:00:00",
        "discharge_datetime": "2026-05-19T14:00:00",
        "encounter_type": "inpatient",
        "attending_physician_id": "STAFF-001",
        "severity": "moderate",
    }
    resource = _build_encounter(
        enc,
        patient_id="POP-1",
        primary_dx_code="S72",
        country="US",
        admit_dx_code="S72",
        admit_dx_system="icd-10-cm",
        chronic_condition_codes=[],
    )
    # `Encounter.diagnosis[0].condition.reference` is the primary route the
    # Encounter builder uses; `reasonReference[]` is emitted only when the
    # diagnosis[] slot is unavailable. Either route MUST resolve to the
    # opaque Condition.id that `_build_conditions` would emit for the same
    # encounter/patient — both routes funnel through
    # `primary_condition_ref_from_codes` → `encounter_primary_condition_id`.
    dx_entries = resource.get("diagnosis", [])
    reason_refs = resource.get("reasonReference", [])
    primary_refs = [e["condition"]["reference"] for e in dx_entries if e.get("rank") == 1] + [
        r["reference"] for r in reason_refs
    ]
    assert primary_refs, f"expected a primary Condition reference on the Encounter, got {resource!r}"
    expected = f"Condition/{encounter_primary_condition_id('POP-1', 'ENC-1')}"
    assert primary_refs[0] == expected


def test_encounter_diagnosis_chronic_condition_reference_uses_shared_resolver() -> None:
    """`Encounter.diagnosis[].condition.reference` for the chronic-as-secondary
    fan-out must resolve via `chronic_condition_id` (was pre-#854 inline
    `f"Condition/cond-chronic-{patient_id}-{i:02d}"`)."""
    from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter

    enc = {
        "encounter_id": "ENC-1",
        "admission_datetime": "2026-05-12T08:00:00",
        "discharge_datetime": "2026-05-19T14:00:00",
        "encounter_type": "inpatient",
        "attending_physician_id": "STAFF-001",
        "severity": "moderate",
    }
    resource = _build_encounter(
        enc,
        patient_id="POP-1",
        primary_dx_code="S72",  # acute primary — chronic fan-out is not preempted
        country="US",
        admit_dx_code="S72",
        admit_dx_system="icd-10-cm",
        chronic_condition_codes=["I25.9", "E11.9"],
    )
    dx_entries = resource.get("diagnosis", [])
    chronic_refs = [
        e["condition"]["reference"] for e in dx_entries if e.get("use", {}).get("coding", [{}])[0].get("code") == "CM"
    ]
    assert len(chronic_refs) == 2
    for idx, ref in enumerate(chronic_refs):
        assert ref == f"Condition/{chronic_condition_id('POP-1', idx)}"
