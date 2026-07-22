"""Integration: JP cohort uses Japanese displays throughout the document chain.

Verifies:
- Composition.type.coding[0].display is Japanese (e.g., "入院時記録" / "退院時サマリー")
- DocumentReference.type.coding[0].display is Japanese (e.g., "経過記録")
- AllergyIntolerance.code.coding[0].display is Japanese when SNOMED code has ja entry
  (e.g., "ペニシリン" for SNOMED 387207008 Penicillin)
- Composition.section[].text.div contains Japanese characters (template generator JP output)

Note on ClinicalImpression.description:
  The α-min-1 implementation generates "Day {N} clinical assessment" — always English —
  since no locale-specific description template exists yet (β-JP-1 scope).
  JP localization of ClinicalImpression.description is deferred; the JP localization
  test only checks the structure (subject / encounter refs present) for this resource.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate


def _has_jp_chars(s: str) -> bool:
    """Return True if *s* contains any CJK / Hiragana / Katakana character."""
    return any(
        "぀" <= c <= "ヿ"  # Hiragana + Katakana
        or "一" <= c <= "鿿"  # CJK Unified Ideographs (common range)
        or "㐀" <= c <= "䶿"  # CJK Extension A
        or "＀" <= c <= "￯"  # Fullwidth / Halfwidth forms
        for c in s
    )


def _loinc_code_from_type(resource: dict) -> str:
    return next(
        (c.get("code", "") for c in resource.get("type", {}).get("coding", [])),
        "",
    )


def _first_display_from_type(resource: dict) -> str:
    return next(
        (c.get("display", "") for c in resource.get("type", {}).get("coding", [])),
        "",
    )


def _text_or_first_display_from_type(resource: dict) -> str:
    """Return the JP-UI-visible label for ``resource.type``.

    Issue #360 G5 (2026-07-22): DocumentReference.type now emits EN LOINC
    canonical on ``coding[].display`` (walker-safe on English-only LOINC
    CS) + JP on ``text``. Prefer ``type.text``, else fall back to
    ``coding[0].display`` (sufficient for both pre-fix + post-fix
    shapes).
    """
    text = resource.get("type", {}).get("text", "") or ""
    if text:
        return str(text)
    return _first_display_from_type(resource)


@pytest.mark.integration
def test_jp_composition_type_display_in_ja() -> None:
    """JP cohort: Composition.type.coding[0].display must contain Japanese characters.

    LOINC 34117-2 → "入院時記録" / LOINC 18842-5 → "退院時サマリー" (from loinc.yaml ja field).
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        comps = load_ndjson(find_ndjson(out, "Composition.ndjson"))
        if not comps:
            pytest.skip("No Composition resources emitted for JP cohort n=200")
        non_jp: list[str] = []
        for comp in comps:
            comp_id = comp.get("id", "?")
            display = _first_display_from_type(comp)
            if display and not _has_jp_chars(display):
                non_jp.append(f"Composition/{comp_id} type.display not JP: {display!r}")
        assert not non_jp, f"{len(non_jp)} Composition resource(s) have non-JP type.display:\n" + "\n".join(non_jp[:5])


@pytest.mark.integration
def test_jp_document_reference_type_display_in_ja() -> None:
    """JP cohort: DocumentReference.type.coding[0].display must be Japanese.

    LOINC 11506-3 → "経過記録" (from loinc.yaml ja field).
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        drefs = load_ndjson(find_ndjson(out, "DocumentReference.ndjson"))
        if not drefs:
            pytest.skip("No DocumentReference resources emitted for JP cohort n=200")
        non_jp: list[str] = []
        for dr in drefs:
            dr_id = dr.get("id", "?")
            # Issue #360 G5 (2026-07-22): read JP from type.text (walker-safe
            # UI source of truth); coding[].display now carries EN LOINC
            # canonical.
            display = _text_or_first_display_from_type(dr)
            if display and not _has_jp_chars(display):
                non_jp.append(f"DocumentReference/{dr_id} type UI-label not JP: {display!r}")
        assert not non_jp, f"{len(non_jp)} DocumentReference resource(s) have non-JP type UI-label:\n" + "\n".join(
            non_jp[:5]
        )


@pytest.mark.integration
def test_jp_allergy_intolerance_display_in_ja() -> None:
    """JP cohort: AllergyIntolerance.code.coding[0].display must be Japanese.

    AllergyIntolerance from the Task 9 builder (id prefix 'allergy-{pid}-{idx}'):
    SNOMED code → resolved via code_lookup("snomed-ct", code, "ja").
    Example: SNOMED 387207008 (Penicillin) → "ペニシリン".

    Session 57 Chain G: SNOMED is an English-only CodeSystem for HAPI
    Validator purposes, so the JA label now lives in ``code.text`` instead
    of being re-injected onto ``code.coding[].display``. The invariant this
    test guards is that JP output carries a Japanese human-readable label
    for the code — check the CodeableConcept as a whole (text OR any
    coding.display), so either surface satisfies the JP-locale contract.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        allergies = load_ndjson(find_ndjson(out, "AllergyIntolerance.ndjson"))
        if not allergies:
            pytest.skip("No AllergyIntolerance resources emitted for JP cohort n=200")

        # Filter to Task 9 builder entries (have allergen_code → SNOMED coding)
        task9_allergies = [a for a in allergies if a.get("code", {}).get("coding")]
        if not task9_allergies:
            pytest.skip(
                "No Task 9 AllergyIntolerance (SNOMED-coded) resources in JP cohort n=200 — "
                "allergy prevalence is 15%; small cohort may have no allergic patients."
            )

        non_jp: list[str] = []
        for ai in task9_allergies:
            ai_id = ai.get("id", "?")
            code = ai.get("code", {})
            text = code.get("text", "") or ""
            coding_displays = [c.get("display", "") or "" for c in code.get("coding", [])]
            has_jp = _has_jp_chars(text) or any(_has_jp_chars(d) for d in coding_displays)
            if not has_jp:
                non_jp.append(
                    f"AllergyIntolerance/{ai_id} neither code.text nor code.coding[].display "
                    f"carries JP characters (text={text!r}, coding_displays={coding_displays!r})"
                )

        assert not non_jp, f"{len(non_jp)} AllergyIntolerance resource(s) have no JP label:\n" + "\n".join(non_jp[:5])


