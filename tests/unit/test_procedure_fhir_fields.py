"""Tests for FHIR Procedure structural fields (category, performer.function,
reasonReference, bodySite, location, outcome, complication)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.output.fhir_r4_adapter import _build_procedure
from clinosim.modules.procedure.engine import (
    _PROCEDURE_METADATA,
    generate_bedside_procedures,
    simulate_surgery,
)
from clinosim.types.patient import ChronicCondition, PatientProfile


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def hip_patient():
    return PatientProfile(
        patient_id="PAT-HIP",
        age=82,
        sex="F",
        chronic_conditions=[
            ChronicCondition(code="I10", severity_score=0.2),
            ChronicCondition(code="M81", severity_score=0.3),
        ],
    )


class _HipProtocol:
    procedure = {
        "typical_duration_minutes": {"mean": 90, "sd": 30},
        "anesthesia": "spinal or general",
        "estimated_blood_loss_ml": {"mean": 300, "sd": 150},
    }


# ---------------------------------------------------------------------------
# Metadata table
# ---------------------------------------------------------------------------


def test_metadata_covers_all_bedside_procedures():
    """Every bedside procedure type must have a metadata entry."""
    from clinosim.modules.procedure.engine import _BEDSIDE_PROCEDURES

    for spec in _BEDSIDE_PROCEDURES:
        proc_type = spec[0]
        assert proc_type in _PROCEDURE_METADATA, f"missing metadata for {proc_type}"
        meta = _PROCEDURE_METADATA[proc_type]
        assert meta.category_code, f"{proc_type} has empty category_code"


def test_metadata_covers_surgery_types():
    for proc_type in ("ORIF", "hemiarthroplasty", "surgery"):
        assert proc_type in _PROCEDURE_METADATA
        assert _PROCEDURE_METADATA[proc_type].category_code == "387713003"


# ---------------------------------------------------------------------------
# Engine — new fields populated
# ---------------------------------------------------------------------------


def test_simulate_surgery_populates_fhir_fields(hip_patient, rng):
    record, _impacts = simulate_surgery(
        patient=hip_patient,
        disease_id="hip_fracture",
        encounter_id="ENC-1",
        admission_time=datetime(2026, 4, 6, 14, 0),
        protocol=_HipProtocol(),
        rng=rng,
        country="JP",
        surgeon_id="DR-SU-001",
        anesthesiologist_id="DR-AN-001",
        operating_rooms=3,
    )
    assert record.category_code == "387713003"  # Surgical procedure
    assert record.body_site_code in {"71341001", "29836001"}  # femur or hip
    assert record.outcome_code in {"385669000", "385670004"}
    assert record.location_id.startswith("loc-or-")


def test_generate_bedside_procedures_populates_metadata(rng):
    procs = generate_bedside_procedures(
        patient_id="PAT-SEP",
        encounter_id="ENC-SEP",
        disease_id="sepsis",
        admission_time=datetime(2026, 4, 6, 10, 0),
        severity="severe",
        rng=rng,
        country="JP",
    )
    assert len(procs) > 0
    for p in procs:
        assert p.category_code  # every bedside proc has a category
        assert p.outcome_code == "385669000"  # default success


# ---------------------------------------------------------------------------
# FHIR adapter — structural fields emitted correctly
# ---------------------------------------------------------------------------


def _proc_dict(**overrides) -> dict:
    base = {
        "procedure_id": "PROC-PAT-001",
        "patient_id": "PAT-001",
        "encounter_id": "ENC-PAT-001-0001",
        "procedure_type": "ORIF",
        "procedure_code": "27236",
        "procedure_name": "Open reduction internal fixation",
        "start_datetime": "2026-04-06T14:30:00",
        "end_datetime": "2026-04-06T16:00:00",
        "duration_minutes": 90,
        "primary_surgeon_id": "DR-SU-001",
        "anesthesiologist_id": "DR-AN-001",
        "anesthesia_type": "general",
        "asa_class": 3,
        "estimated_blood_loss_ml": 320,
        "specimens_sent": [],
        "implants_used": ["intramedullary nail"],
        "intraop_complications": [],
        "preop_diagnosis": "hip_fracture",
        "postop_diagnosis": "hip_fracture",
        "category_code": "387713003",
        "body_site_code": "71341001",
        "outcome_code": "385669000",
        "complication_codes": [],
        "location_id": "loc-or-2",
    }
    base.update(overrides)
    return base


def test_fhir_procedure_has_category():
    r = _build_procedure(_proc_dict(), "PAT-001", 0, "US")
    assert r["category"]["coding"][0]["code"] == "387713003"
    assert r["category"]["coding"][0]["display"] == "Surgical procedure"


def test_fhir_procedure_has_performer_function():
    r = _build_procedure(_proc_dict(), "PAT-001", 0, "US")
    performers = r["performer"]
    assert len(performers) == 2
    surgeon = performers[0]
    assert surgeon["function"]["coding"][0]["code"] == "304292004"
    assert surgeon["function"]["coding"][0]["display"] == "Surgeon"
    assert surgeon["actor"]["reference"] == "Practitioner/DR-SU-001"
    anes = performers[1]
    assert anes["function"]["coding"][0]["code"] == "158967008"
    assert anes["actor"]["reference"] == "Practitioner/DR-AN-001"


def test_fhir_procedure_has_recorder():
    r = _build_procedure(_proc_dict(), "PAT-001", 0, "US")
    assert r["recorder"]["reference"] == "Practitioner/DR-SU-001"


def test_fhir_procedure_has_reason_reference():
    r = _build_procedure(_proc_dict(), "PAT-001", 0, "US")
    assert r["reasonReference"][0]["reference"] == "Condition/cond-ENC-PAT-001-0001-primary"


def test_fhir_procedure_has_body_site():
    r = _build_procedure(_proc_dict(), "PAT-001", 0, "US")
    bs = r["bodySite"][0]["coding"][0]
    assert bs["code"] == "71341001"
    assert bs["display"] == "Bone structure of femur"


def test_fhir_procedure_has_location():
    r = _build_procedure(_proc_dict(), "PAT-001", 0, "US")
    assert r["location"]["reference"] == "Location/loc-or-2"


def test_fhir_procedure_has_outcome_successful():
    r = _build_procedure(_proc_dict(), "PAT-001", 0, "US")
    assert r["outcome"]["coding"][0]["code"] == "385669000"
    assert r["outcome"]["coding"][0]["display"] == "Successful"


def test_fhir_procedure_has_complication_when_present():
    r = _build_procedure(
        _proc_dict(
            outcome_code="385670004",
            complication_codes=["131148009"],
        ),
        "PAT-001",
        0,
        "US",
    )
    assert r["complication"][0]["coding"][0]["code"] == "131148009"
    assert r["complication"][0]["coding"][0]["display"] == "Bleeding"
    assert r["outcome"]["coding"][0]["code"] == "385670004"


def test_fhir_procedure_japanese_display():
    r = _build_procedure(_proc_dict(), "PAT-001", 0, "JP")
    assert r["category"]["coding"][0]["display"] == "手術"
    assert r["performer"][0]["function"]["coding"][0]["display"] == "執刀医"
    assert r["bodySite"][0]["coding"][0]["display"] == "大腿骨"


def test_fhir_procedure_omits_empty_fields():
    """Bedside procedure with no surgeon / location should not emit empty fields."""
    proc = _proc_dict(
        primary_surgeon_id="",
        anesthesiologist_id="",
        location_id="",
        body_site_code="",
    )
    r = _build_procedure(proc, "PAT-001", 0, "US")
    assert "performer" not in r
    assert "recorder" not in r
    assert "location" not in r
    assert "bodySite" not in r


# ---------------------------------------------------------------------------
# End-to-end: real record → FHIR
# ---------------------------------------------------------------------------


def test_bedside_procedure_round_trip_to_fhir(rng):
    procs = generate_bedside_procedures(
        patient_id="PAT-E2E",
        encounter_id="ENC-E2E",
        disease_id="sepsis",
        admission_time=datetime(2026, 4, 6, 10, 0),
        severity="severe",
        rng=rng,
        country="US",
    )
    assert procs
    # dataclass → dict, stringify datetimes the same way cif_writer does
    pdict = asdict(procs[0])
    pdict["start_datetime"] = procs[0].start_datetime.isoformat()
    pdict["end_datetime"] = procs[0].end_datetime.isoformat()
    r = _build_procedure(pdict, "PAT-E2E", 0, "US")
    assert "category" in r
    assert r["category"]["coding"][0]["code"] in {
        "387713003",
        "103693007",
        "277132007",
    }
    assert r["reasonReference"][0]["reference"] == "Condition/cond-ENC-E2E-primary"
