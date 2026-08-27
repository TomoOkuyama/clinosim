"""Unit tests for _fhir_clinical_impression builder (Tier 1 #3 α-min-1 Task 9)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from clinosim.modules.document import CLINICAL_IMPRESSION_ID_PREFIX
from clinosim.modules.output.fhir_r4.conditions.clinical_impression import _bb_clinical_impressions
from clinosim.modules.output.fhir_r4.demographics.patient import resolve_patient_id
from clinosim.modules.output.fhir_r4.encounters.encounter import resolve_encounter_id
from clinosim.types.clinical import ClinicalImpressionRecord


def _make_ctx(impressions, country="us"):
    return SimpleNamespace(
        record={"extensions": {"clinical_impressions": impressions}, "patient": {}},
        country=country,
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        patient_sex="",
    )


def _sample_impression_dataclass() -> ClinicalImpressionRecord:
    return ClinicalImpressionRecord(
        impression_id="ci-enc1-0",
        encounter_id="enc1",
        date=date(2026, 7, 1),
        day_index=0,
        description="Day 0: Admitted with pneumonia.",
        summary="Patient in stable condition. IV antibiotics initiated.",
        investigation_refs=["lab-enc1-wbc-0", "lab-enc1-crp-0"],
        finding_refs=["cond-enc1-j18"],
        prognosis="Favorable with antibiotic therapy.",
        practitioner_id="staff-001",
    )


def _sample_impression_dict() -> dict:
    return {
        "impression_id": "ci-enc1-0",
        "encounter_id": "enc1",
        "date": date(2026, 7, 1),
        "day_index": 0,
        "description": "Day 0: Admitted with pneumonia.",
        "summary": "Patient in stable condition. IV antibiotics initiated.",
        "investigation_refs": ["lab-enc1-wbc-0", "lab-enc1-crp-0"],
        "finding_refs": ["cond-enc1-j18"],
        "prognosis": "Favorable with antibiotic therapy.",
        "practitioner_id": "staff-001",
    }


# --- Empty input ---


def test_no_impressions_emits_nothing():
    ctx = _make_ctx([])
    assert _bb_clinical_impressions(ctx) == []


def test_missing_extension_emits_nothing():
    ctx = SimpleNamespace(
        record={"extensions": {}, "patient": {}},
        country="us",
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        patient_sex="",
    )
    assert _bb_clinical_impressions(ctx) == []


# --- Resource shape ---


def test_emits_one_clinical_impression_dataclass():
    ctx = _make_ctx([_sample_impression_dataclass()])
    resources = _bb_clinical_impressions(ctx)
    assert len(resources) == 1
    assert resources[0]["resourceType"] == "ClinicalImpression"


def test_clinical_impression_id_uses_prefix():
    ctx = _make_ctx([_sample_impression_dataclass()])
    r = _bb_clinical_impressions(ctx)[0]
    assert r["id"].startswith(CLINICAL_IMPRESSION_ID_PREFIX)
    # impression_id already has the prefix "ci-enc1-0"
    # Issue #854 Bucket B (PR-clinical-impression): CI.id opaque.
    from clinosim.modules.output.fhir_r4.conditions.clinical_impression import (
        _resolve_clinical_impression_id,
    )

    assert r["id"] == _resolve_clinical_impression_id("enc1-0")


def test_status_is_completed():
    ctx = _make_ctx([_sample_impression_dataclass()])
    r = _bb_clinical_impressions(ctx)[0]
    assert r["status"] == "completed"


def test_subject_patient_ref():
    ctx = _make_ctx([_sample_impression_dataclass()])
    r = _bb_clinical_impressions(ctx)[0]
    assert r["subject"]["reference"] == f"Patient/{resolve_patient_id('pt1')}"


def test_encounter_ref():
    ctx = _make_ctx([_sample_impression_dataclass()])
    r = _bb_clinical_impressions(ctx)[0]
    assert r["encounter"]["reference"] == f"Encounter/{resolve_encounter_id('enc1')}"


def test_effective_datetime():
    ctx = _make_ctx([_sample_impression_dataclass()])
    r = _bb_clinical_impressions(ctx)[0]
    assert r["effectiveDateTime"] == "2026-07-01"


def test_description_field():
    ctx = _make_ctx([_sample_impression_dataclass()])
    r = _bb_clinical_impressions(ctx)[0]
    assert r["description"] == "Day 0: Admitted with pneumonia."


def test_summary_field():
    ctx = _make_ctx([_sample_impression_dataclass()])
    r = _bb_clinical_impressions(ctx)[0]
    assert r["summary"] == "Patient in stable condition. IV antibiotics initiated."


def test_assessor_ref():
    ctx = _make_ctx([_sample_impression_dataclass()])
    r = _bb_clinical_impressions(ctx)[0]
    assert r["assessor"]["reference"] == "Practitioner/staff-001"


def test_investigation_refs_emitted():
    ctx = _make_ctx([_sample_impression_dataclass()])
    r = _bb_clinical_impressions(ctx)[0]
    assert "investigation" in r
    inv = r["investigation"][0]
    assert inv["code"]["text"] == "Investigations"
    items = inv["item"]
    assert {"reference": "Observation/lab-enc1-wbc-0"} in items
    assert {"reference": "Observation/lab-enc1-crp-0"} in items


def test_finding_refs_emitted():
    ctx = _make_ctx([_sample_impression_dataclass()])
    r = _bb_clinical_impressions(ctx)[0]
    assert "finding" in r
    finding = r["finding"][0]
    assert finding["itemReference"]["reference"] == "Condition/cond-enc1-j18"


def test_prognosis_emitted():
    ctx = _make_ctx([_sample_impression_dataclass()])
    r = _bb_clinical_impressions(ctx)[0]
    assert "prognosisCodeableConcept" in r
    assert r["prognosisCodeableConcept"][0]["text"] == "Favorable with antibiotic therapy."


# --- Empty optional fields ---


def test_empty_investigation_refs_omits_investigation():
    imp = _sample_impression_dataclass()
    imp.investigation_refs = []
    ctx = _make_ctx([imp])
    r = _bb_clinical_impressions(ctx)[0]
    assert "investigation" not in r


def test_empty_finding_refs_omits_finding():
    imp = _sample_impression_dataclass()
    imp.finding_refs = []
    ctx = _make_ctx([imp])
    r = _bb_clinical_impressions(ctx)[0]
    assert "finding" not in r


def test_empty_prognosis_omits_prognosis():
    imp = _sample_impression_dataclass()
    imp.prognosis = ""
    ctx = _make_ctx([imp])
    r = _bb_clinical_impressions(ctx)[0]
    assert "prognosisCodeableConcept" not in r


def test_empty_practitioner_omits_assessor():
    imp = _sample_impression_dataclass()
    imp.practitioner_id = ""
    ctx = _make_ctx([imp])
    r = _bb_clinical_impressions(ctx)[0]
    assert "assessor" not in r


def test_empty_encounter_id_omits_encounter():
    imp = _sample_impression_dataclass()
    imp.encounter_id = ""
    ctx = _make_ctx([imp])
    r = _bb_clinical_impressions(ctx)[0]
    assert "encounter" not in r


# --- Dict path ---


def test_clinical_impression_from_dict_path():
    """Production CIF is json.load() -> dict; verify _o() dict-access path."""
    ctx = _make_ctx([_sample_impression_dict()])
    resources = _bb_clinical_impressions(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "ClinicalImpression"
    # Issue #854 Bucket B (PR-clinical-impression): CI.id opaque.
    from clinosim.modules.output.fhir_r4.conditions.clinical_impression import (
        _resolve_clinical_impression_id,
    )

    assert r["id"] == _resolve_clinical_impression_id("enc1-0")
    assert r["status"] == "completed"
    assert r["subject"]["reference"] == f"Patient/{resolve_patient_id('pt1')}"
    assert r["encounter"]["reference"] == f"Encounter/{resolve_encounter_id('enc1')}"
    assert r["effectiveDateTime"] == "2026-07-01"
    assert r["description"] == "Day 0: Admitted with pneumonia."


# --- Multiple impressions ---


def test_multiple_impressions_all_emitted():
    imp1 = _sample_impression_dataclass()
    imp2 = _sample_impression_dataclass()
    imp2.impression_id = "ci-enc1-1"
    imp2.day_index = 1
    imp2.description = "Day 1: Improving."
    ctx = _make_ctx([imp1, imp2])
    resources = _bb_clinical_impressions(ctx)
    assert len(resources) == 2
    from clinosim.modules.output.fhir_r4.conditions.clinical_impression import (
        _resolve_clinical_impression_id,
    )

    ids = {r["id"] for r in resources}
    assert _resolve_clinical_impression_id("enc1-0") in ids
    assert _resolve_clinical_impression_id("enc1-1") in ids


# --- ID prefix handling ---


def test_id_without_prefix_gets_prefix():
    """If impression_id doesn't already start with ci-, add the prefix."""
    d = _sample_impression_dict()
    d["impression_id"] = "enc1-0"  # no prefix
    ctx = _make_ctx([d])
    r = _bb_clinical_impressions(ctx)[0]
    # Issue #854 Bucket B (PR-clinical-impression): both prefixed and
    # unprefixed CIF ids resolve to the same opaque id (idempotent).
    from clinosim.modules.output.fhir_r4.conditions.clinical_impression import (
        _resolve_clinical_impression_id,
    )

    assert r["id"] == _resolve_clinical_impression_id("enc1-0")


