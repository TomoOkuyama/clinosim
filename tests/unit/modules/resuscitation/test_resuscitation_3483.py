"""Issue #3483: a full-code in-hospital death records the resuscitation attempt
that ends at the time of death; a not-for-resuscitation death records none."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.codes.loader import display
from clinosim.codes.procedures import procedure_code, procedure_type_display
from clinosim.modules.resuscitation.engine import load_rules
from clinosim.modules.resuscitation.enricher import enrich_resuscitation
from clinosim.types.encounter import EncounterStatus, EncounterType
from clinosim.types.patient import PatientProfile
from clinosim.types.staff import StaffMember, StaffRoster

pytestmark = pytest.mark.unit

_ADM = datetime(2025, 3, 1, 10, 0)
_DEATH = datetime(2025, 3, 4, 0, 12)
FULL_CODE, DNR = "304252001", "304253006"
ROSTER = StaffRoster(
    members=[StaffMember(staff_id="NS-IM-001", name="n", role="nurse", department="internal_medicine", ward="4E")]
)


def _record(code_status: str, *, deceased: bool = True, etype=EncounterType.INPATIENT, pid: str = "P1"):
    enc = SimpleNamespace(
        encounter_id=f"ENC-{pid}",
        encounter_type=etype,
        status=EncounterStatus.COMPLETED,
        admission_datetime=_ADM,
        discharge_datetime=_DEATH,
        attending_physician_id="DR-IM-001",
        ward_id="4E",
        department_id="internal_medicine",
    )
    return SimpleNamespace(
        patient=PatientProfile(patient_id=pid, sex="M", age=70),
        encounters=[enc],
        orders=[],
        procedures=[],
        medication_administrations=[],
        deceased=deceased,
        code_status=code_status,
    )


def _run(rec, country: str = "US") -> None:
    enrich_resuscitation(SimpleNamespace(records=[rec], roster=ROSTER, config=SimpleNamespace(country=country)))


@pytest.mark.parametrize("country", ["US", "JP"])
def test_full_code_death_records_a_cpr_ending_at_death(country: str) -> None:
    rec = _record(FULL_CODE)
    _run(rec, country)
    (cpr,) = [p for p in rec.procedures if p.procedure_type == "cpr"]
    assert cpr.end_datetime == _DEATH
    assert cpr.start_datetime == _DEATH - timedelta(minutes=cpr.duration_minutes)
    assert cpr.start_datetime >= _ADM
    assert (cpr.procedure_code_us, cpr.procedure_code_jp) == ("92950", "J046")
    assert cpr.procedure_code == ("92950" if country == "US" else "J046")
    assert cpr.primary_surgeon_id == "DR-IM-001"
    rules = load_rules()
    assert rules.duration_minutes.min <= cpr.duration_minutes <= rules.duration_minutes.max


def test_epinephrine_is_given_during_the_attempt_at_the_modelled_interval() -> None:
    rec = _record(FULL_CODE)
    _run(rec)
    cpr = rec.procedures[0]
    mars = [m for m in rec.medication_administrations if m.drug_name == "Epinephrine"]
    times = [m.actual_datetime for m in mars]
    assert mars and all(cpr.start_datetime <= t < cpr.end_datetime for t in times)
    interval = timedelta(minutes=load_rules().epinephrine.interval_minutes)
    assert all(b - a == interval for a, b in zip(times, times[1:]))
    assert {m.dose for m in mars} == {"1 mg"} and {m.route for m in mars} == {"IV"}
    assert {m.administered_by for m in mars} == {"NS-IM-001"}
    (order,) = [o for o in rec.orders if o.display_name == "Epinephrine"]
    assert {m.order_id for m in mars} == {order.order_id}
    assert order.encounter_id == "ENC-P1" and order.end_datetime == times[-1]


@pytest.mark.parametrize("status", [DNR, "", "unknown"])
def test_no_attempt_without_a_full_code_status(status: str) -> None:
    rec = _record(status)
    _run(rec)
    assert rec.procedures == [] and rec.medication_administrations == [] and rec.orders == []


def test_no_attempt_for_a_survivor_or_an_outpatient() -> None:
    survivor = _record(FULL_CODE, deceased=False)
    outpatient = _record(FULL_CODE, etype=EncounterType.OUTPATIENT)
    _run(survivor)
    _run(outpatient)
    assert survivor.procedures == [] and outpatient.procedures == []


def test_the_attempt_is_deterministic_and_added_once() -> None:
    a, b = _record(FULL_CODE), _record(FULL_CODE)
    _run(a)
    _run(b)
    _run(b)
    assert [p.duration_minutes for p in a.procedures] == [p.duration_minutes for p in b.procedures]
    assert len(b.procedures) == 1 and len(b.orders) == 1
    assert len(a.medication_administrations) == len(b.medication_administrations)


def test_duration_varies_between_patients() -> None:
    recs = [_record(FULL_CODE, pid=f"P{i}") for i in range(20)]
    for r in recs:
        _run(r)
    assert len({r.procedures[0].duration_minutes for r in recs}) > 3


def test_the_death_summary_detection_recognises_the_record() -> None:
    from clinosim.modules.document.narrative.renderers.section_builders.mortality import _recorded_cpr

    rec = _record(FULL_CODE)
    _run(rec)
    assert _recorded_cpr(SimpleNamespace(procedures=rec.procedures))


def test_the_codes_are_registered_and_named() -> None:
    assert procedure_code("cpr", "US") == "92950" and procedure_code("cpr", "JP") == "J046"
    assert display("cpt", "92950", "en") and display("k-codes", "J046", "ja") == "非開胸的心マッサージ"
    assert procedure_type_display("cpr", "ja") == "心肺蘇生" and procedure_type_display("cpr", "en")
