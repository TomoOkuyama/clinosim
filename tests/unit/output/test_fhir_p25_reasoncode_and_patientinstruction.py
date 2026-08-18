"""Session-88j P2-5: Procedure.reasonCode coded emit + MedicationRequest
(dosage) patientInstruction derivation.

Before: `Procedure.reasonCode` was a text-only "入院時診断に基づく処置" /
"Procedure indicated by encounter diagnosis" generic template regardless
of the encounter's actual clinical diagnosis. `dosageInstruction[].patientInstruction`
was never populated.

After: reasonCode gets a real ICD-10 coding derived from the encounter's
`clinical_diagnosis` when available; falls back to the generic text when
no dx is on record. patientInstruction is derived from common frequency
labels (qhs → 就寝前, ac → 食前, pc → 食後, prn → 頓用) so the JP
consumer sees an actionable phrase, not just the structured timing.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.lib.common import build_dosage_instruction
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

# --- P2-5b: patientInstruction derivation from frequency label ---


def test_patient_instruction_qhs_ja():
    order = {"dose_quantity": 5.0, "dose_unit": "mg", "route": "oral", "frequency": "qhs"}
    dosage = build_dosage_instruction(order, country="jp")
    assert dosage is not None
    assert dosage.get("patientInstruction") == "就寝前"


def test_patient_instruction_qhs_en():
    order = {"dose_quantity": 5.0, "dose_unit": "mg", "route": "oral", "frequency": "qhs"}
    dosage = build_dosage_instruction(order, country="us")
    assert dosage is not None
    assert dosage.get("patientInstruction") == "at bedtime"


def test_patient_instruction_prn_ja():
    order = {"dose_quantity": 500, "dose_unit": "mg", "route": "oral", "frequency": "prn"}
    dosage = build_dosage_instruction(order, country="jp")
    assert dosage is not None
    assert dosage["patientInstruction"] == "頓用（必要時）"


def test_patient_instruction_pc_ja():
    """食後 (after meals) ja localization."""
    order = {"dose_quantity": 5, "dose_unit": "mg", "route": "oral", "frequency": "pc"}
    dosage = build_dosage_instruction(order, country="jp")
    assert dosage["patientInstruction"] == "食後"


def test_patient_instruction_en_freq_qd_derives_ja_phrase():
    """session-88j Bug-2 fix follow-up: CIF Order.frequency uses EN
    abbreviations (qd, bid, tid, qid) — the DERIVED display 「1日1回」
    only appears in dosage.text after post-processing. Map at emit
    time so patientInstruction is populated for these primary keys."""
    for freq, expected in [
        ("qd", "毎日1回、指示された時間帯に内服してください"),
        ("bid", "毎日2回、朝・夕の指示された時間帯に内服してください"),
        ("tid", "毎日3回、朝・昼・夕の指示された時間帯に内服してください"),
        ("qid", "毎日4回、指示された時間帯に内服してください"),
        ("q6h", "6時間ごとに内服してください"),
    ]:
        order = {"dose_quantity": 10, "dose_unit": "mg", "route": "oral", "frequency": freq}
        dosage = build_dosage_instruction(order, country="jp")
        assert dosage is not None
        assert dosage.get("patientInstruction") == expected, f"freq={freq}: got {dosage.get('patientInstruction')}"


def test_patient_instruction_ja_freq_1nichi_1kai():
    """session-88j Bug-2 fix: CIF's native JA freq strings (「1日1回」/「1日2回」/…)
    were not recognized by the EN-only derivation map, so 12% of
    MedicationRequest fell into a bucket with an empty patientInstruction.
    Verify the JA freq keys now produce an actionable JA phrase."""
    for freq, expected in [
        ("1日1回", "毎日1回、指示された時間帯に内服してください"),
        ("1日2回", "毎日2回、朝・夕の指示された時間帯に内服してください"),
        ("1日3回", "毎日3回、朝・昼・夕の指示された時間帯に内服してください"),
        ("頓服", "症状のある時にのみ服用してください"),
        ("頓用", "症状のある時にのみ服用してください"),
        ("6時間ごと", "6時間ごとに内服してください"),
    ]:
        order = {"dose_quantity": 10, "dose_unit": "mg", "route": "oral", "frequency": freq}
        dosage = build_dosage_instruction(order, country="jp")
        assert dosage is not None
        assert dosage.get("patientInstruction") == expected, f"freq={freq}: got {dosage.get('patientInstruction')}"


def test_patient_instruction_ja_freq_ignored_under_en():
    """JA freq strings should not derive an EN instruction (they only
    exist as JA in this map)."""
    order = {"dose_quantity": 10, "dose_unit": "mg", "route": "oral", "frequency": "1日1回"}
    dosage = build_dosage_instruction(order, country="us")
    # No derivation for JA-only key under EN — behavior unchanged.
    assert "patientInstruction" not in (dosage or {})


def test_patient_instruction_authored_beats_derived():
    """CIF-authored patient_instruction wins over the derived phrase (Issue #476 opt-in)."""
    order = {
        "dose_quantity": 5,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "qhs",
        "patient_instruction": "就寝直前、就床 30 分前",  # more specific than the derived "就寝前"
    }
    dosage = build_dosage_instruction(order, country="jp")
    assert dosage["patientInstruction"] == "就寝直前、就床 30 分前"


def test_patient_instruction_authored_when_no_freq_derivation():
    """Authored instruction still emits even for freqs without a derived phrase."""
    order = {
        "dose_quantity": 10,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "qd",  # no derivation
        "patient_instruction": "毎朝、食後 30 分以内",
    }
    dosage = build_dosage_instruction(order, country="jp")
    assert dosage["patientInstruction"] == "毎朝、食後 30 分以内"


# --- P2-5a: Procedure.reasonCode with real ICD-10 coding ---


def _minimal_procedure_record(dx_code: str, dx_display: str = "") -> dict:
    """Minimum record shape needed by _build_procedure for reasonCode."""
    return {
        "patient": {"patient_id": "POP-999999"},
        "clinical_diagnosis": {
            "discharge_diagnosis_code": dx_code,
            "discharge_diagnosis_display": dx_display,
        },
    }


def _minimal_procedure() -> dict:
    return {
        "procedure_id": "proc-ENC-999999-1-0",
        "encounter_id": "ENC-999999-1",
        "code": "K664",
        "display_name": "内視鏡的胃粘膜下層剥離術",
        "start_datetime": "2026-08-18T09:00:00+09:00",
        "status": "completed",
    }


def test_procedure_reasoncode_carries_real_icd10_jp():
    """When clinical_diagnosis has a discharge dx code, Procedure.reasonCode
    now carries the ICD-10 coding + display + text (was text-only generic)."""
    record = _minimal_procedure_record("C16.0", "胃噴門部の悪性新生物")
    resource = _build_procedure(
        proc=_minimal_procedure(),
        patient_id="POP-999999",
        index=0,
        country="jp",
        record=record,
    )
    rc = resource.get("reasonCode")
    assert rc and len(rc) == 1
    coding = rc[0]["coding"][0]
    assert coding["code"] == "C16.0"
    # MHLW system URI for JP encounter dx (system_key_for("diagnosis", "jp"))
    assert "mhlw" in coding["system"].lower() or "icd" in coding["system"].lower()
    assert coding["display"] == "胃噴門部の悪性新生物"
    assert rc[0]["text"] == "胃噴門部の悪性新生物"


def test_procedure_reasoncode_falls_back_to_generic_text_when_no_dx():
    record = {"patient": {"patient_id": "POP-999999"}, "clinical_diagnosis": {}}
    resource = _build_procedure(
        proc=_minimal_procedure(),
        patient_id="POP-999999",
        index=1,
        country="jp",
        record=record,
    )
    rc = resource.get("reasonCode")
    assert rc and rc[0].get("text") == "入院時診断に基づく処置"
    assert "coding" not in rc[0]


def test_procedure_reasoncode_english_display():
    record = _minimal_procedure_record("I25.1", "")  # no display, will resolve via code_lookup
    resource = _build_procedure(
        proc=_minimal_procedure(),
        patient_id="POP-999999",
        index=2,
        country="us",
        record=record,
    )
    rc = resource.get("reasonCode")
    assert rc and rc[0]["coding"][0]["code"] == "I25.1"
    # display resolved (or code fallback)
    assert rc[0]["coding"][0].get("display")


def test_patient_instruction_derives_from_freq_per_day_when_freq_empty():
    """session-88j Bug-2 follow-up-2: some orders carry only
    `frequency_per_day` (integer) without a raw `frequency` string —
    derive PI from the integer via the pd→key map (1=qd, 2=bid, …).
    """
    order = {"dose_quantity": 20, "dose_unit": "mg", "route": "oral", "frequency_per_day": 1}
    dosage = build_dosage_instruction(order, country="jp")
    assert dosage is not None
    assert dosage.get("patientInstruction") == "毎日1回、指示された時間帯に内服してください"
