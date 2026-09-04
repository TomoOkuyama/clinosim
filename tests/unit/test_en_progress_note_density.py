"""B9 (#1074): EN inpatient progress-note assessment/plan composers.

Prior to the fix, both composers hard short-circuited for ``target_lang != "ja"``,
returning empty string. Downstream ``_render_progress_note_text`` then fell
back to `_GENERIC_ASSESSMENT_EN` ("Clinical assessment ongoing") and
`_GENERIC_PLAN_EN` ("Continue current management") for every day of every
encounter — 19.4 % + 7.8 % of 1,409 progress notes in the US p=2000
seed=500 baseline.
"""

from __future__ import annotations

from types import SimpleNamespace


def _ctx(lang: str = "en", **kw) -> SimpleNamespace:
    """Minimal NarrativeContext-shaped SimpleNamespace for the composer tests.

    Composers read ``target_lang``, ``complications_occurred``, ``lab_results``,
    ``day_index``, ``medications``, ``procedures``. Everything else is unused.
    """
    return SimpleNamespace(
        target_lang=lang,
        complications_occurred=kw.get("complications", []),
        lab_results=kw.get("labs", []),
        day_index=kw.get("day_index", 1),
        medications=kw.get("meds", []),
        procedures=kw.get("procs", []),
    )


def _lab(name: str, val: float, flag: str, unit: str = "", day: int = 1) -> dict:
    return {"lab_name": name, "value": val, "unit": unit, "flag": flag, "day": day}


def _med(name: str, day: int = 1) -> dict:
    return {"drug_name": name, "day": day}


# ---------------------------------------------------------------------------
# _compose_progress_assessment_from_state
# ---------------------------------------------------------------------------


def test_en_assessment_stable_fallback() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_progress_assessment_from_state(_ctx("en"))
    assert out == "Clinical course stable, no significant change."


def test_en_assessment_with_complications() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_progress_assessment_from_state(
        _ctx("en", complications=["pneumothorax", "aspiration_pneumonia"])
    )
    assert "pneumothorax" in out
    assert "aspiration_pneumonia" in out
    assert "Complications noted" in out


def test_en_assessment_cites_abnormal_labs_today() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_progress_assessment_from_state(
        _ctx(
            "en",
            labs=[
                _lab("Creatinine", 2.1, "H", "mg/dL"),
                _lab("K", 5.6, "H", "mmol/L"),
                _lab("Hb", 12, "", "g/dL"),  # not flagged, ignored
            ],
        )
    )
    assert "Creatinine 2.1 mg/dL [H]" in out
    assert "K 5.6 mmol/L [H]" in out
    assert "Notable labs today" in out


def test_ja_assessment_still_uses_kanji_prose() -> None:
    """Regression guard — JA branch untouched by this refactor."""
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_progress_assessment_from_state(_ctx("ja", complications=["pneumothorax"]))
    assert "合併症" in out
    assert "pneumothorax" in out


# ---------------------------------------------------------------------------
# _compose_progress_plan_from_state
# ---------------------------------------------------------------------------


def test_en_plan_stable_fallback() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_progress_plan_from_state(_ctx("en"))
    assert out == "Continue current management, observe course."


def test_en_plan_lists_medications() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_progress_plan_from_state(
        _ctx("en", meds=[_med("Ceftriaxone"), _med("Azithromycin"), _med("Enoxaparin")])
    )
    assert "Ceftriaxone" in out
    assert "Azithromycin" in out
    assert "Enoxaparin" in out
    assert "Continue current medications" in out


def test_en_plan_lists_procedures() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_progress_plan_from_state(
        _ctx("en", procs=[{"procedure_name": "Chest X-ray"}, {"procedure_name": "CT abdomen"}])
    )
    assert "Chest X-ray" in out
    assert "CT abdomen" in out
    assert "Procedures today" in out


def test_en_plan_dedupes_med_names() -> None:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    # Same drug administered twice today
    out = gen._compose_progress_plan_from_state(
        _ctx("en", meds=[_med("Ceftriaxone"), _med("Ceftriaxone"), _med("Enoxaparin")])
    )
    # Ceftriaxone appears only once in the deduplicated list
    assert out.count("Ceftriaxone") == 1


def test_ja_plan_still_uses_kanji_prose() -> None:
    """Regression guard — JA branch untouched."""
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_progress_plan_from_state(_ctx("ja", meds=[_med("Ceftriaxone")]))
    assert "薬物療法継続" in out


def test_en_med_filter_by_day() -> None:
    """MAR entries for other days must not leak into today's plan."""
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

    gen = TemplateNarrativeGenerator()
    out = gen._compose_progress_plan_from_state(
        _ctx(
            "en",
            day_index=2,
            meds=[
                _med("Ceftriaxone", day=1),  # yesterday, filtered
                _med("Enoxaparin", day=2),  # today, included
            ],
        )
    )
    assert "Enoxaparin" in out
    assert "Ceftriaxone" not in out
