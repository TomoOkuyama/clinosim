"""Regression guards for `MedicationAdministration.medicationCodeableConcept`
on US newborn-workup drugs (#1264).

Prior to the fix, the US drug catalog did not carry the newborn
Vitamin K1 or Erythromycin ophthalmic entries. The resolver's
longest-prefix match against `code_mapping_drug` failed, `base_name`
stayed at `.split(" ")[0]` = the first token, and `.text` shipped as a
useless single word:

    "Vitamin K1 (phytonadione) 1 mg IM" → .text = "Vitamin"
    "Erythromycin 0.5% ophthalmic ointment (Ilotycin)" → .text = "Erythromycin"

Both were indistinguishable from other drugs (Vitamin D adult supplement;
systemic Erythromycin antibiotic). Adding the two multi-word catalog keys
lets longest-prefix-match land at the correct dose-free drug identifier
and populate the RxNorm `.coding[0]` slot.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_admin


def test_us_newborn_vitamin_k1_medadmin_text_and_coding() -> None:
    mar = {
        "order_id": "ORD-VITK-1",
        "drug_name": "Vitamin K1 (phytonadione) 1 mg IM",
        "dose": "1 mg",
        "route": "IM",
        "status": "given",
        "scheduled_datetime": "2026-06-01T14:00:00",
        "actual_datetime": "2026-06-01T14:00:00",
    }
    resource = _build_medication_admin(
        mar,
        patient_id="POP-000001-BABY",
        index=0,
        country="US",
        encounter_id="ENC-000001-BABY-01",
    )
    med = resource["medicationCodeableConcept"]
    assert med["text"] == "Vitamin K1 (phytonadione)", f"Expected clean drug identifier; got {med.get('text')!r}"
    codings = med.get("coding") or []
    assert codings, "US Vitamin K1 must resolve to an RxNorm coding"
    assert codings[0].get("code") == "312424"
    assert "rxnorm" in codings[0].get("system", "").lower()


def test_us_newborn_erythromycin_ophthalmic_medadmin_text_and_coding() -> None:
    mar = {
        "order_id": "ORD-OPH-1",
        "drug_name": "Erythromycin 0.5% ophthalmic ointment (Ilotycin)",
        "dose": "1 cm ribbon each eye",
        "route": "OPH",
        "status": "given",
        "scheduled_datetime": "2026-06-01T10:30:00",
        "actual_datetime": "2026-06-01T10:30:00",
    }
    resource = _build_medication_admin(
        mar,
        patient_id="POP-000001-BABY",
        index=0,
        country="US",
        encounter_id="ENC-000001-BABY-01",
    )
    med = resource["medicationCodeableConcept"]
    assert med["text"] == "Erythromycin 0.5% ophthalmic ointment", (
        f"Expected drug identifier including 'ophthalmic'; got {med.get('text')!r}"
    )
    codings = med.get("coding") or []
    assert codings, "US Erythromycin ophthalmic must resolve to an RxNorm coding"
    assert codings[0].get("code") == "310149"
    assert "rxnorm" in codings[0].get("system", "").lower()


def test_us_medadmin_text_never_truncates_to_first_token() -> None:
    """Guard against the first-token-truncation regression class (#1264).
    The newborn-workup drug names are multi-word — the resolved `.text`
    must never be the single leading token.
    """
    for mar in (
        {
            "order_id": "O1",
            "drug_name": "Vitamin K1 (phytonadione) 1 mg IM",
            "dose": "1 mg",
            "route": "IM",
            "status": "given",
        },
        {
            "order_id": "O2",
            "drug_name": "Erythromycin 0.5% ophthalmic ointment (Ilotycin)",
            "dose": "1 cm ribbon each eye",
            "route": "OPH",
            "status": "given",
        },
    ):
        resource = _build_medication_admin(mar, patient_id="POP-1", index=0, country="US", encounter_id="ENC-1")
        text = resource["medicationCodeableConcept"]["text"]
        first_token = mar["drug_name"].split(" ")[0]
        assert text != first_token, f"regressed to first-token truncation: {text!r}"