def test_id_with_prefix_not_doubled():
    """If impression_id already starts with ci-, don't double it."""
    d = _sample_impression_dict()
    d["impression_id"] = "ci-enc1-0"  # already prefixed
    ctx = _make_ctx([d])
    r = _bb_clinical_impressions(ctx)[0]
    # Issue #854 Bucket B (PR-clinical-impression): CI.id opaque.
    from clinosim.modules.output.fhir_r4.conditions.clinical_impression import (
        _resolve_clinical_impression_id,
    )

    assert r["id"] == _resolve_clinical_impression_id("enc1-0")
    assert not r["id"].startswith("ci-ci-")


# --- session-88j P1-12: LOINC visit-type code emit ---


def test_code_loinc_emit_admission_h_and_p():
    """code_loinc=34117-2 → ClinicalImpression.code populated with LOINC + text."""
    imp = _sample_impression_dataclass()
    imp.code_loinc = "34117-2"
    imp.code_loinc_display = "入院時記録"
    ctx = _make_ctx([imp], country="jp")
    r = _bb_clinical_impressions(ctx)[0]
    assert "code" in r
    coding = r["code"]["coding"][0]
    assert coding["system"] == "http://loinc.org"
    assert coding["code"] == "34117-2"
    assert coding["display"] == "入院時記録"
    assert r["code"]["text"] == "入院時記録"


