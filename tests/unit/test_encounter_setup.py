"""The shared encounter build / finish steps (Issue #2522)."""

from __future__ import annotations

from datetime import datetime

from clinosim.codes.hl7_encounter import ActPriority, AdmitSource, DischargeDisposition
from clinosim.simulator.encounter_setup import attach_orders, encounter_diagnosis, finalize_encounter
from clinosim.types.encounter import Encounter, Order


def test_attach_orders_fills_only_orders_without_an_encounter() -> None:
    enc = Encounter(encounter_id="ENC-1")
    loose, owned = Order(order_id="O-1"), Order(order_id="O-2", encounter_id="ENC-0")
    attach_orders([loose, owned], enc)
    assert (loose.encounter_id, owned.encounter_id) == ("ENC-1", "ENC-0")


def test_finalize_encounter_sets_route_and_lets_the_attending_admit_and_discharge() -> None:
    enc = Encounter(encounter_id="ENC-1", admission_datetime=datetime(2026, 1, 1), attending_physician_id="DR-7")
    finalize_encounter(
        enc, admit_source=AdmitSource.BORN, disposition=DischargeDisposition.HOME, priority=ActPriority.R
    )
    assert (enc.admit_source, enc.discharge_disposition, enc.priority) == ("born", "home", "R")
    assert enc.admitting_physician_id == enc.discharging_physician_id == "DR-7"


def test_encounter_diagnosis_uses_the_country_code_system() -> None:
    us, jp = encounter_diagnosis("J18.9", "US"), encounter_diagnosis("J18.9", "JP")
    assert (us.admission_diagnosis_system, us.discharge_diagnosis_system) == ("icd-10-cm", "icd-10-cm")
    assert (jp.admission_diagnosis_system, jp.discharge_diagnosis_system) == ("icd-10-mhlw", "icd-10-mhlw")
    assert us.admission_diagnosis_code == us.discharge_diagnosis_code == "J18.9"


def test_encounter_diagnosis_takes_a_separate_discharge_code_and_extra_fields() -> None:
    dx = encounter_diagnosis("O80", "US", discharge_code="Z37.0", diagnosis_correct=False)
    assert (dx.admission_diagnosis_code, dx.discharge_diagnosis_code, dx.diagnosis_correct) == ("O80", "Z37.0", False)
