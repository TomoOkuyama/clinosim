"""B9 follow-up (#1074): outpatient / ED assessment composer for the
remaining `Clinical assessment ongoing` residual.

Prior to the fix, `_build_outpatient_assessment` short-circuited to
`_GENERIC_ASSESSMENT_EN` when:
  - document_type is ED_NOTE (hard early return)
  - patient has NO chronic conditions AND no encounter_soap_template

This PR wires two new composers to fill both paths from CIF facts.
"""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.types.document import DocumentType


def _ctx(lang: str = "en", **kw) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang,
        locale="us" if lang == "en" else "jp",
        document_type=kw.get("document_type", DocumentType.PROGRESS_NOTE),
        patient=SimpleNamespace(chronic_conditions=kw.get("chronic", [])),
        encounter=SimpleNamespace(
            chief_complaint=kw.get("chief_complaint", ""),
            primary_diagnosis=kw.get("primary_diagnosis", ""),
        ),
        encounter_type=None,
        encounter_protocol=None,
        disease_protocol=None,
        complications_occurred=kw.get("complications", []),
        working_diagnoses=kw.get("working_dx", []),
        vitals=[],
        lab_results=[],
        medications=[],
        procedures=[],
        clinical_course_archetype="",
        severity="moderate",
        day_index=0,
        los_days=1,
    )


# ---------------------------------------------------------------------------
# _compose_encounter_reason_line
# ---------------------------------------------------------------------------


def test_encounter_reason_from_chief_complaint_en() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_encounter_reason_line(_ctx("en", chief_complaint="Chest pain, dyspnea"))
    assert "Encounter reason" in out
    assert "Chest pain" in out


def test_encounter_reason_from_chief_complaint_ja() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_encounter_reason_line(_ctx("ja", chief_complaint="胸痛、呼吸困難"))
    assert "来院理由" in out
    assert "胸痛" in out


def test_encounter_reason_falls_back_to_primary_dx() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_encounter_reason_line(_ctx("en", primary_diagnosis="Acute myocardial infarction"))
    assert "Primary problem" in out
    assert "Acute myocardial infarction" in out


def test_encounter_reason_empty_when_no_facts() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    assert gen._compose_encounter_reason_line(_ctx("en")) == ""


# ---------------------------------------------------------------------------
# _compose_ed_assessment_from_state
# ---------------------------------------------------------------------------


def test_ed_assessment_from_working_dx_en() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_ed_assessment_from_state(
        _ctx(
            "en",
            working_dx=[{"disease_id": "I21.9"}, {"disease_id": "I50"}],
        )
    )
    assert "ED working assessment" in out


def test_ed_assessment_falls_back_to_chief_complaint() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_ed_assessment_from_state(_ctx("en", chief_complaint="Chest pain, diaphoresis"))
    # No working_dx → returns chief-complaint-based line
    assert "Encounter reason" in out
    assert "Chest pain" in out


def test_ed_assessment_includes_complications() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_ed_assessment_from_state(
        _ctx(
            "en",
            working_dx=[{"disease_id": "A41.9"}],
            complications=["septic_shock"],
        )
    )
    assert "septic_shock" in out
    assert "Complications" in out


def test_ed_assessment_empty_when_no_facts() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    # No working_dx AND no chief_complaint → composer returns empty
    assert gen._compose_ed_assessment_from_state(_ctx("en")) == ""


# ---------------------------------------------------------------------------
# _build_outpatient_assessment integration
# ---------------------------------------------------------------------------


def test_ed_note_document_type_now_composes_from_state() -> None:
    """ED_NOTE previously returned generic fallback. Now composes from CIF."""
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_outpatient_assessment(
        _ctx(
            "en",
            document_type=DocumentType.ED_NOTE,
            chief_complaint="Chest pain, diaphoresis, dyspnea",
        )
    )
    assert "Clinical assessment ongoing" not in text
    assert "Chest pain" in text
    assert "ctx.ed_assessment.state_composed" in facts


def test_outpatient_no_chronic_composes_from_encounter_reason() -> None:
    """Outpatient patient with NO chronic conditions previously fell to
    generic. Now uses chief_complaint as anchor."""
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_outpatient_assessment(
        _ctx(
            "en",
            chronic=[],  # no chronic conditions
            chief_complaint="Annual physical exam",
        )
    )
    assert "Clinical assessment ongoing" not in text
    assert "Encounter reason" in text
    assert "ctx.encounter.chief_complaint" in facts


def test_outpatient_still_uses_chronic_when_present() -> None:
    """Regression guard — patient with chronic conditions gets chronic-list
    line, not the new encounter-reason fallback."""
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    class _Cond:
        def __init__(self, code):
            self.code = code

    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_outpatient_assessment(_ctx("en", chronic=[_Cond("I10"), _Cond("E11.9")]))
    # chronic_condition_line or integrated composer wins
    assert "Encounter reason" not in text  # new fallback didn't fire
    assert "Clinical assessment ongoing" not in text
