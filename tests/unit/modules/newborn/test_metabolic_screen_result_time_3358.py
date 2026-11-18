"""The newborn metabolic screen is resulted days after the heel-stick (Issue #3358)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim import determinism
from clinosim.modules.newborn import enrich_newborn
from clinosim.modules.newborn.engine import build_metabolic_screen_workflow_data, load_newborn_config
from clinosim.modules.newborn.fhir_emit import (
    _bb_newborn_metabolic_screen_diagnostic_report,
    _bb_newborn_metabolic_screen_observation,
)
from clinosim.seeding import text_seed
from clinosim.types.clinical import ConditionEvent
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _record(pid: str, los_days: int = 5) -> CIFPatientRecord:
    admit = datetime(2026, 6, 1, 10, 0)
    enc = Encounter(
        encounter_id=f"ENC-{pid}-01",
        patient_id=pid,
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=admit + timedelta(days=los_days),
    )
    return CIFPatientRecord(
        patient=PatientProfile(patient_id=pid, sex="M", age=0),
        encounters=[enc],
        condition_event=ConditionEvent(
            condition_id=f"COND-{pid}-BIRTH", condition_type="newborn_birth", ground_truth_diseases=["Z38.0"]
        ),
    )


def _ext(pid: str, country: str) -> tuple[CIFPatientRecord, dict]:
    rec = _record(pid)
    enrich_newborn(SimpleNamespace(records=[rec], config=SimpleNamespace(country=country)))
    return rec, rec.extensions["newborn"]["metabolic_screen"]


def _ctx(rec: CIFPatientRecord, country: str) -> SimpleNamespace:
    return SimpleNamespace(
        record=rec,
        patient_id=rec.patient.patient_id,
        country=country.lower(),
        primary_enc_id=rec.encounters[0].encounter_id,
    )


@pytest.mark.parametrize("country,low,high", [("US", 2, 7), ("JP", 7, 14)])
def test_result_time_is_days_after_collection(country: str, low: int, high: int) -> None:
    for i in range(40):
        _, ext = _ext(f"POP-{i:06d}-BABY", country)
        gap = ext["result_datetime"] - ext["collected_datetime"]
        assert timedelta(days=low - 1) <= gap <= timedelta(days=high + 1), (country, gap)


def test_result_time_does_not_touch_the_outcome_stream() -> None:
    cfg_before = dict(load_newborn_config()["metabolic_screen"])
    rec = _record("POP-000007-BABY")
    ext = build_metabolic_screen_workflow_data(rec, "US")
    assert ext is not None
    # The outcome is drawn from the pre-existing stream and is unchanged by the new draw.
    rng = determinism.default_rng(text_seed("newborn-metabolic-screen|POP-000007-BABY"))
    w = cfg_before["result_weights"]
    keys = list(w)
    probs = [w[k] / sum(w.values()) for k in keys]
    assert ext["outcome_key"] == keys[int(rng.choice(len(keys), p=probs))]


def test_fhir_issued_equals_cif_result_time_for_panel_and_observation() -> None:
    rec, ext = _ext("POP-000003-BABY", "US")
    dr = _bb_newborn_metabolic_screen_diagnostic_report(_ctx(rec, "US"))[0]
    obs = _bb_newborn_metabolic_screen_observation(_ctx(rec, "US"))[0]
    assert dr["issued"] == ext["result_datetime"].isoformat() == obs["issued"]
    assert dr["effectiveDateTime"] == ext["collected_datetime"].isoformat()
    assert datetime.fromisoformat(dr["issued"]) - datetime.fromisoformat(dr["effectiveDateTime"]) >= timedelta(hours=24)


def test_fhir_issued_after_json_round_trip() -> None:
    rec, ext = _ext("POP-000004-BABY", "JP")
    ext["collected_datetime"] = ext["collected_datetime"].isoformat()
    ext["result_datetime"] = ext["result_datetime"].isoformat()
    dr = _bb_newborn_metabolic_screen_diagnostic_report(_ctx(rec, "JP"))[0]
    assert dr["issued"] == ext["result_datetime"]
