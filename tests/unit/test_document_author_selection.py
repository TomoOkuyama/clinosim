"""AD-65 Bug B (Task 12): _pick_document_author dispatch tests.

Session 27 clinical-integrity review found 23,279 nursing docs (LOINC
34746-8 / 78390-2 / 34745-0) had author_practitioner_id set to the
attending physician instead of the assigned nurse. These tests pin the
_pick_document_author(spec, encounter) dispatch helper introduced to
fix that: nursing docs -> primary_nurse_id, physician docs -> attending,
with a warn-logged fallback when the nurse is missing.

NOTE: an early draft of this task (task-12-brief.md) used LOINC 34119-8
for nursing_discharge_summary. That code was verified-rejected during
Task 8 (clinosim/codes/data/loinc.yaml: "Nursing facility Initial
evaluation note" — SNF, not hospital); the correct code, matching
document_type_specs.yaml and clinosim/types/document.py, is 34745-0.
Using 34119-8 here would test a LOINC that never actually appears on a
ClinicalDocument, leaving nursing_discharge_summary author dispatch
silently unverified.
"""

import logging
from types import SimpleNamespace

import pytest

from clinosim.modules.document.engine import _pick_document_author


@pytest.mark.unit
def test_nursing_docs_use_nurse():
    for loinc in ("34746-8", "78390-2", "34745-0"):
        spec = SimpleNamespace(loinc_code=loinc)
        enc = SimpleNamespace(attending_physician_id="DR-1", primary_nurse_id="RN-2")
        assert _pick_document_author(spec, enc) == "RN-2"


@pytest.mark.unit
def test_physician_docs_use_attending():
    for loinc in ("34117-2", "11506-3", "18842-5"):
        spec = SimpleNamespace(loinc_code=loinc)
        enc = SimpleNamespace(attending_physician_id="DR-1", primary_nurse_id="RN-2")
        assert _pick_document_author(spec, enc) == "DR-1"


@pytest.mark.unit
def test_nurse_missing_falls_back_to_attending_with_warn(caplog):
    spec = SimpleNamespace(loinc_code="34746-8")
    enc = SimpleNamespace(attending_physician_id="DR-1", primary_nurse_id="")
    with caplog.at_level(logging.WARNING):
        result = _pick_document_author(spec, enc)
    assert result == "DR-1"
    assert any("primary_nurse_id" in rec.message.lower() or "fallback" in rec.message.lower() for rec in caplog.records)
