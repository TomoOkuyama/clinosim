"""Unit tests for newborn bilirubin / CCHD pulse-ox / ophthalmic
prophylaxis events (#1252 N7).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.newborn import (
    build_bilirubin_observations,
    build_cchd_pulse_ox,
    build_ophthalmic_prophylaxis,
    enrich_newborn,
)
from clinosim.modules.newborn.fhir_emit import (
    _bb_newborn_bilirubin,
    _bb_newborn_cchd_pulse_ox,
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


def _adult_record() -> CIFPatientRecord:
    return CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-A", sex="F", age=45),
        encounters=[
            Encounter(
                admission_datetime=datetime(2026, 6, 1, 10, 0),
                discharge_datetime=datetime(2026, 6, 3, 10, 0),
            )
        ],
        condition_event=ConditionEvent(condition_type="pneumonia_acute"),
    )


class _Cfg:
    def __init__(self, country: str) -> None:
        self.country = country


class _Ctx:
    def __init__(self, records: list, country: str = "JP") -> None:
        self.records = records
        self.config = _Cfg(country)


# ---------------------------------------------------------------------------
# Bilirubin daily readings
# ---------------------------------------------------------------------------


def test_bilirubin_emits_three_readings_for_a_5day_los() -> None:
    entries = build_bilirubin_observations(_newborn_record())
    assert len(entries) == 3
    assert [e["day"] for e in entries] == [1, 2, 3]
    for e in entries:
        assert 2.0 <= e["value_mg_dl"] <= 20.0
        assert e["loinc"] == "58941-6"


def test_bilirubin_day3_median_higher_than_day1() -> None:
    """Physiological jaundice peaks day 3-5; the yaml distribution
    must reflect this. Sweep 100 babies and check cohort medians."""
    d1 = []
    d3 = []
    for i in range(100):
        entries = build_bilirubin_observations(_newborn_record(f"POP-{i:05d}-BABY"))
        by_day = {e["day"]: e["value_mg_dl"] for e in entries}
        d1.append(by_day[1])
        d3.append(by_day[3])
    assert sum(d3) / 100 > sum(d1) / 100


def test_bilirubin_skipped_past_discharge() -> None:
    """A 2-day US LOS captures day 1 only; days 2/3 fall past discharge."""
    entries = build_bilirubin_observations(_newborn_record(los_days=1))
    assert len(entries) <= 1


def test_bilirubin_noop_on_adult() -> None:
    assert build_bilirubin_observations(_adult_record()) == []


# ---------------------------------------------------------------------------
# CCHD pulse-oximetry screen
# ---------------------------------------------------------------------------


def test_cchd_emits_right_hand_and_foot_readings() -> None:
    entries = build_cchd_pulse_ox(_newborn_record())
    assert len(entries) == 2
    sites = {e["site"] for e in entries}
    assert sites == {"right_hand", "foot"}
    for e in entries:
        assert 90 <= e["value_pct"] <= 100
        assert e["loinc"] == "59408-5"


def test_cchd_skipped_when_los_shorter_than_24h() -> None:
    admit = datetime(2026, 6, 1, 10, 0)
    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-Q-BABY", sex="M", age=0),
        encounters=[Encounter(admission_datetime=admit, discharge_datetime=admit + timedelta(hours=12))],
        condition_event=ConditionEvent(condition_type="newborn_birth"),
    )
    assert build_cchd_pulse_ox(rec) == []


def test_cchd_noop_on_adult() -> None:
    assert build_cchd_pulse_ox(_adult_record()) == []


# ---------------------------------------------------------------------------
# US ophthalmic prophylaxis
# ---------------------------------------------------------------------------


def test_ophthalmic_prophylaxis_us_emits_one_mar() -> None:
    mars = build_ophthalmic_prophylaxis(_newborn_record(), country="US")
    assert len(mars) == 1
    assert mars[0].route == "OPH"
    assert "Erythromycin" in mars[0].drug_name


def test_ophthalmic_prophylaxis_jp_is_noop() -> None:
    """JP does not routinely apply ophthalmic prophylaxis (declining
    gonorrhea rates + higher antibiotic-stewardship threshold)."""
    assert build_ophthalmic_prophylaxis(_newborn_record(), country="JP") == []


# ---------------------------------------------------------------------------
# End-to-end enricher wiring
# ---------------------------------------------------------------------------


def test_enricher_wires_all_n7_events_to_newborn() -> None:
    baby = _newborn_record()
    adult = _adult_record()
    ctx = _Ctx(records=[baby, adult], country="US")  # US → ophthalmic fires
    enrich_newborn(ctx)
    nb_ext = baby.extensions.get("newborn", {})
    assert len(nb_ext.get("bilirubin", [])) == 3
    assert len(nb_ext.get("cchd_pulse_ox", [])) == 2
    # US locale — ophthalmic MAR present in addition to Vitamin K.
    oph = [m for m in baby.medication_administrations if m.route == "OPH"]
    assert len(oph) == 1
    # Adult record untouched.
    assert adult.medication_administrations == []
    assert not adult.extensions.get("newborn")


# ---------------------------------------------------------------------------
# FHIR bundle-builders
# ---------------------------------------------------------------------------


def test_bilirubin_bundle_builder_renders_three_observations() -> None:
    rec = _newborn_record()
    enrich_newborn(_Ctx(records=[rec], country="JP"))

    class _BundleCtx:
        def __init__(self) -> None:
            self.record = {"extensions": dict(rec.extensions), "encounters": rec.encounters}
            self.patient_id = rec.patient.patient_id
            self.primary_enc_id = rec.encounters[0].encounter_id
            self.country = "jp"

    obs_list = _bb_newborn_bilirubin(_BundleCtx())
    assert len(obs_list) == 3
    for o in obs_list:
        loincs = [c.get("code") for c in o.get("code", {}).get("coding", [])]
        assert "58941-6" in loincs
        vq = o.get("valueQuantity", {})
        assert vq.get("code") == "mg/dL"
        # Category must NOT be "laboratory" — TcB is bedside, not a
        # sent-away lab; keep out of the JP-CLINS lab profile scope.
        cat_codes = [c.get("code") for cat in o.get("category", []) for c in cat.get("coding", [])]
        assert "laboratory" not in cat_codes
        assert "exam" in cat_codes


def test_cchd_bundle_builder_renders_two_observations_with_bodysite() -> None:
    rec = _newborn_record()
    enrich_newborn(_Ctx(records=[rec], country="US"))

    class _BundleCtx:
        def __init__(self) -> None:
            self.record = {"extensions": dict(rec.extensions), "encounters": rec.encounters}
            self.patient_id = rec.patient.patient_id
            self.primary_enc_id = rec.encounters[0].encounter_id
            self.country = "us"

    obs_list = _bb_newborn_cchd_pulse_ox(_BundleCtx())
    assert len(obs_list) == 2
    body_sites = {c.get("code") for o in obs_list for c in o.get("bodySite", {}).get("coding", [])}
    # SNOMED right upper arm 368208006 / foot 22335008
    assert body_sites == {"368208006", "22335008"}
    for o in obs_list:
        loincs = [c.get("code") for c in o.get("code", {}).get("coding", [])]
        assert "59408-5" in loincs
