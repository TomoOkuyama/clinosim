"""Issue #1307 — regression: pregnancy complications O14 / O24 / O42 /
O60 / O64 (and any other ``clinical_diagnosis.working_diagnoses`` entry)
never emitted a FHIR Condition.

PR #1293 populated ``ClinicalDiagnosis.working_diagnoses`` from the
pregnancy TemporalStatePeriod at delivery encounter time, but no FHIR
builder read that field back — 0 O-code Conditions on p=10k builds.

The fix in ``modules/output/fhir_r4/conditions/conditions.py::_build_conditions``
adds a per-``working_diagnoses``-entry Condition emit loop.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions
from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
    encounter_secondary_condition_id,
    encounter_secondary_condition_key,
)


def _record_with_working_dx(disease_ids: list[str]) -> dict:
    return {
        "patient": {"patient_id": "POP-000042", "sex": "F"},
        "clinical_diagnosis": {
            "admission_diagnosis_code": "O80",
            "discharge_diagnosis_code": "Z37.0",
            "working_diagnoses": [
                {
                    "disease_id": code,
                    "onset_day": 0,
                    "onset_datetime": "2026-06-22T10:03:00",
                }
                for code in disease_ids
            ],
        },
        "encounters": [
            {
                "encounter_id": "enc-delivery-42",
                "encounter_type": "inpatient",
                "admission_datetime": "2026-06-22T10:03:00",
                "discharge_datetime": "2026-06-24T14:30:00",
                "attending_physician_id": "DR-OB-001",
                "status": "completed",
            },
        ],
        "deceased": False,
    }


def _codes(conditions: list[dict]) -> list[str]:
    out: list[str] = []
    for c in conditions:
        for coding in c.get("code", {}).get("coding", []):
            out.append(coding.get("code", ""))
    return out


def test_pregnancy_complications_emit_conditions():
    # Two Bernoulli-sampled complications carried onto the delivery
    # encounter's working_diagnoses.
    rec = _record_with_working_dx(["O24.9", "O42.9"])
    conds = _build_conditions(rec, patient_id="pt-42", country="US")
    codes = _codes(conds)
    assert "O24.9" in codes, f"O24.9 missing from emitted Conditions: {codes}"
    assert "O42.9" in codes, f"O42.9 missing from emitted Conditions: {codes}"


def test_secondary_condition_id_is_deterministic_and_indexed():
    rec = _record_with_working_dx(["O24.9", "O42.9"])
    conds = _build_conditions(rec, patient_id="pt-42", country="US")
    # Locate the two secondary Conditions by id.
    expected_0 = encounter_secondary_condition_id("pt-42", "enc-delivery-42", 0)
    expected_1 = encounter_secondary_condition_id("pt-42", "enc-delivery-42", 1)
    ids = [c["id"] for c in conds]
    assert expected_0 in ids
    assert expected_1 in ids


def test_secondary_condition_carries_encounter_diagnosis_category():
    rec = _record_with_working_dx(["O24.9"])
    conds = _build_conditions(rec, patient_id="pt-42", country="US")
    for c in conds:
        codes = _codes([c])
        if "O24.9" in codes:
            cats = [x.get("code") for cat in c.get("category", []) for x in cat.get("coding", [])]
            assert "encounter-diagnosis" in cats
            break
    else:
        raise AssertionError("O24.9 Condition not found")


def test_secondary_condition_onset_uses_entry_timestamp():
    rec = _record_with_working_dx(["O24.9"])
    conds = _build_conditions(rec, patient_id="pt-42", country="US")
    for c in conds:
        if "O24.9" not in _codes([c]):
            continue
        assert c.get("onsetDateTime", "").startswith("2026-06-22")
        break


def test_secondary_condition_deduped_against_primary():
    # If a working_diagnoses entry shares its ICD base with the encounter
    # primary diagnosis, the primary owns that row — no duplicate secondary.
    rec = _record_with_working_dx(["Z37.0"])  # same base as discharge_dx
    conds = _build_conditions(rec, patient_id="pt-42", country="US")
    # Count Z37-coded Conditions — must be exactly one (the primary).
    z37_hits = sum(1 for c in conds if any(x.startswith("Z37") for x in _codes([c])))
    assert z37_hits == 1, f"Z37 duplicated: {z37_hits} Conditions"


def test_no_working_diagnoses_no_secondary_conditions():
    rec = _record_with_working_dx([])
    conds = _build_conditions(rec, patient_id="pt-42", country="US")
    # No secondary key present in any id.
    for c in conds:
        assert "-secondary-" not in encounter_secondary_condition_key("pt-42", "enc-delivery-42", 0) or c[
            "id"
        ] != encounter_secondary_condition_id("pt-42", "enc-delivery-42", 0)


def test_in_hospital_complication_gets_distinguishing_evidence_label():
    rec = _record_with_working_dx(["O24.9"])
    # Overwrite source on the first entry.
    rec["clinical_diagnosis"]["working_diagnoses"][0]["source"] = "in_hospital_complication"
    conds = _build_conditions(rec, patient_id="pt-42", country="US")
    for c in conds:
        if "O24.9" not in _codes([c]):
            continue
        ev_text = (c.get("evidence") or [{}])[0].get("code", [{}])[0].get("text", "")
        assert "In-hospital complication" in ev_text
        break
