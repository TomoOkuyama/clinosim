"""Issue #3248: problem lists show every chronic condition, the encounter's
own problem first, numbered consecutively; chronic SOAP template text has no
line break inside a sentence.

Before the fix the outpatient subjective listed the first three chronic
conditions in stored order, the admission H&P comorbidities and the nursing
PMH the first four, so a cardiology visit for atrial fibrillation named
obesity, nicotine and alcohol dependence and omitted AF; the outpatient
Assessment left staged problems unnumbered (1., text, 3.).
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers._shared_helpers import (
    chronic_condition_label,
    ordered_chronic_conditions,
)
from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import (
    _compose_ap_assessment_from_state,
)
from clinosim.modules.document.narrative.renderers.section_builders.hpi import _hpi_parts
from clinosim.modules.document.narrative.renderers.section_builders.nursing import build_nursing_history
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    _compose_chronic_assessment_integrated,
    build_outpatient_subjective,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import load_document_data_yaml
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

# Patient POP-006603's chronic list (stored order) with the AF visit.
_CODES = ["E66.9", "F17.210", "F10.20", "D55.0", "I48", "I50", "I10"]


def _ctx(lang: str, conditions: list, *, visit_dx: str = "", vitals: list | None = None, document_type=None):
    patient = SimpleNamespace(
        chronic_conditions=conditions, current_medications=[], age=74, sex="M", date_of_birth=None
    )
    diagnoses = (
        [{"admission_diagnosis_code": visit_dx, "discharge_diagnosis_code": visit_dx, "working_diagnoses": []}]
        if visit_dx
        else []
    )
    return SimpleNamespace(
        patient=patient,
        encounter=SimpleNamespace(chief_complaint="", primary_nurse_id=""),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=0,
        los_days=0,
        vitals=vitals or [],
        lab_results=[],
        medications=[],
        diagnoses=diagnoses,
        procedures=[],
        allergies=[],
        document_type=document_type or DocumentType.OUTPATIENT_SOAP,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        materialized_facts=[],
        section_facts={},
        shift="",
        discharge_medications=[],
        working_diagnoses=[],
        roster_map={},
        authored_datetime=None,
    )


def _conds(codes: list[str]) -> list:
    return [SimpleNamespace(code=c, stage="") for c in codes]


def _labels(lang: str) -> list[str]:
    country = "JP" if lang == "ja" else "US"
    return [chronic_condition_label(c, country, lang, "M") or c for c in _CODES]


def test_encounter_problem_is_ordered_first_and_nothing_dropped() -> None:
    ctx = _ctx("en", _conds(_CODES), visit_dx="I48.91")
    ordered = [c.code for c in ordered_chronic_conditions(ctx)]
    assert ordered == ["I48", "E66.9", "F17.210", "F10.20", "D55.0", "I50", "I10"]


def test_no_visit_dx_keeps_stored_order() -> None:
    ctx = _ctx("en", _conds(_CODES))
    assert [c.code for c in ordered_chronic_conditions(ctx)] == _CODES


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_outpatient_subjective_lists_every_condition_af_first(lang: str) -> None:
    text, _ = build_outpatient_subjective(TemplateNarrativeGenerator(), _ctx(lang, _conds(_CODES), visit_dx="I48"))
    labels = _labels(lang)
    positions = [text.find(lbl) for lbl in labels]
    assert all(p >= 0 for p in positions), (labels, text)
    assert positions[4] == min(positions), text  # I48 first


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_admission_hp_comorbidities_list_every_condition(lang: str) -> None:
    ctx = _ctx(lang, _conds(_CODES), visit_dx="I48.91", document_type=DocumentType.ADMISSION_HP)
    text = _compose_ap_assessment_from_state(ctx)
    for lbl in _labels(lang):
        assert lbl in text, (lbl, text)


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_nursing_pmh_lists_every_condition(lang: str) -> None:
    ctx = _ctx(lang, _conds(_CODES), visit_dx="I48.91")
    text, _ = build_nursing_history(TemplateNarrativeGenerator(), ctx)
    for lbl in _labels(lang):
        assert lbl in text, (lbl, text)


def test_hpi_history_lists_every_condition_af_first() -> None:
    # The HPI is composed for languages with authored narrative (JA).
    ctx = _ctx("ja", _conds(_CODES), visit_dx="I48.91", document_type=DocumentType.ADMISSION_HP)
    ctx.encounter = SimpleNamespace(chief_complaint_ja="動悸", chief_complaint="動悸", primary_nurse_id="")
    history = _hpi_parts(ctx).details
    labels = _labels("ja")
    positions = [history.find(lbl) for lbl in labels]
    assert all(p >= 0 for p in positions), (labels, history)
    assert positions[4] == min(positions), history  # I48 first


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_assessment_numbers_staged_stageless_and_vital_items_consecutively(lang: str) -> None:
    conds = [
        SimpleNamespace(code="M54.5", stage=""),
        SimpleNamespace(code="", stage=""),  # codeless entry: skipped, must not leave a gap
        SimpleNamespace(code="C16", stage="IV"),
        SimpleNamespace(code="F00", stage="CDR 1"),
        SimpleNamespace(code="G47.30", stage=""),
    ]
    vital = SimpleNamespace(
        systolic_bp=None, diastolic_bp=None, heart_rate=120, temperature_celsius=36.5, spo2=98.0, respiratory_rate=None
    )
    text = _compose_chronic_assessment_integrated(_ctx(lang, conds, vitals=[vital]))
    lines = text.split("\n")
    assert len(lines) == 5, text
    for n, line in enumerate(lines, 1):
        assert re.match(rf"{n}\. ", line), (n, text)


def test_chronic_soap_templates_have_no_line_break_inside_text() -> None:
    reg = load_document_data_yaml("chronic_soap_templates.yaml")
    for code, entry in reg.items():
        if code == "metadata":
            continue
        for section_name, by_lang in entry.items():
            for lang, text in by_lang.items():
                assert "\n" not in str(text).strip(), (code, section_name, lang, text)


def test_no_rendered_ja_soap_line_ends_with_touten() -> None:
    gen = TemplateNarrativeGenerator()
    reg = load_document_data_yaml("chronic_soap_templates.yaml")
    for code in (k for k in reg if k != "metadata"):
        text, _ = build_outpatient_subjective(gen, _ctx("ja", _conds([code])))
        for line in text.split("\n"):
            assert not line.rstrip().endswith("、"), (code, text)
