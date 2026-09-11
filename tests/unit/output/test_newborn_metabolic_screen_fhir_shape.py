"""Unit tests for the newborn metabolic-screen full FHIR shape
bundle-builders (#1252 N6b).

Emits three sibling resources from
``record.extensions["newborn"]["metabolic_screen"]``:

  * `ServiceRequest` — LOINC 54089-8 "Newborn screening panel"
  * `Specimen` — SNOMED 122554006 "Capillary blood specimen"
  * `DiagnosticReport` — LOINC 54089-8, conclusionCode carrying the
    same SNOMED pass / refer outcome as the sibling `Procedure`.

The existing `Procedure` for the physical heel-stick event
(`build_metabolic_screen_procedure`) is unchanged and continues to be
emitted by the shared `_bb_procedures` builder.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.newborn import enrich_newborn
from clinosim.modules.newborn.fhir_emit import (
    _bb_newborn_metabolic_screen_diagnostic_report,
    _bb_newborn_metabolic_screen_service_request,
    _bb_newborn_metabolic_screen_specimen,
)
from clinosim.types.clinical import ConditionEvent
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _newborn_record(patient_id: str = "POP-000001-BABY", los_days: int = 5) -> CIFPatientRecord:
    admit = datetime(2026, 6, 1, 10, 0)
    enc = Encounter(
        encounter_id=f"ENC-{patient_id}-01",
        patient_id=patient_id,
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=admit + timedelta(days=los_days),
    )
    return CIFPatientRecord(
        patient=PatientProfile(patient_id=patient_id, sex="M", age=0),
        encounters=[enc],
        condition_event=ConditionEvent(
            condition_id=f"COND-{patient_id}-BIRTH",
            condition_type="newborn_birth",
            ground_truth_diseases=["Z38.0"],
        ),
    )


def _run_enricher(record: CIFPatientRecord, country: str = "JP") -> None:
    ctx = SimpleNamespace(records=[record], config=SimpleNamespace(country=country))
    enrich_newborn(ctx)


def _build_ctx(record: CIFPatientRecord, country: str = "JP") -> SimpleNamespace:
    return SimpleNamespace(
        record=record,
        patient_id=record.patient.patient_id,
        country=country.lower(),
        primary_enc_id=record.encounters[0].encounter_id,
    )


# ---------------------------------------------------------------- SR


def test_metabolic_screen_service_request_jp_shape() -> None:
    rec = _newborn_record()
    _run_enricher(rec, country="JP")
    ctx = _build_ctx(rec, country="JP")
    out = _bb_newborn_metabolic_screen_service_request(ctx)
    assert len(out) == 1
    sr = out[0]
    assert sr["resourceType"] == "ServiceRequest"
    assert sr["status"] == "completed"
    assert sr["intent"] == "order"
    coding = sr["code"]["coding"][0]
    assert coding["code"] == "54089-8"
    assert coding["system"].endswith("loinc.org")
    cat = sr["category"][0]["coding"][0]
    assert cat["code"] == "108252007"
    assert cat["system"].endswith("snomed.info/sct")
    assert sr["subject"]["reference"].startswith("Patient/")
    assert sr["encounter"]["reference"].startswith("Encounter/")
    assert "authoredOn" in sr
    assert "occurrenceDateTime" in sr


def test_metabolic_screen_service_request_no_op_when_ext_absent() -> None:
    rec = _newborn_record()
    ctx = _build_ctx(rec, country="JP")
    # enricher NOT run — no extensions.newborn.metabolic_screen set
    assert _bb_newborn_metabolic_screen_service_request(ctx) == []


# ---------------------------------------------------------------- Specimen


def test_metabolic_screen_specimen_us_shape() -> None:
    rec = _newborn_record(los_days=2)  # US LOS
    _run_enricher(rec, country="US")
    ctx = _build_ctx(rec, country="US")
    out = _bb_newborn_metabolic_screen_specimen(ctx)
    assert len(out) == 1
    spec = out[0]
    assert spec["resourceType"] == "Specimen"
    assert spec["status"] == "available"
    type_coding = spec["type"]["coding"][0]
    assert type_coding["code"] == "122554006"
    assert type_coding["system"].endswith("snomed.info/sct")
    assert spec["subject"]["reference"].startswith("Patient/")
    coll = spec["collection"]
    assert "collectedDateTime" in coll
    # Body site + method emit as text only (no SNOMED coding) — the
    # feedback_verify_fhir_profile_uri_from_spec rule forbids fabricating
    # unverified codes. Confirm text is populated and no coding leaked.
    assert coll["bodySite"] == {"text": "Heel"}
    assert coll["method"] == {"text": "Heel-stick capillary blood collection"}


def test_metabolic_screen_specimen_jp_shape_is_japanese_text() -> None:
    rec = _newborn_record()
    _run_enricher(rec, country="JP")
    ctx = _build_ctx(rec, country="JP")
    out = _bb_newborn_metabolic_screen_specimen(ctx)
    assert out[0]["collection"]["bodySite"] == {"text": "踵"}
    assert out[0]["collection"]["method"] == {"text": "踵採血 (毛細血管採血)"}


# ---------------------------------------------------------------- DR


def test_metabolic_screen_diagnostic_report_shape() -> None:
    rec = _newborn_record()
    _run_enricher(rec, country="JP")
    ctx = _build_ctx(rec, country="JP")
    out = _bb_newborn_metabolic_screen_diagnostic_report(ctx)
    assert len(out) == 1
    dr = out[0]
    assert dr["resourceType"] == "DiagnosticReport"
    assert dr["status"] == "final"
    coding = dr["code"]["coding"][0]
    assert coding["code"] == "54089-8"
    cat = dr["category"][0]["coding"][0]
    assert cat["code"] == "LAB"
    # Cross-reference to SR + Specimen
    assert len(dr["basedOn"]) == 1
    assert dr["basedOn"][0]["reference"].startswith("ServiceRequest/")
    assert len(dr["specimen"]) == 1
    assert dr["specimen"][0]["reference"].startswith("Specimen/")
    # Aggregate verdict via conclusionCode + conclusion text
    assert "conclusionCode" in dr
    outcome_code = dr["conclusionCode"][0]["coding"][0]["code"]
    assert outcome_code in ("385669000", "385671000")
    assert "conclusion" in dr and len(dr["conclusion"]) > 0
    # Effective + issued timestamps present
    assert "effectiveDateTime" in dr
    assert "issued" in dr


def test_metabolic_screen_dr_conclusioncode_matches_procedure_outcome() -> None:
    """DR.conclusionCode + Procedure.outcome_code must always agree —
    both sample the same sub-seed keyed on `patient_id`. If they
    diverge, downstream consumers see contradictory pass / refer
    verdicts for the same physical event.
    """
    for i in range(30):
        rec = _newborn_record(f"POP-{i:05d}-BABY")
        _run_enricher(rec, country="JP")
        ctx = _build_ctx(rec, country="JP")
        dr_list = _bb_newborn_metabolic_screen_diagnostic_report(ctx)
        procs = [p for p in rec.procedures if p.procedure_type == "metabolic_screen_tandem_ms"]
        assert dr_list and procs
        dr_outcome = dr_list[0]["conclusionCode"][0]["coding"][0]["code"]
        assert dr_outcome == procs[0].outcome_code, (
            f"[{i}] DR outcome {dr_outcome!r} != Procedure outcome {procs[0].outcome_code!r}"
        )


# ---------------------------------------------------------------- cross-ref IDs


def test_metabolic_screen_dr_references_sr_and_specimen_by_derived_id() -> None:
    """The DR's basedOn / specimen references must resolve to the SAME
    ids emitted by the SR + Specimen builders — cross-resource id
    consistency check.
    """
    rec = _newborn_record()
    _run_enricher(rec, country="JP")
    ctx = _build_ctx(rec, country="JP")
    sr = _bb_newborn_metabolic_screen_service_request(ctx)[0]
    spec = _bb_newborn_metabolic_screen_specimen(ctx)[0]
    dr = _bb_newborn_metabolic_screen_diagnostic_report(ctx)[0]
    assert dr["basedOn"][0]["reference"] == f"ServiceRequest/{sr['id']}"
    assert dr["specimen"][0]["reference"] == f"Specimen/{spec['id']}"


# ---------------------------------------------------------------- adult / no-op


def test_metabolic_screen_bundle_builders_no_op_on_non_newborn() -> None:
    adult = CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-ADULT", sex="F", age=45),
        encounters=[
            Encounter(
                encounter_id="ENC-ADULT-01",
                patient_id="POP-ADULT",
                encounter_type=EncounterType.INPATIENT,
                admission_datetime=datetime(2026, 6, 1, 10, 0),
                discharge_datetime=datetime(2026, 6, 3, 10, 0),
            )
        ],
        condition_event=ConditionEvent(condition_type="pneumonia_acute"),
    )
    _run_enricher(adult, country="JP")
    ctx = _build_ctx(adult, country="JP")
    assert _bb_newborn_metabolic_screen_service_request(ctx) == []
    assert _bb_newborn_metabolic_screen_specimen(ctx) == []
    assert _bb_newborn_metabolic_screen_diagnostic_report(ctx) == []
