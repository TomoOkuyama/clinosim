"""Issue #3568: a chemotherapy visit follows the regimen's route, a cytotoxic
cycle starts with a blood count, and the note states the cycle."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim import determinism
from clinosim.locale.loader import load_chemo_regimens
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    build_outpatient_assessment,
    build_outpatient_objective,
    build_outpatient_plan,
    build_outpatient_subjective,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.population.engine import PersonRecord, _chemo_cycle_events
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.simulator.phases._healthcare_calendar import chemo_visit_spec
from clinosim.types.document import DocumentType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _spec_with_pretreatment(regimen_name: str, cycle: int = 0) -> dict:
    return chemo_visit_spec(f"chemo_regimens:{regimen_name}", cycle)


def _visit(regimen_name: str, country: str = "US", cycle: int = 0):
    return _simulate_outpatient_visit(
        patient=PatientProfile(patient_id="POP-000001", sex="M", age=68, height_cm=170.0, weight_kg=70.0),
        visit_type="chemo_visit",
        visit_date=datetime(2026, 2, 10, 10, 0),
        roster=StaffRoster(),
        rng=determinism.default_rng(42),
        chronic_code="C71",
        followup_spec=_spec_with_pretreatment(regimen_name, cycle),
        country=country,
    )


def _soap(record, country: str) -> dict[str, str]:
    from dataclasses import asdict

    rec = asdict(record)
    rec["condition_event"]["visit_type"] = "chemo_visit"
    enc = rec["encounters"][0]
    ctx = build_narrative_context(rec, enc, DocumentType.OUTPATIENT_SOAP, 0, country)
    ctx.diagnoses = [{"admission_diagnosis_code": "C71", "discharge_diagnosis_code": "C71"}]
    gen = TemplateNarrativeGenerator()
    return {
        "S": build_outpatient_subjective(gen, ctx)[0],
        "O": build_outpatient_objective(gen, ctx)[0],
        "A": build_outpatient_assessment(gen, ctx)[0],
        "P": build_outpatient_plan(gen, ctx)[0],
    }


def test_oral_regimen_has_an_oral_visit_reason_and_no_infusion_procedure() -> None:
    rec = _visit("Temozolomide_stupp")
    assert rec.procedures == []
    assert rec.medication_administrations == []
    assert [o.display_name for o in rec.orders if o.order_type.name == "MEDICATION"] == ["Temozolomide"]
    assert "infusion" not in (rec.encounters[0].chief_complaint or "").lower()
    assert "oral" in (rec.encounters[0].chief_complaint or "").lower()


@pytest.mark.parametrize(
    "regimen, code_us, code_jp",
    [
        ("LHRH_q28d", "96402", "G000"),
        ("BCG_intravesical", "51720", "G003-2"),
        ("FOLFOX", "96413", "G004"),
    ],
)
def test_procedure_code_follows_the_route(regimen: str, code_us: str, code_jp: str) -> None:
    [proc] = _visit(regimen).procedures
    assert (proc.procedure_code_us, proc.procedure_code_jp) == (code_us, code_jp)


def test_only_iv_regimens_use_the_infusion_code() -> None:
    for name, regimen in load_chemo_regimens()["regimens"].items():
        proc = _visit(name).procedures
        infusion = [p for p in proc if p.procedure_code_us == "96413"]
        assert bool(infusion) == (regimen["administration"] == "iv"), name


def test_cytotoxic_regimens_order_a_cbc_and_others_do_not() -> None:
    data = load_chemo_regimens()["regimens"]
    assert {n for n, r in data.items() if r.get("pretreatment_labs")} == {
        "FOLFOX",
        "CarboPem",
        "GemNabP",
        "Temozolomide_stupp",
    }
    assert any(lab.lab_name == "WBC" for lab in _visit("FOLFOX").lab_results)
    assert _visit("LHRH_q28d").lab_results == []


def test_note_states_cycle_and_pretreatment_labs_and_no_prior_cycle_on_cycle_one() -> None:
    first = _soap(_visit("FOLFOX", cycle=1), "US")
    assert "Cycle 1 of 12" in first["S"]
    assert "since the last cycle" not in first["S"]
    assert "Pre-treatment labs:" in first["O"]
    third = _soap(_visit("FOLFOX", cycle=3), "US")
    assert "Cycle 3 of 12" in third["S"] and "since the last cycle" in third["S"]


def test_oral_note_says_prescribed_not_given_in_clinic() -> None:
    soap = _soap(_visit("Temozolomide_stupp", cycle=2), "US")
    text = "\n".join(soap.values())
    assert "Temozolomide" in soap["A"] and "prescribed today" in soap["A"]
    assert "given today" not in text and "administered" not in text


def test_note_wording_follows_the_route_jp() -> None:
    oral = _soap(_visit("Temozolomide_stupp", "JP", 2), "JP")
    assert "処方" in oral["A"] and "施行" not in oral["A"] and "第2コース" in oral["S"]
    bcg = _soap(_visit("BCG_intravesical", "JP", 1), "JP")
    assert "膀胱内に注入" in bcg["A"] and "点滴" not in "\n".join(bcg.values())


def test_scheduler_numbers_the_cycles_from_one() -> None:
    for i in range(200):
        person = PersonRecord(
            person_id=f"POP-C25-{i:04d}",
            household_id="HH-000001",
            age=60,
            sex="F",
            date_of_birth=date(1966, 1, 1),
            chronic_conditions=["C25"],
        )
        events = _chemo_cycle_events(person, year=2024)
        if events:
            assert [e.chemo_cycle for e in events] == list(range(1, len(events) + 1))
            return
    raise AssertionError("no GemNabP assignment in 200 sweeps")


def test_pretreatment_cbc_is_resulted_before_the_drugs_are_given() -> None:
    rec = _visit("FOLFOX", cycle=2)
    [enc] = rec.encounters
    results = [lab.result_datetime for lab in rec.lab_results]
    assert results
    dosing = [m.actual_datetime for m in rec.medication_administrations]
    assert dosing and max(results) < min(dosing)
    assert all(p.start_datetime > max(results) for p in rec.procedures)
    assert enc.discharge_datetime >= max(p.end_datetime for p in rec.procedures)


def test_oncology_visit_note_is_authored_at_the_end_of_the_visit() -> None:
    from types import SimpleNamespace

    from clinosim.modules.document.engine import _plan_encounter_once
    from clinosim.modules.document.narrative.registry import load_document_type_specs

    rec = _visit("FOLFOX", cycle=2)
    [enc] = rec.encounters
    enc.service_line = "oncology"
    spec = load_document_type_specs()[DocumentType.OUTPATIENT_SOAP]
    facts = SimpleNamespace(admission_dt=enc.admission_datetime, end_dt=enc.discharge_datetime, encounter=enc)
    [plan] = _plan_encounter_once(spec, facts)  # type: ignore[arg-type]
    assert plan.authored == enc.discharge_datetime.isoformat()
    enc.service_line = ""
    [plan] = _plan_encounter_once(spec, facts)  # type: ignore[arg-type]
    # Issue #3650: every outpatient visit note is authored at the visit end now
    assert plan.authored == enc.discharge_datetime.isoformat()
