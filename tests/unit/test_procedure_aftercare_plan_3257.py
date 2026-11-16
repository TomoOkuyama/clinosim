"""Issue #3257 (part b) and #3284 (part a): the operative / procedure note
plan fits the procedure and the patient's location, and JP operative notes
name the surgical approach in Japanese.

The procedure note used one boilerplate plan for every procedure ("monitor the
puncture / insertion site ... follow-up imaging the next day", also for a
urinary catheter), and the operative note wrote "ward-level monitoring" for a
patient who was in the ICU. The plan is now chosen by the catalog's
``aftercare`` category of the procedure type, and the operative note's
recovery destination by where the patient was when the procedure ended.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from clinosim.codes.procedures import bedside_procedures, catalog_procedure_types, procedure_aftercare
from clinosim.locale.i18n import t
from clinosim.locale.loader import load_narrative_op_approach
from clinosim.modules.document.narrative.renderers.section_builders import op_pn_notes
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import load_bedside_procedure_codes
from clinosim.types.procedure import ProcedureRecord

pytestmark = pytest.mark.unit

_SURGICAL = "387713003"
_ADMIT = datetime(2026, 4, 6, 8, 0)
_DISEASE_DIR = Path(__file__).resolve().parents[2] / "clinosim" / "modules" / "disease" / "reference_data"


def _ctx(proc: ProcedureRecord, lang: str, *, icu: bool = False, icu_day: int = -1) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang,
        locale="JP" if lang == "ja" else "US",
        encounter=SimpleNamespace(
            encounter_id=proc.encounter_id, encounter_type="inpatient", admission_datetime=_ADMIT.isoformat()
        ),
        procedures=[proc],
        related_procedure_id=proc.procedure_id,
        roster_map={},
        icu_transferred=icu,
        icu_transferred_day=icu_day,
    )


def _proc(**kw: object) -> ProcedureRecord:
    base: dict = dict(
        procedure_id="PROC-1",
        encounter_id="ENC-1",
        procedure_type="coronary_pci",
        procedure_code="92920",
        procedure_code_us="92920",
        procedure_code_jp="K546",
        category_code=_SURGICAL,
        start_datetime=_ADMIT.replace(hour=10),
        end_datetime=_ADMIT.replace(hour=11),
    )
    base.update(kw)
    return ProcedureRecord(**base)


# ---------------------------------------------------------------------------
# Procedure note: the plan is the procedure's own aftercare.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize("ptype", ["urinary_catheter", "nasogastric_tube"])
def test_device_procedure_note_has_no_puncture_site_or_follow_up_imaging(ptype: str, lang: str) -> None:
    proc = _proc(procedure_type=ptype, procedure_code="J063", procedure_code_jp="J063", category_code="")
    text, _ = op_pn_notes.build_pn_postop_plan(TemplateNarrativeGenerator(), _ctx(proc, lang))
    assert text.startswith(("Post-procedure plan:", "術後方針:"))
    for banned in ("puncture", "imaging", "穿刺", "画像"):
        assert banned not in text, text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_urinary_catheter_plan_is_about_the_catheter(lang: str) -> None:
    proc = _proc(procedure_type="urinary_catheter", category_code="")
    text, _ = op_pn_notes.build_pn_postop_plan(TemplateNarrativeGenerator(), _ctx(proc, lang))
    assert ("catheter" in text) if lang == "en" else ("カテーテル" in text)


def test_procedure_note_plans_differ_by_procedure() -> None:
    gen = TemplateNarrativeGenerator()
    plans = {
        ptype: op_pn_notes.build_pn_postop_plan(gen, _ctx(_proc(procedure_type=ptype), "ja"))[0]
        for ptype in ("urinary_catheter", "central_line", "intubation", "blood_transfusion", "coronary_pci")
    }
    assert len(set(plans.values())) == len(plans), plans


def test_unknown_procedure_type_gets_the_general_plan() -> None:
    proc = _proc(procedure_type="not_in_catalog")
    text, _ = op_pn_notes.build_pn_postop_plan(TemplateNarrativeGenerator(), _ctx(proc, "en"))
    assert text == t("proc_note.postop_plan_line", "en", plan=t("procedure_aftercare.general", "en"))


def test_unsuccessful_procedure_keeps_the_escalation_plan() -> None:
    proc = _proc(procedure_type="urinary_catheter", outcome_code="385671000")
    text, _ = op_pn_notes.build_pn_postop_plan(TemplateNarrativeGenerator(), _ctx(proc, "en"))
    assert text == t("proc_note.postop_unsuccessful", "en")


def test_every_procedure_note_procedure_has_an_aftercare_category() -> None:
    pn_codes = load_bedside_procedure_codes()["procedure_note"]
    for entry in bedside_procedures():
        if str(entry.get("k_code") or "") in pn_codes:
            assert procedure_aftercare(str(entry["type"])), entry["type"]


def test_every_aftercare_category_has_english_and_japanese_text() -> None:
    categories = {procedure_aftercare(ptype) for ptype in catalog_procedure_types()} - {""}
    assert {"general", "surgical_wound"} <= categories | {"general"}
    for cat in categories | {"general"}:
        for lang in ("en", "ja"):
            assert t(f"procedure_aftercare.{cat}", lang), (cat, lang)


# ---------------------------------------------------------------------------
# Operative note: destination by the patient's location, monitoring by procedure.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_operative_note_of_an_icu_patient_says_icu(lang: str) -> None:
    text, _ = op_pn_notes.build_op_postop_plan(TemplateNarrativeGenerator(), _ctx(_proc(), lang, icu=True, icu_day=0))
    assert t("op_note.postop_dest_icu", lang) in text
    assert t("op_note.postop_dest_ward", lang) not in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_operative_note_before_a_later_icu_transfer_says_ward(lang: str) -> None:
    text, _ = op_pn_notes.build_op_postop_plan(TemplateNarrativeGenerator(), _ctx(_proc(), lang, icu=True, icu_day=3))
    assert t("op_note.postop_dest_ward", lang) in text


def test_operative_note_of_a_ward_patient_with_complication_says_ward() -> None:
    proc = _proc(intraop_complications=["bleeding"])
    text, _ = op_pn_notes.build_op_postop_plan(TemplateNarrativeGenerator(), _ctx(proc, "en"))
    assert "ward-level monitoring" in text


def test_pci_operative_note_monitors_the_access_site_not_a_wound() -> None:
    text, _ = op_pn_notes.build_op_postop_plan(TemplateNarrativeGenerator(), _ctx(_proc(), "en", icu=True, icu_day=0))
    assert "access-site" in text.lower()
    assert "wound" not in text and "urine output" not in text


def test_open_surgery_operative_note_keeps_the_wound_plan() -> None:
    proc = _proc(procedure_type="ORIF", procedure_code="27236", procedure_code_us="27236", procedure_code_jp="K0463")
    text, _ = op_pn_notes.build_op_postop_plan(TemplateNarrativeGenerator(), _ctx(proc, "en"))
    assert "wound" in text


# ---------------------------------------------------------------------------
# #3284: surgical approaches read in Japanese, without conditional text.
# ---------------------------------------------------------------------------


def _disease_approach_maps() -> dict[str, dict[str, str]]:
    maps = {}
    for path in sorted(_DISEASE_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        approach = (data.get("procedure") or {}).get("approach") or {}
        if approach:
            maps[path.stem] = {str(k): str(v) for k, v in approach.items()}
    return maps


def _disease_approaches() -> list[str]:
    return [v for m in _disease_approach_maps().values() for v in m.values()]


def test_disease_yamls_have_approaches() -> None:
    assert len(_disease_approaches()) >= 9


def test_approaches_are_keyed_by_a_recorded_procedure_type() -> None:
    # The procedure engine looks the approach up by the recorded procedure
    # type; a key that is no recorded type is never used.
    for disease, approach in _disease_approach_maps().items():
        assert set(approach) <= catalog_procedure_types(), (disease, set(approach) - catalog_procedure_types())


@pytest.mark.parametrize("approach", _disease_approaches())
def test_every_disease_approach_has_english_and_japanese(approach: str) -> None:
    entry = load_narrative_op_approach().get(approach.strip().lower())
    assert entry is not None, approach
    assert entry.get("en") and entry.get("ja"), approach
    # A Latin eponym (Henry) is how JP records write it; English words are not.
    assert not re.search(r"[A-Za-z]{3,}\s+[A-Za-z]{3,}", str(entry["ja"])), entry["ja"]


@pytest.mark.parametrize("approach", _disease_approaches())
def test_disease_approach_has_no_conditional_text(approach: str) -> None:
    assert not re.search(r"\bif\b", approach), approach


@pytest.mark.parametrize(
    "approach",
    [
        "laparoscopic approach with 3-port technique",
        "open reduction and internal fixation",
        "staged escharectomy followed by split-thickness autograft",
    ],
)
def test_jp_operative_note_has_no_english_approach(approach: str) -> None:
    proc = _proc(procedure_type="laparoscopic appendectomy", approach=approach, procedure_code="K718-2")
    gen = TemplateNarrativeGenerator()
    for builder in (op_pn_notes.build_op_procedure_name, op_pn_notes.build_op_course):
        text, _ = builder(gen, _ctx(proc, "ja"))
        assert not re.search(r"[A-Za-z]{3,}(?:\s+[A-Za-z-]+){2,}", text), text
        assert "アプローチアプローチ" not in text
        assert "法アプローチ" not in text, text


def test_english_approach_suffix_follows_the_phrase_flag() -> None:
    gen = TemplateNarrativeGenerator()
    single, _ = op_pn_notes.build_op_course(gen, _ctx(_proc(approach="laparoscopic"), "en"))
    assert "via a laparoscopic approach" in single
    phrase, _ = op_pn_notes.build_op_course(gen, _ctx(_proc(approach="medial parapatellar approach"), "en"))
    assert "via medial parapatellar approach" in phrase
    assert "approach approach" not in phrase


@pytest.mark.parametrize("country", ["US", "JP"])
def test_crush_hand_surgery_records_its_approach(country: str) -> None:
    import numpy as np

    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.modules.procedure.engine import simulate_surgery
    from clinosim.types.patient import PatientProfile

    record, _ = simulate_surgery(
        PatientProfile(patient_id="P-HAND", age=40, sex="M"),
        "crush_injury_hand",
        "ENC-HAND",
        _ADMIT,
        load_disease_protocol("crush_injury_hand"),
        np.random.default_rng(7),
        country,
    )
    assert record.procedure_type == "complex hand surgery"
    assert record.approach == "debridement, fixation, and tendon/nerve repair"