def test_code_loinc_emit_progress_note_en():
    """Progress note (11506-3) with English display."""
    d = _sample_impression_dict()
    d["code_loinc"] = "11506-3"
    d["code_loinc_display"] = "Progress note"
    ctx = _make_ctx([d], country="us")
    r = _bb_clinical_impressions(ctx)[0]
    assert r["code"]["coding"][0]["code"] == "11506-3"
    assert r["code"]["coding"][0]["display"] == "Progress note"
    assert r["code"]["text"] == "Progress note"


def test_code_loinc_emit_discharge_summary():
    """Discharge summary (18842-5)."""
    imp = _sample_impression_dataclass()
    imp.code_loinc = "18842-5"
    imp.code_loinc_display = "退院時サマリー"
    ctx = _make_ctx([imp], country="jp")
    r = _bb_clinical_impressions(ctx)[0]
    assert r["code"]["coding"][0]["code"] == "18842-5"
    assert r["code"]["text"] == "退院時サマリー"


def test_code_loinc_absent_omits_code_field():
    """Backwards compat: empty code_loinc ⇒ builder omits `code`."""
    imp = _sample_impression_dataclass()
    # code_loinc defaults to "" — do not set
    ctx = _make_ctx([imp])
    r = _bb_clinical_impressions(ctx)[0]
    assert "code" not in r


def test_code_loinc_without_display_still_emits_coding():
    """code_loinc set but display empty → coding.display omitted, no text."""
    d = _sample_impression_dict()
    d["code_loinc"] = "11506-3"
    # code_loinc_display intentionally left blank
    ctx = _make_ctx([d])
    r = _bb_clinical_impressions(ctx)[0]
    assert r["code"]["coding"][0]["code"] == "11506-3"
    assert "display" not in r["code"]["coding"][0]
    assert "text" not in r["code"]
