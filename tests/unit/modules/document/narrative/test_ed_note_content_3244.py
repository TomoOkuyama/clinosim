"""ED notes carry the vitals, a focused exam, the results and the Rx (Issue #3244).

The English ED exam had no vitals, the triage note had none in either
locale, imaging was listed by name only, the take-home prescription was
missing from the disposition, a template's unresolved placeholders dropped
its abdominal line, and the JP workup repeated a study ordered twice.
"""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._template_helpers import _fill_template_placeholders
from clinosim.modules.document.narrative.renderers.ed_triage_note import render_ed_triage_note
from clinosim.modules.document.narrative.renderers.section_builders.ed_note import (
    build_ed_disposition,
    build_ed_physical_exam,
    build_ed_workup,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_WHEN = datetime(2025, 11, 20, 18, 35)
_VITALS = [
    {
        "timestamp": _WHEN.isoformat(),
        "systolic_bp": 107,
        "diastolic_bp": 70,
        "heart_rate": 77,
        "respiratory_rate": 21,
        "spo2": 98.0,
        "temperature_celsius": 36.8,
        "pain_score": 6,
    }
]


def _ctx(cond: str, lang: str, **over) -> NarrativeContext:
    values = dict(
        patient=PatientProfile(patient_id="PT-1", age=45, sex="M"),
        encounter=SimpleNamespace(
            encounter_id="ENC-1",
            encounter_type=SimpleNamespace(value="emergency"),
            admission_datetime=_WHEN,
            chief_complaint="x",
            discharge_disposition="home",
            triage_data=SimpleNamespace(
                level="3", level_system="ESI", arrival_mode="walk_in", chief_complaint_summary="x"
            ),
        ),
        encounter_type=SimpleNamespace(value="emergency"),
        disease_protocol=None,
        encounter_protocol=load_encounter_condition(cond),
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=_VITALS,
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ED_NOTE,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        orders=[],
    )
    values.update(over)
    return NarrativeContext(**values)


_GEN = TemplateNarrativeGenerator()


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_the_exam_of_every_locale_starts_with_the_arrival_vitals(lang: str) -> None:
    text, _ = build_ed_physical_exam(_GEN, _ctx("low_back_pain", lang))
    assert "BP 107/70 mmHg" in text and "HR 77/min" in text, text
    assert "6/10" in text, text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_the_triage_note_states_the_triage_vitals(lang: str) -> None:
    out = render_ed_triage_note(_ctx("low_back_pain", lang), SimpleNamespace())
    assert "BP 107/70 mmHg" in out.raw_text and "HR 77/min" in out.raw_text, out.raw_text


def test_a_triage_note_without_vitals_has_no_vitals_line() -> None:
    out = render_ed_triage_note(_ctx("low_back_pain", "en", vitals=[]), SimpleNamespace())
    assert "vital" not in out.raw_text.lower()


def test_low_back_pain_exam_examines_the_back_and_the_legs() -> None:
    text, _ = build_ed_physical_exam(_GEN, _ctx("low_back_pain", "en"))
    assert "paraspinal" in text and "Lower-limb strength" in text, text


def test_abdominal_pain_exam_has_the_abdominal_line() -> None:
    for lang, word in (("en", "tenderness"), ("ja", "圧痛")):
        text, _ = build_ed_physical_exam(_GEN, _ctx("abdominal_pain_nonspecific", lang))
        assert word in text and "{" not in text, text


def test_burn_note_names_one_site_and_one_mechanism_in_hpi_and_exam() -> None:
    from clinosim.modules.document.narrative._template_helpers import _pick_localized
    from clinosim.modules.document.narrative.renderers._ed_helpers import get_ed_note_template

    for lang in ("en", "ja"):
        ctx = _ctx("minor_burn", lang)
        hpi = _pick_localized(get_ed_note_template(ctx), "hpi", lang, ctx)
        exam, _ = build_ed_physical_exam(_GEN, ctx)
        assert " or " not in hpi and "{" not in hpi, hpi
        assert "手または腕" not in hpi
        # The exam names the same site the HPI names.
        site = next(
            s
            for s in ctx.encounter_protocol["narrative"]["ed_note_template"]["variants"]["burn__site"][lang]
            if s in hpi
        )
        assert site in exam, (hpi, exam)


def _study(order_id: str, impression: str, ja: str) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id,
        report=SimpleNamespace(impression_text=impression, impression_text_ja=ja, issued_datetime=_WHEN.isoformat()),
    )


def _imaging_order(order_id: str, name: str) -> dict:
    return {
        "order_id": order_id,
        "encounter_id": "ENC-1",
        "order_type": "imaging",
        "display_name": name,
        "ordered_datetime": _WHEN.isoformat(),
    }


def test_imaging_is_listed_with_the_impression_of_its_report() -> None:
    ctx = _ctx(
        "low_back_pain",
        "en",
        orders=[_imaging_order("O1", "Lumbar_Xray")],
        imaging_studies=[_study("O1", "No acute fracture.", "明らかな骨折なし。")],
    )
    text, _ = build_ed_workup(_GEN, ctx)
    assert "(No acute fracture)" in text, text


def test_the_same_study_ordered_twice_is_listed_once() -> None:
    orders = [_imaging_order("O1", "Chest_Xray"), _imaging_order("O2", "Chest_Xray")]
    text, _ = build_ed_workup(_GEN, _ctx("chest_pain_noncardiac", "ja", orders=orders))
    imaging = text.split("画像: ", 1)[1].split("。")[0]
    assert "、" not in imaging, imaging


