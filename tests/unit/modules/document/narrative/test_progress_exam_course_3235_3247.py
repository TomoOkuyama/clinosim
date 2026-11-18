"""Progress-note exam, general state and Assessment follow the hospital course
(Issues #3235, #3247): the exam and the general state agree with the vital
signs of the note's period, the "no special findings" filler is not written
beside an abnormal reading, and the Assessment states the post-operative day,
the day each complication began and whether the course improved or worsened."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from clinosim.modules.document.narrative._medication_plan import drug_tier, medication_plan_rules
from clinosim.modules.document.narrative._progress_exam import (
    agreeing_clauses,
    period_states,
    progress_exam_findings,
    progress_exam_rules,
)
from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.document.narrative.renderers._composers import compose_progress_assessment_from_state
from clinosim.modules.document.narrative.renderers.progress_note import render_progress_note
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 5, 1, 10, 0)
_EXAM = {
    "general": {"all": "意識清明、全身状態良好"},
    "cardiovascular": {"all": "整、心雑音なし"},
    "respiratory": {"all": "呼吸音清明、呼吸数正常"},
}


def _v(day: int, hour: int, **fields) -> dict:
    return {"timestamp": datetime(2026, 5, 1 + day, hour, 0).isoformat(), **fields}


def _ctx(vitals: list[dict], *, day: int = 1, lang: str = "ja", procedures=None, events=None) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang,
        vitals=vitals,
        day_index=day,
        los_days=8,
        severity="moderate",
        encounter={"encounter_id": "E1", "admission_datetime": _ADM, "chief_complaint_ja": "呼吸困難"},
        patient={"date_of_birth": "1950-01-01"},
        disease_protocol=SimpleNamespace(disease_id="sepsis"),
        clinical_course_archetype="uncomplicated_improvement",
        authored_datetime=None,
        procedures=procedures or [],
        complications_events=events or [],
        complications_occurred=[],
        lab_results=[],
        medications=[],
        orders=[],
        diagnoses=[],
        allergies=[],
    )


def _note(vitals: list[dict], exam: dict = _EXAM, traj_objective: str = "") -> str:
    gen = TemplateNarrativeGenerator()
    spec = load_document_type_specs()[DocumentType.PROGRESS_NOTE]
    traj = {"subjective": "", "objective": traj_objective, "assessment": "", "plan": ""}
    with (
        patch.object(gen, "_resolve_daily_trajectory_with_source", return_value=(traj, "")),
        patch.object(gen, "_resolve_physical_exam", return_value=exam),
    ):
        return render_progress_note(gen, _ctx(vitals), spec).sections["objective"]


def test_febrile_tachycardic_day_is_not_described_as_well() -> None:
    vitals = [_v(1, 8, temperature_celsius=38.8, heart_rate=105, respiratory_rate=18, spo2=98.0)]
    objective = _note(vitals)
    assert "全身状態良好" not in objective and "特記事項なし" not in objective
    assert "発熱あり" in objective and "頻脈" in objective


def test_normal_day_keeps_the_authored_well_state() -> None:
    vitals = [_v(1, 8, temperature_celsius=36.8, heart_rate=78, respiratory_rate=16, spo2=98.0)]
    objective = _note(vitals)
    assert "全身状態良好" in objective and "呼吸数正常" in objective and "発熱あり" not in objective


def test_tachypnea_removes_normal_respiratory_rate_and_hypoxia_states_oxygen() -> None:
    vitals = [
        _v(
            1,
            8,
            respiratory_rate=28,
            spo2=89.0,
            on_supplemental_oxygen=True,
            oxygen_flow_rate_lpm=4.0,
            oxygen_delivery_device="nasal_cannula",
        )
    ]
    objective = _note(vitals)
    assert "呼吸数正常" not in objective
    assert "頻呼吸" in objective and "SpO2 低下" in objective and "酸素投与下" in objective


def test_exam_clause_stating_the_reading_is_not_duplicated() -> None:
    exam = {"cardiovascular": {"all": "頻脈、整"}}
    ctx = _ctx([_v(1, 8, heart_rate=120)])
    out = progress_exam_findings(ctx, ctx.vitals, exam, "moderate", "ja")
    assert out["cardiovascular"].count("頻脈") == 1


def test_a_reading_of_the_period_other_than_the_first_counts() -> None:
    ctx = _ctx([_v(1, 2, temperature_celsius=36.9), _v(1, 14, temperature_celsius=38.4)])
    assert period_states(ctx, ctx.vitals)["temperature_celsius"] == {"high"}
    assert "全身状態良好" not in agreeing_clauses("意識清明、全身状態良好", period_states(ctx, ctx.vitals), "ja")


def test_authored_objective_text_is_also_filtered() -> None:
    vitals = [_v(1, 8, temperature_celsius=39.0)]
    objective = _note(vitals, exam={}, traj_objective="全身状態良好。創部問題なし")
    assert "全身状態良好" not in objective and "創部問題なし" in objective


def test_distress_is_not_written_for_normal_vitals_without_pain() -> None:
    ctx = _ctx([_v(1, 8, temperature_celsius=36.5, heart_rate=70, respiratory_rate=15, spo2=98.0)])
    assert agreeing_clauses("意識清明、苦痛様", period_states(ctx, ctx.vitals), "ja") == "意識清明"
    sick = _ctx([_v(1, 8, heart_rate=70, pain_score=7)])
    assert "苦痛様" in agreeing_clauses("意識清明、苦痛様", period_states(sick, sick.vitals), "ja")


def test_admission_complaint_does_not_rewrite_every_later_day() -> None:
    vitals = [_v(2, 8, temperature_celsius=36.6, heart_rate=70, respiratory_rate=15, spo2=98.0)]
    assert "笛声音" not in _note(vitals)


def test_no_reading_leaves_the_authored_text() -> None:
    ctx = _ctx([])
    out = progress_exam_findings(ctx, [], _EXAM, "moderate", "ja")
    assert out["general"] == "意識清明、全身状態良好"


def test_english_terms_exist_for_every_term_and_finding() -> None:
    rules = progress_exam_rules()
    assert all("en" in t.terms for t in rules.extra_terms)
    assert all("en" in f.text for f in rules.state_findings)
    ctx = _ctx([_v(1, 8, temperature_celsius=38.8, heart_rate=118)], lang="en")
    out = progress_exam_findings(
        ctx, ctx.vitals, {"general": {"all": "alert, general condition good"}}, "moderate", "en"
    )
    assert "febrile" in out["general"] and "general condition good" not in out["general"]
    assert not any("぀" <= ch <= "鿿" for ch in "".join(out.values()))


# ---- Assessment (Issue #3247) ----------------------------------------------


def _op(day: int) -> dict:
    return {
        "encounter_id": "E1",
        "category_code": "387713003",
        "procedure_type": "ORIF",
        "start_datetime": datetime(2026, 5, 1 + day, 3, 45).isoformat(),
    }


@pytest.mark.parametrize(
    ("day", "ja", "en"),
    [(1, "手術当日", "Day of surgery"), (3, "術後2日目", "Post-operative day 2")],
)
def test_assessment_states_the_post_operative_day(day: int, ja: str, en: str) -> None:
    for lang, expected in (("ja", ja), ("en", en)):
        out = compose_progress_assessment_from_state(_ctx([], day=day, lang=lang, procedures=[_op(1)]))
        assert expected in out


def test_no_post_operative_line_before_the_operation() -> None:
    out = compose_progress_assessment_from_state(_ctx([], day=0, procedures=[_op(1)]))
    assert "術後" not in out and "手術当日" not in out


def test_complication_names_its_day_of_onset() -> None:
    event = {"name": "cerebral_edema", "onset_day": 2, "onset_datetime": "2026-05-03T12:00:00"}
    en = compose_progress_assessment_from_state(_ctx([], day=4, lang="en", events=[event]))
    assert "onset hospital day 3" in en
    ja = compose_progress_assessment_from_state(_ctx([], day=4, events=[event]))
    assert "入院3日目発症" in ja


def test_course_improving_worsening_and_persisting() -> None:
    febrile = {"temperature_celsius": 38.6, "heart_rate": 112}
    well = {"temperature_celsius": 36.8, "heart_rate": 80}
    improving = compose_progress_assessment_from_state(_ctx([_v(1, 8, **febrile), _v(2, 8, **well)], day=2, lang="en"))
    assert "Improving" in improving and "fever" in improving
    worsening = compose_progress_assessment_from_state(_ctx([_v(1, 8, **well), _v(2, 8, **febrile)], day=2, lang="en"))
    assert "Worsening" in worsening and "tachycardia" in worsening
    persisting = compose_progress_assessment_from_state(
        _ctx([_v(1, 8, **febrile), _v(2, 8, **febrile)], day=2, lang="ja")
    )
    assert "持続" in persisting
    stable = compose_progress_assessment_from_state(_ctx([_v(1, 8, **well), _v(2, 8, **well)], day=2, lang="en"))
    assert "Improving" not in stable and "Worsening" not in stable


# ---- aspirin and fluids (Issue #3247 comment) ------------------------------


def test_aspirin_ranks_with_the_antithrombotics_not_the_analgesics() -> None:
    tiers = [t.name for t in medication_plan_rules().tiers]
    assert tiers.index("antithrombotic") < tiers.index("analgesic")
    assert drug_tier("aspirin", "PO") == tiers.index("antithrombotic")
    assert drug_tier("ibuprofen", "PO") == tiers.index("analgesic")


def test_lactated_ringer_is_a_catalog_fluid() -> None:
    from clinosim.codes.drugs import drug_classes

    for drug in ("lactated_ringer_solution", "lactated_ringers_injectable_solution"):
        assert "electrolyte_solution" in drug_classes(drug)
