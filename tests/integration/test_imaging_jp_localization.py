"""Integration: JP cohort keeps the Japanese labels reachable across the imaging chain.

Contract after P2 A (iris4h-ai feedback V4/V5): the JP-only post-emit
walker `_strip_japanese_display_on_english_only_systems` drops the
Japanese `display` from Coding entries on standard English-only
CodeSystems (LOINC / SNOMED / HL7 terminology / DICOM / UCUM / HL7 FHIR
sid) because HAPI Validator rejects them as "Wrong Display Name".

The Japanese human-readable label MUST still be reachable through
FHIR-legal siblings:
- CodeableConcept-wrapped coding: label survives in the enclosing
  `text` field (populated by builders for JP output).
- Bare Coding-typed fields (e.g. `ImagingStudy.series[].modality`):
  no `text` sibling is available under FHIR R4, so `display` legitimately
  stays absent — this is the accepted feedback Option 1 tradeoff.

Radiology narrative (DiagnosticReport.conclusion / text.div) is
locale-neutral to the walker and continues to carry Japanese text.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate


def _has_jp_chars(s: str) -> bool:
    """Return True if *s* contains any CJK / Hiragana / Katakana character."""
    return any(
        "　" <= c <= "鿿"  # CJK Unified Ideographs + Hiragana/Katakana
        or "゠" <= c <= "ヿ"  # Katakana
        or "぀" <= c <= "ゟ"  # Hiragana
        for c in s
    )


@pytest.mark.integration
def test_jp_imaging_study_modality_dcm_display_absent() -> None:
    """JP cohort: `ImagingStudy.modality[0]` on the DICOM CodeSystem carries
    system + code but must NOT carry a Japanese `display` (bare Coding — no
    `text` sibling available under FHIR R4, feedback Option 1 tradeoff).
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted for JP cohort n=200")
        non_stub = [s for s in studies if s.get("modality")]
        # Session 52 fix 3: stub-only studies (inference failed, session 48
        # case D) legitimately have no modality — scope the assertion to
        # non-stub studies, but require they exist at all.
        assert non_stub, "every ImagingStudy is a stub — inference coverage collapsed"
        for study in non_stub:
            mod = study["modality"][0]
            assert mod.get("system") == "http://dicom.nema.org/resources/ontology/DCM"
            assert mod.get("code"), f"ImagingStudy/{study['id']} modality missing code"
            display = mod.get("display", "")
            assert not _has_jp_chars(display), (
                f"ImagingStudy/{study['id']} modality display leaked Japanese "
                f"under DICOM system: {display!r} — P2 A walker should strip it"
            )


@pytest.mark.integration
def test_jp_imaging_study_series_modality_dcm_display_absent() -> None:
    """JP cohort: `ImagingStudy.series[].modality` on the DICOM CodeSystem
    must NOT carry a Japanese `display` (same rationale as
    `test_jp_imaging_study_modality_dcm_display_absent`)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted for JP cohort n=200")
        for study in studies:
            for series in study.get("series", []):
                mod = series.get("modality", {})
                if mod.get("system") != "http://dicom.nema.org/resources/ontology/DCM":
                    continue
                display = mod.get("display", "")
                assert not _has_jp_chars(display), (
                    f"ImagingStudy/{study['id']} series modality display leaked "
                    f"Japanese under DICOM system: {display!r}"
                )


@pytest.mark.integration
def test_jp_radiology_dr_conclusion_in_ja() -> None:
    """JP cohort: radiology DiagnosticReport.conclusion must be Japanese."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        drs = load_ndjson(find_ndjson(out, "DiagnosticReport.ndjson"))
        rad_drs = [r for r in drs if r.get("id", "").startswith("imgrpt-")]
        if not rad_drs:
            pytest.skip("No radiology DiagnosticReport resources emitted for JP cohort")
        for dr in rad_drs:
            conclusion = dr.get("conclusion", "")
            assert conclusion, f"DiagnosticReport/{dr['id']} missing conclusion"
            assert _has_jp_chars(conclusion), f"DiagnosticReport/{dr['id']} conclusion not Japanese: {conclusion!r}"


@pytest.mark.integration
def test_jp_radiology_dr_text_div_in_ja() -> None:
    """JP cohort: radiology DiagnosticReport.text.div must contain Japanese characters."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        drs = load_ndjson(find_ndjson(out, "DiagnosticReport.ndjson"))
        rad_drs = [r for r in drs if r.get("id", "").startswith("imgrpt-")]
        if not rad_drs:
            pytest.skip("No radiology DiagnosticReport resources emitted for JP cohort")
        for dr in rad_drs:
            div = dr.get("text", {}).get("div", "")
            assert div, f"DiagnosticReport/{dr['id']} missing text.div"
            assert _has_jp_chars(div), f"DiagnosticReport/{dr['id']} text.div not Japanese: {div[:150]!r}"


@pytest.mark.integration
def test_jp_imaging_sr_category_ja_label_via_text() -> None:
    """JP cohort: imaging ServiceRequest.category SNOMED 363679005 keeps its
    Japanese label — post-P2 A the `display` on the SNOMED coding is stripped
    (HAPI Validator "Wrong Display Name" rejection) and the label survives in
    the enclosing CodeableConcept's `text` field.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        srs = load_ndjson(find_ndjson(out, "ServiceRequest.ndjson"))
        imaging_srs = [
            s
            for s in srs
            if any(c.get("code") == "363679005" for entry in s.get("category", []) for c in entry.get("coding", []))
        ]
        if not imaging_srs:
            pytest.skip("No imaging SRs (363679005) emitted for JP cohort n=200")
        for sr in imaging_srs:
            entry = next(
                (e for e in sr.get("category", []) if any(c.get("code") == "363679005" for c in e.get("coding", []))),
                None,
            )
            assert entry is not None, f"SR/{sr['id']} SNOMED 363679005 category entry not found"
            snomed = next(c for c in entry["coding"] if c.get("code") == "363679005")
            # SNOMED coding: system + code present, Japanese display stripped.
            assert snomed.get("system") == "http://snomed.info/sct"
            assert not _has_jp_chars(snomed.get("display", "")), (
                f"SR/{sr['id']} SNOMED 363679005 display leaked Japanese: {snomed.get('display')!r}"
            )
            # `text` on the CodeableConcept preserves the localized label.
            assert _has_jp_chars(entry.get("text", "")), (
                f"SR/{sr['id']} category text missing Japanese label: {entry.get('text')!r}"
            )
            break  # one sample is sufficient to verify localization
