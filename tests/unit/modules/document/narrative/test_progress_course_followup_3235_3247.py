"""Progress-note follow-up of Issues #3235 / #3247: the pain site and the
observer-based pain statement, unchanged exam findings stated once, the day
after a non-operative procedure, the key labs' course and the Plan items
beyond drugs (diet, rehabilitation, discharge arrangement)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.document.narrative.renderers._composers import (
    compose_progress_assessment_from_state,
    compose_progress_plan_from_state,
    compose_progress_subjective_from_state,
)
from clinosim.modules.document.narrative.renderers.progress_note import render_progress_note
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 5, 1, 10, 0)


def _v(day: int, hour: int, **fields) -> dict:
    return {"timestamp": datetime(2026, 5, 1 + day, hour, 0).isoformat(), **fields}


def _ctx(vitals=None, *, day=2, lang="ja", disease="sepsis", cc_ja="", cc_en="", **extra) -> SimpleNamespace:
    base = {
        "target_lang": lang,
        "vitals": vitals or [],
        "day_index": day,
        "los_days": 8,
        "severity": "moderate",
        "encounter": {
            "encounter_id": "E1",
            "admission_datetime": _ADM,
            "chief_complaint_ja": cc_ja,
            "chief_complaint": cc_en,
            "discharge_disposition": "home",
        },
        "patient": {"date_of_birth": "1950-01-01"},
        "disease_protocol": SimpleNamespace(disease_id=disease, expected_lab_distributions={"admission": {"CRP": {}}}),
        "clinical_course_archetype": "uncomplicated_improvement",
        "authored_datetime": None,
        "procedures": [],
        "complications_events": [],
        "complications_occurred": [],
        "lab_results": [],
        "medications": [],
        "orders": [],
        "diagnoses": [],
        "allergies": [],
        "rehab_sessions": [],
    }
    base.update(extra)
    return SimpleNamespace(**base)


# ---- pain (Issue #3235) -----------------------------------------------------


def test_pain_site_from_the_complaint_when_the_disease_has_none() -> None:
    vitals = [_v(2, 8, pain_score=6, consciousness_level="A")]
    ja = compose_progress_subjective_from_state(_ctx(vitals, cc_ja="腹痛、発熱"))
    assert "腹痛" in ja and "NRS 6" in ja
    en = compose_progress_subjective_from_state(_ctx(vitals, lang="en", cc_en="Abdominal pain and fever"))
    assert "abdominal pain" in en and "NRS 6" in en


def test_disease_pain_site_wins_over_the_complaint() -> None:
    vitals = [_v(2, 8, pain_score=6, consciousness_level="A")]
    out = compose_progress_subjective_from_state(_ctx(vitals, disease="hip_fracture", cc_ja="腹痛"))
    assert "股関節部痛" in out


def test_no_complaint_site_keeps_the_generic_pain() -> None:
    vitals = [_v(2, 8, pain_score=6, consciousness_level="A")]
    assert "腹痛" not in compose_progress_subjective_from_state(_ctx(vitals, cc_ja="倦怠感"))


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_unconscious_patient_gets_no_score_and_a_self_report_statement(lang: str) -> None:
    vitals = [_v(2, 8, pain_score=7, consciousness_level="P")]
    out = compose_progress_subjective_from_state(_ctx(vitals, lang=lang, cc_ja="胸痛", cc_en="Chest pain"))
    assert "NRS" not in out and "7" not in out.split("AVPU")[0]
    assert ("自己申告は困難" in out) if lang == "ja" else ("not possible" in out)
    assert ("胸痛" in out) if lang == "ja" else ("chest pain" in out)


# ---- unchanged exam ---------------------------------------------------------

_EXAM = {"general": {"all": "意識清明、全身状態良好"}, "cardiovascular": {"all": "整、心雑音なし"}}


def _note(vitals: list[dict], day: int = 2, exam: dict | None = None) -> str:
    gen = TemplateNarrativeGenerator()
    spec = load_document_type_specs()[DocumentType.PROGRESS_NOTE]
    traj = {"subjective": "", "objective": "", "assessment": "", "plan": ""}
    with (
        patch.object(gen, "_resolve_daily_trajectory_with_source", return_value=(traj, "")),
        patch.object(gen, "_resolve_physical_exam", return_value=exam or _EXAM),
    ):
        return render_progress_note(gen, _ctx(vitals, day=day), spec).sections["objective"]


def test_identical_exam_is_stated_as_unchanged() -> None:
    well = dict(temperature_celsius=36.8, heart_rate=78, respiratory_rate=16, spo2=98.0)
    out = _note([_v(1, 8, **well), _v(2, 8, **well)])
    assert "身体所見: 前日と著変なし" in out and "心雑音なし" not in out


def test_a_changed_system_is_written_and_the_rest_collapsed() -> None:
    well = dict(temperature_celsius=36.8, heart_rate=78, respiratory_rate=16, spo2=98.0)
    exam = {"general": {"all": "意識清明"}, "cardiovascular": {"all": "整、心雑音なし"}}
    out = _note([_v(1, 8, **well), _v(2, 8, **{**well, "heart_rate": 120})], exam=exam)
    assert "頻脈" in out and "一般状態: 前日と著変なし" in out


def test_the_first_day_is_never_collapsed() -> None:
    out = _note([_v(0, 8, heart_rate=70)], day=0)
    # the admission day writes the disease's admission exam (Issue #3227), never "unchanged"
    assert "前日と著変なし" not in out and "循環器:" in out


# ---- post-procedure day -----------------------------------------------------


def _proc(ptype: str, day: int, category: str = "387713003") -> dict:
    return {
        "encounter_id": "E1",
        "category_code": category,
        "procedure_type": ptype,
        "start_datetime": datetime(2026, 5, 1 + day, 3, 45).isoformat(),
    }


@pytest.mark.parametrize(
    ("ptype", "day", "ja", "en"),
    [
        ("coronary_pci", 3, "処置後2日目", "Post-procedure day 2"),
        ("coronary_pci", 1, "処置当日", "Day of procedure"),
        ("ORIF", 3, "術後2日目", "Post-operative day 2"),
    ],
)
def test_procedure_versus_operation_wording(ptype: str, day: int, ja: str, en: str) -> None:
    for lang, expected in (("ja", ja), ("en", en)):
        out = compose_progress_assessment_from_state(_ctx(day=day, lang=lang, procedures=[_proc(ptype, 1)]))
        assert expected in out
    assert "術後" not in compose_progress_assessment_from_state(_ctx(day=day, procedures=[_proc("coronary_pci", 1)]))


# ---- key labs ---------------------------------------------------------------


def _lab(name: str, value: float, flag: str, day: int) -> dict:
    return {
        "lab_name": name,
        "value": value,
        "unit": "mg/dL",
        "flag": flag,
        "result_datetime": datetime(2026, 5, 1 + day, 6, 0).isoformat(),
    }


def test_key_lab_improving_and_worsening() -> None:
    better = [_lab("CRP", 12.0, "H", 1), _lab("CRP", 3.0, "H", 2)]
    out = compose_progress_assessment_from_state(_ctx(day=2, lang="en", lab_results=better))
    assert "Key labs improving (CRP 12" in out and "→ 3" in out
    worse = [_lab("CRP", 3.0, "H", 1), _lab("CRP", 12.0, "H", 2)]
    out = compose_progress_assessment_from_state(_ctx(day=2, lab_results=worse))
    assert "主要検査は増悪" in out and "CRP" in out


def test_a_lab_outside_the_admission_problem_is_not_a_key_lab() -> None:
    labs = [_lab("Glucose", 300.0, "H", 1), _lab("Glucose", 120.0, "H", 2)]
    out = compose_progress_assessment_from_state(_ctx(day=2, lang="en", lab_results=labs))
    assert "Key labs" not in out


def test_a_result_after_the_note_time_is_not_compared() -> None:
    labs = [_lab("CRP", 12.0, "H", 1), _lab("CRP", 3.0, "H", 2)]
    ctx = _ctx(day=2, lang="en", lab_results=labs, authored_datetime=datetime(2026, 5, 3, 5, 0))
    assert "Key labs" not in compose_progress_assessment_from_state(ctx)


# ---- plan items beyond drugs ------------------------------------------------


def _diet(slug: str, day: int) -> dict:
    return {"order_type": "diet", "display_name": slug, "ordered_datetime": datetime(2026, 5, 1 + day, 7, 0)}


def test_plan_names_the_diet_and_its_change() -> None:
    orders = [_diet("NPO", 0), _diet("soft_diet", 2)]
    assert "食事を" in compose_progress_plan_from_state(_ctx(day=2, orders=orders))
    en = compose_progress_plan_from_state(_ctx(day=3, lang="en", orders=orders))
    assert "Diet:" in en and "Diet changed" not in en


def test_plan_names_the_rehab_of_the_day() -> None:
    sessions = [SimpleNamespace(therapy_type="PT", session_date=datetime(2026, 5, 3, 10, 0))]
    assert "リハビリテーション継続 (PT)" in compose_progress_plan_from_state(_ctx(day=2, rehab_sessions=sessions))
    assert "Rehabilitation" not in compose_progress_plan_from_state(_ctx(day=3, lang="en", rehab_sessions=sessions))


def test_discharge_planning_only_near_discharge_and_not_after_death() -> None:
    assert "退院に向けて" in compose_progress_plan_from_state(_ctx(day=7))
    assert "退院に向けて" not in compose_progress_plan_from_state(_ctx(day=3))
    assert "Discharge planning" in compose_progress_plan_from_state(_ctx(day=7, lang="en"))
    died = _ctx(day=7)
    died.encounter["discharge_disposition"] = "exp"
    assert "退院" not in compose_progress_plan_from_state(died)
