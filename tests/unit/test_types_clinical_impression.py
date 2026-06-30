"""Unit tests for ClinicalImpressionRecord(Tier 1 #3 α-min-1 PR1)."""

from __future__ import annotations

from datetime import date

from clinosim.types.clinical import ClinicalImpressionRecord


def test_clinical_impression_defaults():
    c = ClinicalImpressionRecord()
    assert c.impression_id == ""
    assert c.encounter_id == ""
    assert c.day_index == 0
    assert c.description == ""
    assert c.investigation_refs == []
    assert c.finding_refs == []
    assert c.prognosis == ""


def test_clinical_impression_full_payload():
    c = ClinicalImpressionRecord(
        impression_id="ci-enc1-3",
        encounter_id="enc1",
        date=date(2026, 7, 1),
        day_index=3,
        description="炎症マーカー低下、改善傾向",
        summary="CRP 5.2 → 1.8、WBC 11k → 8k、解熱、食欲改善",
        investigation_refs=["lab-enc1-CRP-3"],
        finding_refs=["cond-enc1-pneumonia-primary"],
        prognosis="改善見込み",
        practitioner_id="staff-doc-001",
    )
    assert c.day_index == 3
    assert c.investigation_refs[0] == "lab-enc1-CRP-3"