def test_labs_are_listed_with_their_values() -> None:
    order = {
        "order_id": "L1",
        "encounter_id": "ENC-1",
        "order_type": "lab",
        "display_name": "WBC",
        "ordered_datetime": _WHEN.isoformat(),
        "result": {
            "lab_name": "WBC",
            "value": 14.2,
            "unit": "10*3/uL",
            "flag": "H",
            "result_datetime": _WHEN.isoformat(),
        },
    }
    text, _ = build_ed_workup(_GEN, _ctx("low_back_pain", "en", orders=[order]))
    assert "14.2" in text and "[H]" in text, text


def test_the_disposition_lists_the_discharge_prescription() -> None:
    meds = [
        {"drug_name": "Ibuprofen 600mg", "dose": "600mg"},
        {"drug_name": "Cyclobenzaprine", "dose": "10mg"},
    ]
    text, facts = build_ed_disposition(_GEN, _ctx("low_back_pain", "en", discharge_medications=meds))
    assert "Discharge prescription: Ibuprofen 600mg, Cyclobenzaprine 10mg." in text, text
    assert "ctx.discharge_medications" in facts


def test_a_visit_without_a_prescription_has_no_prescription_line() -> None:
    text, _ = build_ed_disposition(_GEN, _ctx("low_back_pain", "en"))
    assert "prescription" not in text.lower()


# --- template data ---------------------------------------------------------------

_CONDITIONS = sorted(
    p.stem
    for p in (
        __import__("pathlib").Path(__file__).resolve().parents[5] / "clinosim/modules/encounter/reference_data"
    ).glob("*.yaml")
    if (load_encounter_condition(p.stem).get("narrative") or {}).get("ed_note_template")
)


@pytest.mark.parametrize("cond", _CONDITIONS)
@pytest.mark.parametrize("lang", ["en", "ja"])
def test_every_placeholder_of_the_hpi_and_exam_templates_resolves(cond: str, lang: str) -> None:
    from clinosim.locale.i18n import t

    tmpl = load_encounter_condition(cond)["narrative"]["ed_note_template"]
    ctx = _ctx(cond, lang)
    generic = t("fallback.generic_fallback", lang)
    texts = [tmpl["hpi"][lang], *tmpl["physical_exam"][lang].values()]
    for text in texts:
        filled = _fill_template_placeholders(text, ctx, lang)
        assert filled != generic and not re.search(r"\{\w+\}", filled), (cond, lang, text)


_INSTRUCTION = re.compile(r"(を確認|を聴取|を評価)(する)?。|\b(reviewed|assessed|evaluated)\.$")


@pytest.mark.parametrize("cond", _CONDITIONS)
def test_ed_hpi_states_findings_not_instructions(cond: str) -> None:
    hpi = load_encounter_condition(cond)["narrative"]["ed_note_template"]["hpi"]
    for lang, text in hpi.items():
        assert not _INSTRUCTION.search(text), (cond, lang, text)


# --- allergies and the prescription schedule ----------------------------------------


@pytest.mark.parametrize("lang,word", [("en", "Allergies"), ("ja", "アレルギー")])
def test_the_triage_note_and_triage_details_state_the_allergies(lang: str, word: str) -> None:
    from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_triage_details

    out = render_ed_triage_note(_ctx("low_back_pain", lang), SimpleNamespace())
    assert word in out.raw_text
    details, facts = build_triage_details(_GEN, _ctx("low_back_pain", lang))
    assert word in details and "ctx.allergies" in facts


def test_a_recorded_allergy_is_named() -> None:
    allergy = SimpleNamespace(allergen_code="372687004", is_nka=False, criticality="")
    out = render_ed_triage_note(_ctx("low_back_pain", "en", allergies=[allergy]), SimpleNamespace())
    assert "Amoxicillin" in out.raw_text, out.raw_text


def test_the_prescription_line_carries_frequency_and_days() -> None:
    meds = [{"drug_name": "Ibuprofen", "dose": "600mg", "rx_frequency": "tid", "rx_duration_days": 10}]
    en, _ = build_ed_disposition(_GEN, _ctx("low_back_pain", "en", discharge_medications=meds))
    assert "Ibuprofen 600mg tid x10d" in en, en
    ja, _ = build_ed_disposition(_GEN, _ctx("low_back_pain", "ja", discharge_medications=meds))
    assert "10日分" in ja and "tid" not in ja, ja


def test_the_collector_carries_the_schedule_of_an_ed_prescription() -> None:
    from clinosim.modules.document.narrative.passes import NarrativePass

    rx = {"items": [{"drug_name": "Ibuprofen", "dose": "600mg", "frequency": "tid", "duration_days": 10}]}
    [med] = NarrativePass._collect_discharge_medications({"discharge_prescription": rx})
    assert med["rx_frequency"] == "tid" and med["rx_duration_days"] == 10


def test_a_non_numeric_supply_is_not_a_duration() -> None:
    from clinosim.modules.document.narrative.passes import NarrativePass

    rx = {"items": [{"drug_name": "Metformin", "dose": "500mg", "days_supply": "ongoing"}]}
    [med] = NarrativePass._collect_discharge_medications({"discharge_prescription": rx})
    assert "rx_duration_days" not in med
