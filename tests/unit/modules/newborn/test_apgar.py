"""Unit tests for newborn Apgar-score CIF emission + FHIR bundle-builder
(#1252 N4).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.newborn import build_apgar_scores, enrich_newborn
from clinosim.modules.newborn.fhir_emit import _bb_newborn_apgar
from clinosim.types.clinical import ConditionEvent
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _newborn_record(patient_id: str = "POP-000001-BABY") -> CIFPatientRecord:
    admit = datetime(2026, 6, 1, 10, 0)
    enc = Encounter(
        encounter_id=f"ENC-{patient_id}-01",
        patient_id=patient_id,
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=admit + timedelta(days=5),
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


def _adult_record() -> CIFPatientRecord:
    admit = datetime(2026, 6, 1, 10, 0)
    enc = Encounter(
        encounter_id="ENC-A-1",
        admission_datetime=admit,
        discharge_datetime=admit + timedelta(days=2),
    )
    return CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-A", sex="F", age=45),
        encounters=[enc],
        condition_event=ConditionEvent(condition_type="pneumonia_acute"),
    )


class _Cfg:
    def __init__(self, country: str) -> None:
        self.country = country


class _Ctx:
    def __init__(self, records: list, country: str = "JP") -> None:
        self.records = records
        self.config = _Cfg(country)


def test_apgar_returns_two_scores_at_1_and_5_min() -> None:
    scores = build_apgar_scores(_newborn_record())
    assert len(scores) == 2
    assert scores[0]["minute"] == 1
    assert scores[1]["minute"] == 5
    # Realistic range for a healthy Z38.0 term newborn.
    assert 0 <= scores[0]["score"] <= 10
    assert 0 <= scores[1]["score"] <= 10


def test_apgar_deterministic_same_pid() -> None:
    a = build_apgar_scores(_newborn_record("POP-000042-BABY"))
    b = build_apgar_scores(_newborn_record("POP-000042-BABY"))
    assert [(x["minute"], x["score"]) for x in a] == [(x["minute"], x["score"]) for x in b]


def test_apgar_no_op_on_adult() -> None:
    assert build_apgar_scores(_adult_record()) == []


def test_apgar_5min_median_above_1min_across_a_cohort() -> None:
    """Real neonatal cohorts show 5-min Apgar > 1-min Apgar on average
    (the newborn transitions from the birth stress state). The
    weighted distribution in `newborn_screening.yaml` enforces this.
    """
    m1_total = 0
    m5_total = 0
    n = 100
    for i in range(n):
        pid = f"POP-{i:05d}-BABY"
        scores = build_apgar_scores(_newborn_record(pid))
        m1_total += scores[0]["score"]
        m5_total += scores[1]["score"]
    m1_mean = m1_total / n
    m5_mean = m5_total / n
    assert m5_mean > m1_mean, f"expected 5-min mean {m5_mean:.2f} > 1-min mean {m1_mean:.2f}"


def test_enricher_writes_apgar_to_extensions() -> None:
    rec = _newborn_record()
    ctx = _Ctx(records=[rec], country="JP")
    enrich_newborn(ctx)
    apgar = rec.extensions.get("newborn", {}).get("apgar", [])
    assert len(apgar) == 2
    assert {a["minute"] for a in apgar} == {1, 5}


def test_fhir_emit_renders_two_apgar_observations() -> None:
    """The `_bb_newborn_apgar` bundle-builder reads
    `extensions["newborn"]["apgar"]` and renders one Observation per
    minute with the correct LOINC (9271-8 / 9274-2), UCUM-`{score}`
    valueQuantity, and survey category.
    """
    rec = _newborn_record()
    ctx = _Ctx(records=[rec], country="JP")
    enrich_newborn(ctx)

    class _BundleCtx:
        def __init__(self, record: CIFPatientRecord) -> None:
            self.record = {
                "extensions": dict(record.extensions),
                "encounters": record.encounters,
            }
            self.patient_id = record.patient.patient_id
            self.primary_enc_id = record.encounters[0].encounter_id
            self.country = "jp"

    obs_list = _bb_newborn_apgar(_BundleCtx(rec))
    assert len(obs_list) == 2
    loincs = sorted(
        c.get("code") for o in obs_list for c in (o.get("code", {}).get("coding", []) or []) if c.get("code")
    )
    assert loincs == ["9271-8", "9274-2"]
    # Values are integer scores 0-10 with UCUM {score} unit.
    for o in obs_list:
        vq = o.get("valueQuantity", {})
        assert 0 <= vq.get("value", -1) <= 10
        assert vq.get("code") == "{score}"
        cat_codes = [c.get("code") for cat in o.get("category", []) for c in cat.get("coding", [])]
        assert "survey" in cat_codes
