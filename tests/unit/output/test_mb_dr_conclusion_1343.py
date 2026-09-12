"""Issue #1343 — Microbiology DiagnosticReport.conclusion field must be
populated with a human-readable summary of the culture outcome.

Prior state: MB DR emitted ``conclusionCode`` (SNOMED Normal/Abnormal) and
``presentedForm`` (multi-line text attachment), but ``conclusion`` (the FHIR
canonical single-line summary field, 0..1) was blank. A downstream reader
scanning ``DiagnosticReport.conclusion`` on the MB DR saw nothing.

Fix populates ``conclusion`` from a new ``_mb_conclusion_text`` helper. The
tests here pin the four canonical branches: negative culture, positive with
sensitivities, positive without sensitivities (pending), and organism
identification pending after positive growth.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.labs.microbiology import _mb_conclusion_text


def test_negative_culture_conclusion_en():
    mb = {"growth": False, "organism_snomed": ""}
    txt = _mb_conclusion_text(mb, "en")
    assert "No growth" in txt
    assert "5-day" in txt


def test_negative_culture_conclusion_ja():
    mb = {"growth": False, "organism_snomed": ""}
    txt = _mb_conclusion_text(mb, "ja")
    assert "培養" in txt
    assert "発育なし" in txt


def test_positive_culture_with_sensitivities_en():
    # S. pneumoniae SNOMED 9861002; PEN/CTX/VAN sensitivity panel.
    mb = {
        "growth": True,
        "organism_snomed": "9861002",
        "susceptibilities": [
            {"antibiotic_display": "PEN", "interpretation": "S"},
            {"antibiotic_display": "CTX", "interpretation": "S"},
            {"antibiotic_display": "VAN", "interpretation": "S"},
        ],
    }
    txt = _mb_conclusion_text(mb, "en")
    # The organism display comes from code_lookup — in the absence of a
    # SNOMED display for the exact code we still see "isolated" and the
    # sensitivity panel.
    assert "isolated" in txt
    assert "PEN=S" in txt
    assert "CTX=S" in txt


def test_positive_culture_with_sensitivities_ja():
    mb = {
        "growth": True,
        "organism_snomed": "9861002",
        "susceptibilities": [
            {"antibiotic_display": "PEN", "interpretation": "S"},
            {"antibiotic_display": "CTX", "interpretation": "S"},
        ],
    }
    txt = _mb_conclusion_text(mb, "ja")
    assert "分離" in txt
    assert "PEN=S" in txt


def test_positive_culture_no_sensitivities_pending_en():
    mb = {"growth": True, "organism_snomed": "9861002", "susceptibilities": []}
    txt = _mb_conclusion_text(mb, "en")
    assert "isolated" in txt
    assert "pending" in txt


def test_positive_culture_no_organism_pending_en():
    mb = {"growth": True, "organism_snomed": "", "susceptibilities": []}
    txt = _mb_conclusion_text(mb, "en")
    assert "positive" in txt.lower()
    assert "pending" in txt


def test_positive_culture_no_organism_pending_ja():
    mb = {"growth": True, "organism_snomed": "", "susceptibilities": []}
    txt = _mb_conclusion_text(mb, "ja")
    assert "陽性" in txt
    assert "同定中" in txt


def test_more_than_four_sensitivities_truncated_with_ellipsis():
    mb = {
        "growth": True,
        "organism_snomed": "9861002",
        "susceptibilities": [{"antibiotic_display": f"AB{i}", "interpretation": "S"} for i in range(6)],
    }
    txt = _mb_conclusion_text(mb, "en")
    assert "…" in txt
    # First four included; last two not.
    assert "AB0=S" in txt and "AB3=S" in txt
    assert "AB5=S" not in txt


def test_growth_off_but_organism_labeled_contaminant_en():
    # A defensive path: growth=False but organism_snomed present →
    # classified as contaminant so the reader isn't misled by an
    # organism display without clinical significance.
    mb = {"growth": False, "organism_snomed": "9861002"}
    txt = _mb_conclusion_text(mb, "en")
    assert "not clinically significant" in txt
    assert "contaminant" in txt.lower()
