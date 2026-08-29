"""Issue #925 — Composition.section[].entry[] population.

At v0.5.0, SOAP-note (34131-3) and JP-CLINS discharge-summary (18842-5)
Composition builders emitted section text but never populated
``section.entry[]`` with references to the encounter's
MedicationRequests / Observations / Procedures / Conditions. These
tests pin the fix: `_bb_compositions` builds an encounter → resource
index once per bundle and threads it through so the generic + JP-CLINS
section walkers can populate `entry[]` from the SAME walk that emits
`section.text.div` / `section.code`.

Absence-of-entry semantics also pinned: a section with no eligible
resources in the index MUST omit `entry` entirely (spec-clean under
Composition.section.entry 0..*) instead of emitting an empty array.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.documents.composition import (
    _build_composition,
    _build_encounter_resource_index,
    _derive_section_entries,
)


def _make_entry(resource: dict) -> dict:
    return {"fullUrl": f"urn:uuid:{resource.get('id', 'x')}", "resource": resource}


def _soap_doc(encounter_id: str = "ENC-001") -> dict:
    return {
        "document_id": "doc-ENC-001-soap-01",
        "document_type": "OUTPATIENT_SOAP",
        "loinc_code": "34131-3",
        "format_type": "composition",
        "patient_id": "POP-000001",
        "encounter_id": encounter_id,
        "author_practitioner_id": "PRAC-EN-001",
        "authored_datetime": "2026-03-01T10:00:00",
        "language": "en",
        "narrative": {
            "sections": {
                "subjective": "Patient reports chest tightness.",
                "objective": "BP 148/92, HR 88.",
                "assessment": "Hypertension, uncontrolled.",
                "plan": "Increase amlodipine 5mg -> 10mg. F/U labs in 4wks.",
            }
        },
    }


def _jp_ds_doc(encounter_id: str = "ENC-002") -> dict:
    return {
        "document_id": "doc-ENC-002-ds-01",
        "document_type": "DISCHARGE_SUMMARY",
        "loinc_code": "18842-5",
        "format_type": "composition",
        "patient_id": "POP-000002",
        "encounter_id": encounter_id,
        "author_practitioner_id": "PRAC-JP-001",
        "authored_datetime": "2026-02-20T10:00:00",
        "language": "ja",
        "narrative": {
            "sections": {
                "admission_reason": "急性腎盂腎炎のため入院。",
                "admission_details": "2026-02-15、緊急入院。",
                "admission_diagnoses": "1. 急性腎盂腎炎（N10）",
                "chief_complaint": "発熱・腰痛",
                "present_illness": "3日前より発熱と背部痛。",
                "hospital_course": "抗菌薬治療で改善。",
                "discharge_details": "2026-02-20、自宅退院。",
                "discharge_diagnoses": "1. 急性腎盂腎炎（N10）",
                "discharge_medications": "レボフロキサシン 500mg 1日1回 × 7日間",
                "discharge_instructions": "十分な水分摂取。",
            }
        },
    }


# ------------------------------------------------------------------ #
# _build_encounter_resource_index
# ------------------------------------------------------------------ #


@pytest.mark.unit
def test_encounter_resource_index_buckets_by_encounter_and_type():
    entries = [
        _make_entry(
            {
                "resourceType": "MedicationRequest",
                "id": "mr-aaaa",
                "encounter": {"reference": "Encounter/enc-1"},
                "medicationCodeableConcept": {"text": "amlodipine 10mg"},
            }
        ),
        _make_entry(
            {
                "resourceType": "Observation",
                "id": "obs-bbbb",
                "encounter": {"reference": "Encounter/enc-1"},
                "code": {"text": "BP"},
            }
        ),
        _make_entry(
            {
                "resourceType": "Observation",
                "id": "obs-cccc",
                "encounter": {"reference": "Encounter/enc-2"},
                "code": {"text": "HR"},
            }
        ),
        # No encounter → skipped.
        _make_entry({"resourceType": "MedicationRequest", "id": "mr-orphan"}),
        # Untracked resource type → skipped.
        _make_entry(
            {
                "resourceType": "Patient",
                "id": "pat-1",
                "encounter": {"reference": "Encounter/enc-1"},
            }
        ),
    ]
    index = _build_encounter_resource_index(entries)
    assert set(index.keys()) == {"enc-1", "enc-2"}
    assert index["enc-1"]["MedicationRequest"] == [
        {"reference": "MedicationRequest/mr-aaaa", "display": "amlodipine 10mg"}
    ]
    assert index["enc-1"]["Observation"] == [{"reference": "Observation/obs-bbbb", "display": "BP"}]
    assert index["enc-2"]["Observation"] == [{"reference": "Observation/obs-cccc", "display": "HR"}]
    assert "MedicationRequest" not in index.get("enc-2", {})


# ------------------------------------------------------------------ #
# _derive_section_entries (generic)
# ------------------------------------------------------------------ #


@pytest.mark.unit
def test_derive_section_entries_returns_empty_when_no_index():
    assert _derive_section_entries("plan", "enc-1", None) == []


@pytest.mark.unit
def test_derive_section_entries_returns_empty_for_narrative_only_sections():
    index = {"enc-1": {"MedicationRequest": [{"reference": "MedicationRequest/mr-x"}]}}
    # subjective / chief_complaint / hpi are narrative-only.
    assert _derive_section_entries("subjective", "enc-1", index) == []
    assert _derive_section_entries("chief_complaint", "enc-1", index) == []
    assert _derive_section_entries("hpi", "enc-1", index) == []


@pytest.mark.unit
def test_derive_section_entries_plan_pulls_med_sr_procedure():
    index = {
        "enc-1": {
            "MedicationRequest": [{"reference": "MedicationRequest/mr-a"}],
            "ServiceRequest": [{"reference": "ServiceRequest/sr-b"}],
            "Procedure": [{"reference": "Procedure/proc-c"}],
            "Observation": [{"reference": "Observation/obs-d"}],  # NOT in plan bucket
        }
    }
    refs = _derive_section_entries("plan", "enc-1", index)
    assert {r["reference"] for r in refs} == {
        "MedicationRequest/mr-a",
        "ServiceRequest/sr-b",
        "Procedure/proc-c",
    }


# ------------------------------------------------------------------ #
# SOAP Composition — end-to-end via _build_composition (US path)
# ------------------------------------------------------------------ #


@pytest.mark.unit
def test_soap_composition_plan_section_has_medication_and_procedure_entries():
    index = {
        "ENC-001": {
            "MedicationRequest": [
                {"reference": "MedicationRequest/mr-a", "display": "amlodipine"},
                {"reference": "MedicationRequest/mr-b", "display": "aspirin"},
            ],
            "Observation": [
                {"reference": "Observation/obs-1"},
                {"reference": "Observation/obs-2"},
                {"reference": "Observation/obs-3"},
            ],
            "Condition": [{"reference": "Condition/cond-hypertension"}],
        }
    }
    doc = _soap_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "en", encounter_index=index)
    sections_by_title = {s["title"]: s for s in comp["section"]}
    # Plan (P) → 2 MedicationRequest entries.
    plan_entries = sections_by_title["plan"].get("entry") or []
    assert {e["reference"] for e in plan_entries} == {"MedicationRequest/mr-a", "MedicationRequest/mr-b"}
    # Objective (O) → 3 Observation entries.
    obj_entries = sections_by_title["objective"].get("entry") or []
    assert len(obj_entries) == 3
    assert all(r["reference"].startswith("Observation/") for r in obj_entries)
    # Assessment (A) → 1 Condition entry.
    assess_entries = sections_by_title["assessment"].get("entry") or []
    assert assess_entries == [{"reference": "Condition/cond-hypertension"}]
    # Subjective (S) → narrative-only, no entry key.
    assert "entry" not in sections_by_title["subjective"]


@pytest.mark.unit
def test_soap_composition_omits_entry_when_index_has_no_resources():
    """A section whose encounter carries zero eligible resources MUST
    omit `entry` (not emit `entry: []`) — Composition.section.entry
    is 0..* and the spec-clean shape is absent, not an empty array.
    """
    doc = _soap_doc(encounter_id="ENC-EMPTY")
    comp = _build_composition(doc, doc["narrative"]["sections"], "en", encounter_index={})
    for section in comp["section"]:
        assert "entry" not in section, f"section {section.get('title')} should have no `entry` key"


@pytest.mark.unit
def test_soap_composition_without_index_is_unchanged():
    """The pre-#925 shape (no `encounter_index` kwarg) must still work
    for callers that only feed the builder its doc + sections — the
    change is additive.
    """
    doc = _soap_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "en")
    for section in comp["section"]:
        assert "entry" not in section


# ------------------------------------------------------------------ #
# JP-CLINS discharge summary — extra entries via encounter_index
# ------------------------------------------------------------------ #


@pytest.mark.unit
def test_jp_clins_ds_populates_admission_diagnoses_from_primary_when_no_index():
    """342 (入院時診断) mirrors 344 (退院時診断) when the index is not
    consulted — clinosim's `clinical_diagnosis` carries a single
    primary shared between admission and discharge.
    """
    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    children = {c["code"]["coding"][0]["code"]: c for c in comp["section"][0]["section"]}
    assert "entry" in children["342"], "342 admission diagnoses should carry a Condition entry"
    assert children["342"]["entry"][0]["reference"].startswith("Condition/")


@pytest.mark.unit
def test_jp_clins_ds_444_populated_with_discharge_medication_requests():
    doc = _jp_ds_doc()
    index = {
        "ENC-002": {
            "MedicationRequest": [
                {"reference": "MedicationRequest/rxdc-aaa", "display": "レボフロキサシン"},
                {"reference": "MedicationRequest/rxdc-bbb", "display": "ロキソプロフェン"},
            ],
        }
    }
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja", encounter_index=index)
    children = {c["code"]["coding"][0]["code"]: c for c in comp["section"][0]["section"]}
    entries = children["444"].get("entry") or []
    assert {e["reference"] for e in entries} == {
        "MedicationRequest/rxdc-aaa",
        "MedicationRequest/rxdc-bbb",
    }


@pytest.mark.unit
def test_jp_clins_ds_344_extends_with_extra_conditions_from_index():
    """344 (退院時診断) keeps its templated primary Condition ref and
    appends any additional Conditions from the encounter index —
    de-duplicated so the primary is never doubled.
    """
    from clinosim.modules.output.fhir_r4.conditions.primary_ref import encounter_primary_condition_id

    doc = _jp_ds_doc()
    primary_ref = f"Condition/{encounter_primary_condition_id('POP-000002', 'ENC-002')}"
    index = {
        "ENC-002": {
            "Condition": [
                # Duplicate — must be de-duplicated.
                {"reference": primary_ref, "display": "急性腎盂腎炎"},
                {"reference": "Condition/cond-comorbid-hypertension", "display": "高血圧"},
            ],
        }
    }
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja", encounter_index=index)
    children = {c["code"]["coding"][0]["code"]: c for c in comp["section"][0]["section"]}
    entries = children["344"].get("entry") or []
    refs = [e["reference"] for e in entries]
    # Primary appears exactly once, plus the comorbidity.
    assert refs.count(primary_ref) == 1
    assert "Condition/cond-comorbid-hypertension" in refs
    assert len(refs) == 2


@pytest.mark.unit
def test_jp_clins_ds_444_absent_entry_when_no_medication_index():
    """Encounter with no MRs → 444 discharge_medications MUST NOT emit
    entry: [] (spec-clean absent, not empty array)."""
    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja", encounter_index={})
    children = {c["code"]["coding"][0]["code"]: c for c in comp["section"][0]["section"]}
    assert "entry" not in children["444"]
