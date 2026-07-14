"""Integration: JP cohort uses Japanese displays throughout the imaging chain.

Verifies:
- ImagingStudy.modality[0].display is Japanese (単純X線撮影 / コンピュータ断層撮影 etc.)
- Radiology DiagnosticReport.conclusion (impression_text_ja) is Japanese
- Radiology DiagnosticReport.text.div contains Japanese characters
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
def test_jp_imaging_study_modality_display_in_ja() -> None:
    """JP cohort: ImagingStudy.modality[0].display must be Japanese."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted for JP cohort n=200")
        non_stub = [s for s in studies if s.get("modality")]
        # Session 52 fix 3: stub-only studies (inference failed, session 48
        # case D) legitimately have no modality — scope the JP-display
        # assertion to non-stub studies, but require they exist at all.
        assert non_stub, "every ImagingStudy is a stub — inference coverage collapsed"
        for study in non_stub:
            mod_display = study["modality"][0].get("display", "")
            assert _has_jp_chars(mod_display), (
                f"ImagingStudy/{study['id']} modality display not Japanese: {mod_display!r}"
            )


@pytest.mark.integration
def test_jp_imaging_study_series_modality_in_ja() -> None:
    """JP cohort: ImagingStudy.series[].modality.display must be Japanese."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted for JP cohort n=200")
        for study in studies:
            for series in study.get("series", []):
                mod_display = series.get("modality", {}).get("display", "")
                assert _has_jp_chars(mod_display), (
                    f"ImagingStudy/{study['id']} series modality display not Japanese: "
                    f"{mod_display!r}"
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
            assert _has_jp_chars(conclusion), (
                f"DiagnosticReport/{dr['id']} conclusion not Japanese: {conclusion!r}"
            )


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
            assert _has_jp_chars(div), (
                f"DiagnosticReport/{dr['id']} text.div not Japanese: {div[:150]!r}"
            )


@pytest.mark.integration
def test_jp_imaging_sr_category_snomed_display_in_ja() -> None:
    """JP cohort: imaging ServiceRequest.category SNOMED 363679005 display is Japanese."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("JP", 200, 42, out)
        srs = load_ndjson(find_ndjson(out, "ServiceRequest.ndjson"))
        imaging_srs = [
            s for s in srs
            if any(
                c.get("code") == "363679005"
                for entry in s.get("category", [])
                for c in entry.get("coding", [])
            )
        ]
        if not imaging_srs:
            pytest.skip("No imaging SRs (363679005) emitted for JP cohort n=200")
        for sr in imaging_srs:
            snomed = next(
                (
                    c
                    for entry in sr.get("category", [])
                    for c in entry.get("coding", [])
                    if c.get("code") == "363679005"
                ),
                None,
            )
            assert snomed is not None, (
                f"SR/{sr['id']} SNOMED 363679005 not found in category"
            )
            display = snomed.get("display", "")
            assert _has_jp_chars(display), (
                f"SR/{sr['id']} SNOMED 363679005 display not Japanese: {display!r}"
            )
            break  # one sample is sufficient to verify localization
