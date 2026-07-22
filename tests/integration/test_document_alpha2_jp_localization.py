"""Integration: JP cohort uses Japanese displays for α-min-2 document chain resources.

Verifies:
- Composition.type.coding[0].display is Japanese for α-min-2 nursing types:
    LOINC 78390-2 → "入院時看護アセスメント" / LOINC 34745-0 → "退院時看護サマリ"
- DocumentReference.type.coding[0].display is Japanese for NURSING_SHIFT_NOTE:
    LOINC 34746-8 → "看護経過記録"
- CareTeam.category[0].text uses Japanese or mixed Japanese-English:
    SNOMED 424535000 'Clinical team' — display depends on locale config
    (EN fallback acceptable if no JP code exists; test verifies structure not language)
- CareTeam.subject and encounter refs are structurally valid for JP cohort

Note on CareTeam localization:
  CareTeam.category uses SNOMED 424535000 'Clinical team'. There is no standard
  Japanese display for this SNOMED code in the current loinc.yaml/snomed.yaml.
  The builder uses the EN display 'Clinical team' for both US and JP cohorts in α-min-2.
  JP localization of CareTeam.category.text is deferred to β-JP-1 per spec §4.
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


def _first_display_from_type(resource: dict) -> str:
    return next(
        (c.get("display", "") for c in resource.get("type", {}).get("coding", [])),
        "",
    )


def _text_or_first_display_from_type(resource: dict) -> str:
    """Return the JP-UI-visible label for ``resource.type``.

    Issue #360 G5 (2026-07-22): DocumentReference.type now emits EN LOINC
    canonical on ``coding[].display`` (walker-safe on the English-only
    LOINC CS) + JP on ``text`` (JP UI's source of truth). This helper
    prefers ``type.text`` when populated, else falls back to
    ``coding[0].display`` — sufficient for both the pre-fix (JP on
    coding.display) and post-fix (JP on text) shapes, so downstream
    integration assertions read as "the JP label" rather than "the
    coding.display slot".
    """
    text = resource.get("type", {}).get("text", "") or ""
    if text:
        return str(text)
    return _first_display_from_type(resource)


def _loinc_code_from_type(resource: dict) -> str:
    return next(
        (c.get("code", "") for c in resource.get("type", {}).get("coding", [])),
        "",
    )


_LOINC_NURSING_SHIFT_NOTE = "34746-8"
_LOINC_ADMISSION_NURSING_ASSESSMENT = "78390-2"
_LOINC_NURSING_DISCHARGE_SUMMARY = "34745-0"


@pytest.mark.integration
def test_jp_nursing_composition_type_display_in_ja() -> None:
    """JP cohort: ADMISSION_NURSING_ASSESSMENT Composition.type.coding[0].display must be JP.

    LOINC 78390-2 → display_ja="入院時看護アセスメント" (from document_type_specs.yaml).
    Also checks NURSING_DISCHARGE_SUMMARY LOINC 34745-0 → "退院時看護サマリ".
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        comps = load_ndjson(find_ndjson(out, "Composition.ndjson"))
        if not comps:
            pytest.skip("No Composition resources emitted for JP cohort n=200")

        # Filter to α-min-2 nursing composition types
        nursing_loincs = {_LOINC_ADMISSION_NURSING_ASSESSMENT, _LOINC_NURSING_DISCHARGE_SUMMARY}
        nursing_comps = [c for c in comps if _loinc_code_from_type(c) in nursing_loincs]
        if not nursing_comps:
            pytest.skip(
                "No ADMISSION_NURSING_ASSESSMENT or NURSING_DISCHARGE_SUMMARY Compositions "
                "in JP cohort n=200 — nursing enricher may not be firing for JP inpatient encounters"
            )

        non_jp: list[str] = []
        for comp in nursing_comps:
            comp_id = comp.get("id", "?")
            display = _first_display_from_type(comp)
            if display and not _has_jp_chars(display):
                non_jp.append(
                    f"Composition/{comp_id} (LOINC {_loinc_code_from_type(comp)}) type.display not JP: {display!r}"
                )
        assert not non_jp, f"{len(non_jp)} nursing Composition resource(s) have non-JP type.display:\n" + "\n".join(
            non_jp[:5]
        )


@pytest.mark.integration
def test_jp_nursing_shift_note_type_display_in_ja() -> None:
    """JP cohort: NURSING_SHIFT_NOTE DocumentReference.type.coding[0].display must be JP.

    LOINC 34746-8 → display_ja="看護経過記録" (from document_type_specs.yaml).
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        drefs = load_ndjson(find_ndjson(out, "DocumentReference.ndjson"))
        if not drefs:
            pytest.skip("No DocumentReference resources emitted for JP cohort n=200")

        nursing_shift_drefs = [d for d in drefs if _loinc_code_from_type(d) == _LOINC_NURSING_SHIFT_NOTE]
        if not nursing_shift_drefs:
            pytest.skip(
                "No NURSING_SHIFT_NOTE DocumentReferences (LOINC 34746-8) "
                "in JP cohort n=200 — nursing enricher not firing for JP inpatient"
            )

        non_jp: list[str] = []
        for dr in nursing_shift_drefs:
            dr_id = dr.get("id", "?")
            # Issue #360 G5 (2026-07-22): read JP from type.text (walker-safe
            # UI source of truth); coding[].display carries EN LOINC canonical
            # (walker-safe on English-only CS) so pre-fix "display must be JP"
            # assertion no longer holds on coding[].display.
            display = _text_or_first_display_from_type(dr)
            if display and not _has_jp_chars(display):
                non_jp.append(f"DocumentReference/{dr_id} type UI-label not JP: {display!r}")
        assert not non_jp, (
            f"{len(non_jp)} NURSING_SHIFT_NOTE DocumentReference resource(s) "
            "have non-JP type.display:\n" + "\n".join(non_jp[:5])
        )


@pytest.mark.integration
def test_jp_care_team_structural_fields_present() -> None:
    """JP cohort: CareTeam has required structural fields (ref integrity).

    Note: CareTeam.category.text is 'Clinical team' (English) in α-min-2 —
    JP localization of CareTeam category text is deferred to β-JP-1 phase.
    This test verifies that the JP cohort emits structurally valid CareTeam
    resources with correct subject and encounter references.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        care_teams = load_ndjson(find_ndjson(out, "CareTeam.ndjson"))
        if not care_teams:
            pytest.skip("No CareTeam resources emitted for JP cohort n=200")
        for ct in care_teams:
            ct_id = ct.get("id", "?")
            assert ct.get("status"), f"CareTeam/{ct_id} missing status"
            assert ct.get("subject", {}).get("reference", "").startswith("Patient/"), (
                f"CareTeam/{ct_id} subject must start with 'Patient/'"
            )
            assert ct.get("encounter", {}).get("reference", "").startswith("Encounter/"), (
                f"CareTeam/{ct_id} encounter must start with 'Encounter/'"
            )


@pytest.mark.integration
def test_jp_care_team_count_matches_encounter_count() -> None:
    """JP cohort: CareTeam count must equal Encounter count (1:1 invariant).

    Verifies the 1:1 invariant holds for the JP cohort (16,046 CareTeams for
    JP p=5k baseline). Regression guard: JP localization paths must not
    filter out any CareTeam resources.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        care_teams = load_ndjson(find_ndjson(out, "CareTeam.ndjson"))
        encounters = load_ndjson(find_ndjson(out, "Encounter.ndjson"))
        assert care_teams, "CareTeam.ndjson empty for JP cohort — silent-no-op in JP path"
        # CY7-05 (structural, 2026-07-11): FHIR-emit-only synthetic ED
        # encounters (id ends with "-ED", used for Encounter.partOf ED→IMP
        # linkage) don't have CareTeam records because they don't exist in
        # CIF. Exclude them from the 1:1 count assertion.
        real_encounter_count = sum(1 for e in encounters if not e.get("id", "").endswith("-ED"))
        assert len(care_teams) == real_encounter_count, (
            f"JP CareTeam count {len(care_teams)} != real Encounter count "
            f"{real_encounter_count} (total encounters incl. synth ED: "
            f"{len(encounters)}) — CareTeam 1:1-with-Encounter invariant "
            "violated for JP cohort. Check if JP locale gating in "
            "_fhir_care_team.py is filtering encounters."
        )


@pytest.mark.integration
def test_jp_nursing_composition_section_text() -> None:
    """JP cohort: ADMISSION_NURSING_ASSESSMENT Composition sections must be non-empty.

    α-min-2 nursing Composition sections (nursing_history, adl_assessment,
    risk_assessments, nursing_diagnosis, care_plan) are generated by the
    template generator. For JP cohort, sections should contain either JP text
    or EN fallback (template content is English-first in α-min-2; JP section
    text is deferred to β-JP-1 phase per spec §5.3.2).

    This test verifies that section content is non-empty (not silently dropped),
    not that all content is JP (language deferred to β-JP-1).
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        comps = load_ndjson(find_ndjson(out, "Composition.ndjson"))
        if not comps:
            pytest.skip("No Composition resources emitted for JP cohort n=200")

        nursing_comps = [c for c in comps if _loinc_code_from_type(c) == _LOINC_ADMISSION_NURSING_ASSESSMENT]
        if not nursing_comps:
            pytest.skip(
                "No ADMISSION_NURSING_ASSESSMENT Compositions in JP cohort n=200 — "
                "nursing enricher may not be firing for JP inpatient encounters"
            )

        empty_sections: list[str] = []
        for comp in nursing_comps[:10]:  # Sample first 10 for speed
            comp_id = comp.get("id", "?")
            sections = comp.get("section", [])
            if not sections:
                empty_sections.append(f"Composition/{comp_id}: no section[] at all")
                continue
            for sec in sections:
                title = sec.get("title", "?")
                div = sec.get("text", {}).get("div", "")
                if not div or div.strip() == "<div></div>":
                    empty_sections.append(f"Composition/{comp_id} section {title!r}: empty div")

        assert not empty_sections, (
            f"{len(empty_sections)} empty section(s) in ADMISSION_NURSING_ASSESSMENT "
            f"Composition (JP cohort):\n" + "\n".join(empty_sections[:5])
        )