@pytest.mark.integration
def test_jp_composition_section_text_in_ja() -> None:
    """JP cohort: Japanese sections in Composition.section[].text.div contain JP chars.

    The template generator produces JP content in locale-aware sections
    (chief_complaint, hpi, allergies, social_history, physical_examination,
    assessment_and_plan) when target_lang='ja'.

    α-min-1 English-fallback sections (excluded from this check):
      - past_medical_history: ICD codes without JP display text in the template
      - medications_at_home: drug names remain in English (RxNorm integration incomplete)
      - discharge_medications: medication orders remain in English
    These sections are known to produce mixed/English content in α-min-1.
    Task 6 CLAUDE.md note: "en locale note: when a disease YAML field has only 'ja',
    the generator falls back to 'ja' text".  The inverse (fields without ja key) stays
    in English.  This is an α-min-1 limitation, not a bug.
    """
    # Sections known to be JP-capable in α-min-1
    _JP_SECTIONS = frozenset(
        {
            "chief_complaint",
            "hpi",
            "allergies",
            "social_history",
            "physical_examination",
            "assessment_and_plan",
            "admission_summary",
            "hospital_course",
            "discharge_diagnoses",
            "follow_up",
        }
    )

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        comps = load_ndjson(find_ndjson(out, "Composition.ndjson"))
        # Only check Composition resources that have JP-capable sections
        sectioned = [c for c in comps if any(sec.get("title") in _JP_SECTIONS for sec in c.get("section", []))]
        if not sectioned:
            pytest.skip("No Composition resources with JP-capable sections for JP cohort n=200")

        non_jp_sections: list[str] = []
        for comp in sectioned:
            comp_id = comp.get("id", "?")
            for sec in comp.get("section", []):
                title = sec.get("title", "")
                if title not in _JP_SECTIONS:
                    continue  # skip known English-fallback sections
                div = sec.get("text", {}).get("div", "")
                if div and not _has_jp_chars(div):
                    non_jp_sections.append(f"Composition/{comp_id} section title={title!r}: div not JP: {div[:80]!r}")
        assert not non_jp_sections, f"{len(non_jp_sections)} JP-capable section(s) with non-JP text.div:\n" + "\n".join(
            non_jp_sections[:5]
        )


@pytest.mark.integration
def test_jp_clinical_impression_structural_fields_present() -> None:
    """JP cohort: ClinicalImpression has required structural fields (ref integrity).

    Note: ClinicalImpression.description is "Day N clinical assessment" (English)
    in α-min-1 — JP text is deferred to β-JP-1 phase.  This test verifies that
    the JP cohort still emits structurally valid ClinicalImpression resources with
    correct subject and encounter references.

    Status assertion respects the ``snapshot-in-progress-clinical-impression-status``
    by-design pattern (see ``docs/audit-cycles/by-design-registry.md``):
    ``status = "completed"`` is the normal case, but ``"in-progress"`` is
    legitimate when the linked Encounter itself is snapshot-truncated
    (AD-32 snapshot semantics) — both are valid FHIR R4 EventStatus codes.
    The by-design signature requires that an in-progress CI links to an
    in-progress Encounter; any other status combination is a real defect.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        impressions = load_ndjson(find_ndjson(out, "ClinicalImpression.ndjson"))
        if not impressions:
            pytest.skip("No ClinicalImpression resources emitted for JP cohort n=200")
        encounters = load_ndjson(find_ndjson(out, "Encounter.ndjson"))
        encounter_status_by_id = {enc.get("id", ""): enc.get("status", "") for enc in encounters}
        for ci in impressions:
            ci_id = ci.get("id", "?")
            status = ci.get("status", "")
            assert status in ("completed", "in-progress"), (
                f"ClinicalImpression/{ci_id} unexpected status {status!r}; "
                "expected 'completed' or by-design 'in-progress' for snapshot-truncated Encounter"
            )
            enc_ref = ci.get("encounter", {}).get("reference", "")
            if status == "in-progress":
                # by-design signature: linked Encounter must also be in-progress
                assert enc_ref.startswith("Encounter/"), (
                    f"ClinicalImpression/{ci_id} in-progress but has no Encounter reference: {enc_ref!r}"
                )
                enc_id = enc_ref[len("Encounter/") :]
                enc_status = encounter_status_by_id.get(enc_id)
                assert enc_status == "in-progress", (
                    f"ClinicalImpression/{ci_id} status='in-progress' but "
                    f"linked Encounter/{enc_id} status={enc_status!r} (by-design "
                    "signature requires both to be in-progress; see "
                    "docs/audit-cycles/by-design-registry.md "
                    "snapshot-in-progress-clinical-impression-status)"
                )
            assert ci.get("subject", {}).get("reference", "").startswith("Patient/"), (
                f"ClinicalImpression/{ci_id} subject must start with 'Patient/'"
            )
