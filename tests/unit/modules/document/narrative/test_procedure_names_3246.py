"""Procedures are named in the narrative from the CIF record (Issue #3246).

CIF ``ProcedureRecord`` stores codes only (``procedure_type`` plus
``procedure_code`` / ``procedure_code_jp`` / ``procedure_code_us``, AD-30);
it has no ``procedure_name`` / ``name`` key. The discharge-summary hospital
course, the progress-note plan, the H&P plan and the death-summary
circumstances read those missing keys, so no procedure was ever named. They
now name it through ``procedure_prose_name`` (the procedure catalog's
clinical name, else the code display of ``resolve_procedure_display``), and
the daily notes list only that day's procedures.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers._shared_helpers import (
    procedure_prose_name,
    resolve_procedure_display,
)
from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import build_hospital_course
from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
    build_dds_circumstances_of_death,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

_ADMIT = datetime(2026, 9, 1, 10, 0)


def _proc(ptype: str, us: str, jp: str, start: str, *, lang: str) -> dict:
    return {
        "procedure_type": ptype,
        "procedure_code": jp if lang == "ja" else us,
        "procedure_code_jp": jp,
        "procedure_code_us": us,
        "start_datetime": start,
    }


def _ctx(lang: str, procedures: list[dict], *, day_index: int = 0, doc=DocumentType.DISCHARGE_SUMMARY):
    p = PatientProfile(patient_id="pt-3246")
    p.age = 80
    p.sex = "F"
    enc = SimpleNamespace(
        encounter_id="enc-3246",
        admission_datetime=_ADMIT,
        encounter_type=SimpleNamespace(value="inpatient"),
        primary_diagnosis="Hip fracture",
    )
    return NarrativeContext(
        patient=p,
        encounter=enc,
        encounter_type=enc.encounter_type,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=day_index,
        los_days=14,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=procedures,
        allergies=[],
        document_type=doc,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


def _hip_procs(lang: str) -> list[dict]:
    return [
        _proc("urinary_catheter", "51702", "J063", "2026-09-01T12:00:00", lang=lang),
        _proc("ORIF", "27236", "K0463", "2026-09-02T09:00:00", lang=lang),
    ]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_hospital_course_names_the_operation(lang: str) -> None:
    procs = _hip_procs(lang)
    text, facts = build_hospital_course(TemplateNarrativeGenerator(), _ctx(lang, procs))
    assert procedure_prose_name(procs[1], lang) in text
    assert procedure_prose_name(procs[0], lang) in text
    assert "ctx.procedures" in facts


def test_hospital_course_lists_a_repeated_procedure_once() -> None:
    procs = _hip_procs("en") + [_proc("urinary_catheter", "51702", "J063", "2026-09-05T12:00:00", lang="en")]
    text, _ = build_hospital_course(TemplateNarrativeGenerator(), _ctx("en", procs))
    assert text.count(procedure_prose_name(procs[0], "en")) == 1


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_progress_plan_lists_only_todays_procedures(lang: str) -> None:
    procs = _hip_procs(lang)
    gen = TemplateNarrativeGenerator()
    day1 = gen._compose_progress_plan_from_state(_ctx(lang, procs, day_index=1, doc=DocumentType.PROGRESS_NOTE))
    assert procedure_prose_name(procs[1], lang) in day1
    assert procedure_prose_name(procs[0], lang) not in day1
    day3 = gen._compose_progress_plan_from_state(_ctx(lang, procs, day_index=3, doc=DocumentType.PROGRESS_NOTE))
    assert procedure_prose_name(procs[1], lang) not in day3


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_admission_plan_lists_admission_day_procedures(lang: str) -> None:
    procs = _hip_procs(lang)
    plan = TemplateNarrativeGenerator()._compose_ap_plan_from_state(_ctx(lang, procs, doc=DocumentType.ADMISSION_HP))
    assert procedure_prose_name(procs[0], lang) in plan
    # The operation on hospital day 1 is not yet done when the H&P is written.
    assert procedure_prose_name(procs[1], lang) not in plan


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_uncoded_display_is_named_from_the_catalog_not_the_slug(lang: str) -> None:
    proc = {"procedure_type": "hearing_screen_aabr", "procedure_code": "413083006"}
    name = resolve_procedure_display(proc, lang)
    assert "_" not in name
    assert name


def test_death_summary_detects_cpr_from_the_procedure_code() -> None:
    procs = [{"procedure_type": "cpr", "procedure_code": "92950", "procedure_code_us": "92950"}]
    gen = TemplateNarrativeGenerator()
    text, _ = build_dds_circumstances_of_death(gen, _ctx("en", procs, doc=DocumentType.DEATH_DISCHARGE_SUMMARY))
    assert "resuscitation was performed" in text
    # Intubation (K-code display "... for resuscitation") is not CPR.
    intub = [_proc("intubation", "31500", "J044", "2026-09-02T09:00:00", lang="ja")]
    text, _ = build_dds_circumstances_of_death(gen, _ctx("en", intub, doc=DocumentType.DEATH_DISCHARGE_SUMMARY))
    assert "resuscitation was performed" not in text


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("en", "Open reduction and internal fixation (ORIF)"), ("ja", "観血的整復固定術")],
)
def test_prose_name_is_the_catalog_name(lang: str, expected: str) -> None:
    assert procedure_prose_name(_hip_procs(lang)[1], lang) == expected


def test_prose_name_of_an_uncatalogued_type_is_its_code_display() -> None:
    proc = {"procedure_type": "CT of chest", "procedure_code": "", "procedure_code_us": "71250"}
    assert procedure_prose_name(proc, "ja") == resolve_procedure_display(proc, "ja") == "胸部CT（造影なし）"
