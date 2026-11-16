"""Tests for TemplateNarrativeGenerator rehabilitation_plan sections (chain 2,
third and final chain-2 sub-project).

Mirrors tests/unit/modules/document/narrative/test_template_generator_nutrition_care_plan.py.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, FormatType, NarrativeContext
from clinosim.types.patient import PatientProfile

_RP_SECTIONS = (
    "patient_and_diagnosis",
    "rehab_team",
    "functional_status",
    "basic_movement",
    "session_frequency",
    "goals",
    "policy",
    "discharge_estimate",
    "explanation_consent",
)


def _make_spec() -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="rehabilitation_plan",
        loinc_code="34823-5",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp",),
        generation_frequency="admission_once_if_rehab_sessions",
        composition_sections=_RP_SECTIONS,
        encounter_types_supported=("inpatient",),
        stage2_strategy="template_only",
    )


def _make_encounter() -> Any:
    return SimpleNamespace(
        encounter_id="enc-rp-test",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        attending_physician_id="dr-rp-001",
    )


def _rehab_session(
    day_post_op: int = 1,
    session_date: datetime = datetime(2026, 7, 2, 10, 0),
    functional_progress: str = "stable",
    patient_participation: str = "good",
    pain_score: int | None = 3,
    duration_minutes: int = 40,
    therapy_type: str = "PT",
) -> dict[str, Any]:
    return {
        "session_id": f"REHAB-test-{day_post_op:03d}",
        "patient_id": "pt-rp-test",
        "encounter_id": "enc-rp-test",
        "therapy_type": therapy_type,
        "session_date": session_date,
        "duration_minutes": duration_minutes,
        "day_post_op": day_post_op,
        "activities": ["bed exercises"],
        "patient_participation": patient_participation,
        "pain_score": pain_score,
        "functional_progress": functional_progress,
    }


def _make_ctx(
    encounter: Any = None,
    rehab_sessions: list[Any] | None = None,
    target_lang: str = "ja",
    locale: str = "jp",
    authored_datetime: datetime | None = None,
) -> NarrativeContext:
    return NarrativeContext(
        patient=PatientProfile(patient_id="pt-rp-test"),
        encounter=encounter or _make_encounter(),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=10,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.REHABILITATION_PLAN,
        target_lang=target_lang,
        locale=locale,
        rehab_sessions=rehab_sessions if rehab_sessions is not None else [_rehab_session()],
        authored_datetime=authored_datetime,
    )


def test_rehabilitation_plan_returns_all_9_sections_non_empty() -> None:
    spec = _make_spec()
    ctx = _make_ctx()
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict)
    for section in _RP_SECTIONS:
        assert section in out.sections, f"section {section!r} missing"
        assert out.sections[section].strip() != "", f"section {section!r} is empty"


def test_rehabilitation_plan_jp_has_japanese_text() -> None:
    spec = _make_spec()
    ctx = _make_ctx(target_lang="ja", locale="jp")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    all_text = " ".join(out.sections.values())
    has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
    assert has_jp, f"rehabilitation_plan sections contain no Japanese text: {all_text[:300]!r}"


def test_rehabilitation_plan_en_no_crash() -> None:
    spec = _make_spec()
    ctx = _make_ctx(target_lang="en", locale="us")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section in _RP_SECTIONS:
        assert out.sections[section].strip() != ""


def test_rehab_team_lists_therapy_type() -> None:
    spec = _make_spec()
    ctx = _make_ctx(rehab_sessions=[_rehab_session(therapy_type="PT")])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "PT" in out.sections["rehab_team"]


def test_rehab_team_fallback_when_no_sessions() -> None:
    spec = _make_spec()
    ctx = _make_ctx(rehab_sessions=[])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.sections["rehab_team"].strip() != ""


def test_basic_movement_early_phase_for_day_post_op_1() -> None:
    spec = _make_spec()
    ctx = _make_ctx(rehab_sessions=[_rehab_session(day_post_op=1)])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "早期" in out.sections["basic_movement"]


def test_basic_movement_late_phase_for_day_post_op_20() -> None:
    spec = _make_spec()
    ctx = _make_ctx(rehab_sessions=[_rehab_session(day_post_op=20)])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "後期" in out.sections["basic_movement"]


def test_discharge_estimate_is_undetermined_when_no_disease_protocol() -> None:
    """Issue #3240: the realized ctx.los_days is never stated as an estimate."""
    spec = _make_spec()
    ctx = _make_ctx()
    ctx.los_days = 14
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "14" not in out.sections["discharge_estimate"]
    assert "未定" in out.sections["discharge_estimate"]


# ── Issue #3261: the plan is written at the start of rehabilitation ──────


def _stay_sessions() -> list[dict[str, Any]]:
    """POD1 baseline session (authored the same afternoon) + later sessions
    that happen after the plan was written."""
    return [
        _rehab_session(
            day_post_op=1,
            session_date=datetime(2026, 7, 2, 10, 0),
            functional_progress="stable",
            patient_participation="fair",
            pain_score=6,
        ),
        _rehab_session(
            day_post_op=8,
            session_date=datetime(2026, 7, 9, 10, 0),
            functional_progress="improved",
            pain_score=2,
        ),
        _rehab_session(
            day_post_op=20,
            session_date=datetime(2026, 7, 21, 10, 0),
            functional_progress="improved",
            pain_score=1,
            therapy_type="OT",
        ),
    ]


def _plan_sections(**kw: Any) -> dict[str, str]:
    ctx = _make_ctx(rehab_sessions=_stay_sessions(), authored_datetime=datetime(2026, 7, 2, 13, 45), **kw)
    return TemplateNarrativeGenerator().generate(ctx, _make_spec()).sections


def test_functional_status_uses_the_session_known_at_authoring_3261() -> None:
    fs = _plan_sections()["functional_status"]
    assert "6/10" in fs
    assert "やや不良" in fs
    assert "2026-07-02" in fs
    assert "改善" not in fs
    assert "1/10" not in fs and "2/10" not in fs


def test_basic_movement_uses_the_session_known_at_authoring_3261() -> None:
    assert "早期" in _plan_sections()["basic_movement"]


def test_session_frequency_is_planned_not_counted_3261() -> None:
    sf = _plan_sections()["session_frequency"]
    assert "1日1回" in sf
    assert "40分" in sf
    assert "2026-07-02" in sf
    assert "2026-07-21" not in sf
    assert "3回" not in sf


def test_rehab_team_lists_only_disciplines_known_at_authoring_3261() -> None:
    team = _plan_sections()["rehab_team"]
    assert "PT" in team
    assert "OT" not in team


def test_explanation_given_on_authored_date_3261() -> None:
    ex = _plan_sections()["explanation_consent"]
    assert "説明済" in ex
    assert "2026-07-02" in ex
    assert "予定" not in ex


def test_rehab_plan_en_has_no_japanese_3261() -> None:
    sections = _plan_sections(target_lang="en", locale="us")
    text = " ".join(sections.values())
    assert not any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in text), text
    assert "once daily" in sections["session_frequency"]
    assert "2026-07-02" in sections["explanation_consent"]
