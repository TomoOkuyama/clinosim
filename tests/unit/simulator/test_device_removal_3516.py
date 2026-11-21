"""A catheter is placed by its placing event and removed when its indication
ends (Issue #3516)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim.modules.device.engine import load_devices_config, place_devices_for_encounter
from clinosim.simulator.device_removal import device_removal_rules, removal_date
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Encounter, EncounterType, Order
from clinosim.types.output import CIFPatientRecord
from clinosim.types.procedure import ProcedureRecord

pytestmark = pytest.mark.unit

_ADMIT = datetime(2026, 3, 1, 10, 0)
_STABLE = PhysiologicalState()
_SHOCK = PhysiologicalState(perfusion_status=0.2)


def _enc(days: int = 10) -> Encounter:
    return Encounter(
        encounter_id="enc1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=_ADMIT,
        discharge_datetime=datetime(2026, 3, 1 + days, 10, 0),
    )


def _record(states: list[PhysiologicalState], **kw) -> CIFPatientRecord:
    rec = CIFPatientRecord()
    rec.physiological_states = states
    for k, v in kw.items():
        setattr(rec, k, v)
    return rec


def _insertion(proc_type: str, when: datetime) -> ProcedureRecord:
    return ProcedureRecord(procedure_id="p", encounter_id="enc1", procedure_type=proc_type, start_datetime=when)


def _surgery(when: datetime) -> ProcedureRecord:
    return ProcedureRecord(
        procedure_id="s",
        encounter_id="enc1",
        procedure_type="orif",
        start_datetime=when,
        category_code="387713003",
    )


def _removal(rule_key: str, states, placed=date(2026, 3, 1), operations=(), discharged=date(2026, 3, 11)):
    return removal_date(
        device_removal_rules().kinds[rule_key],
        placed=placed,
        admitted=date(2026, 3, 1),
        discharged=discharged,
        states=states,
        operations=list(operations),
    )


def test_rules_cover_the_catheters_and_cite_a_source() -> None:
    kinds = device_removal_rules().kinds
    assert {"indwelling_catheter", "cvc"} <= set(kinds)
    assert kinds["mechanical_ventilator"].indications == {}


def test_strict_io_catheter_removed_after_minimum_dwell_when_stable() -> None:
    assert _removal("indwelling_catheter", [_STABLE] * 11) == (date(2026, 3, 3), "strict_io_monitoring")


def test_catheter_stays_while_the_patient_needs_icu_care() -> None:
    states = [_SHOCK] * 5 + [_STABLE] * 6
    assert _removal("indwelling_catheter", states) == (date(2026, 3, 6), "strict_io_monitoring")


def test_catheter_without_a_stable_day_is_removed_at_discharge() -> None:
    assert _removal("indwelling_catheter", [_SHOCK] * 11) == (date(2026, 3, 11), "strict_io_monitoring")


def test_postoperative_catheter_removed_the_day_after_surgery() -> None:
    got = _removal("indwelling_catheter", [_STABLE] * 11, operations=[date(2026, 3, 2)])
    assert got == (date(2026, 3, 3), "perioperative")


def test_open_stay_keeps_its_device_open() -> None:
    got = removal_date(
        device_removal_rules().kinds["cvc"],
        placed=date(2026, 3, 1),
        admitted=date(2026, 3, 1),
        discharged=None,
        states=[_STABLE] * 9,
        operations=[],
    )
    assert got == (None, "hemodynamic_monitoring")


def test_ward_catheter_from_an_insertion_procedure_gets_a_removal() -> None:
    rec = _record([_STABLE] * 11, procedures=[_insertion("urinary_catheter", datetime(2026, 3, 1, 14, 0))])
    out = place_devices_for_encounter(rec, _enc(), load_devices_config())
    assert [(d.device_type, d.origin) for d in out] == [("indwelling_catheter", "insertion")]
    assert (out[0].placement_date, out[0].removal_date) == ("2026-03-01", "2026-03-03")


def test_ward_catheter_from_an_order_is_placed_on_the_order_day() -> None:
    order = Order(
        order_id="o1",
        encounter_id="enc1",
        display_name="foley_catheter: Strict I/O monitoring",
        ordered_datetime=datetime(2026, 3, 2, 9, 0),
    )
    rec = _record([_STABLE] * 11, orders=[order])
    out = place_devices_for_encounter(rec, _enc(), load_devices_config())
    assert [(d.placement_date, d.removal_date) for d in out] == [("2026-03-02", "2026-03-04")]


def test_stay_without_a_catheter_event_gets_no_device() -> None:
    assert place_devices_for_encounter(_record([_STABLE] * 11), _enc(), load_devices_config()) == []


def test_icu_device_is_placed_on_the_icu_transfer_day() -> None:
    rec = _record([_STABLE] * 11, icu_transferred=True, icu_transferred_day=3)
    out = {d.device_type: d for d in place_devices_for_encounter(rec, _enc(), load_devices_config())}
    assert out["indwelling_catheter"].placement_date == "2026-03-04"
    assert out["indwelling_catheter"].removal_date == "2026-03-06"
    assert out["cvc"].origin == "icu_stay"


def test_icu_device_follows_the_insertion_procedure_when_there_is_one() -> None:
    rec = _record(
        [_STABLE] * 11,
        icu_transferred=True,
        icu_transferred_day=3,
        procedures=[_insertion("central_line", datetime(2026, 3, 2, 8, 0))],
    )
    out = {d.device_type: d for d in place_devices_for_encounter(rec, _enc(), load_devices_config())}
    assert out["cvc"].placement_date == "2026-03-02"
    assert out["indwelling_catheter"].placement_date == "2026-03-04"


def test_a_ventilator_stays_until_discharge() -> None:
    rec = _record(
        [_STABLE] * 11,
        icu_transferred=True,
        icu_transferred_day=0,
        procedures=[_insertion("intubation", datetime(2026, 3, 2, 8, 0))],
    )
    out = {d.device_type: d for d in place_devices_for_encounter(rec, _enc(), load_devices_config())}
    assert (out["mechanical_ventilator"].placement_date, out["mechanical_ventilator"].removal_date) == (
        "2026-03-02",
        "2026-03-11",
    )


def test_postoperative_icu_stay_catheter_follows_the_operation() -> None:
    rec = _record(
        [_STABLE] * 11,
        icu_transferred=True,
        icu_transferred_day=1,
        procedures=[_surgery(datetime(2026, 3, 4, 9, 0))],
    )
    out = {d.device_type: d for d in place_devices_for_encounter(rec, _enc(), load_devices_config())}
    assert out["indwelling_catheter"].removal_date == "2026-03-05"
    assert out["indwelling_catheter"].removal_indication == "perioperative"


def test_fhir_device_and_use_statement_carry_the_removal() -> None:
    from clinosim.modules.output.fhir_r4.lib.context import BundleContext
    from clinosim.modules.output.fhir_r4.procedures.device import _bb_device, _bb_device_use

    rec = _record([_STABLE] * 11, procedures=[_insertion("urinary_catheter", datetime(2026, 3, 1, 14, 0))])
    device = place_devices_for_encounter(rec, _enc(), load_devices_config())[0]
    ctx = BundleContext(
        record={"patient_id": "P1", "extensions": {"device": [device]}},
        country="US",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="P1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="",
        patient_sex="M",
    )
    assert _bb_device(ctx)[0]["status"] == "inactive"
    use = _bb_device_use(ctx)[0]
    assert use["status"] == "completed"
    assert use["timingPeriod"] == {"start": "2026-03-01", "end": "2026-03-03"}
