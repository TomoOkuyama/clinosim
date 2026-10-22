"""F10 (alcohol UD) + C16 (gastric cancer) chronic medication entries (Issue #1701).

Pre-fix: both ICD codes stored in chronic_conditions but no entries in
chronic_medications.yaml, so diagnosed patients emitted zero home
medications over a 5y sim window.

#1804 Phase 2.a: entries now carry ``drug_id`` instead of ``drug`` /
``drug_ja`` where a catalog mapping exists; this test resolves by
drug_id first and falls back to the legacy ``drug`` field for entries
not yet migrated (Tegafur-Gimeracil-Oteracil combo).
"""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import get_drug
from clinosim.locale.loader import load_chronic_medications


def _entry_drug_name(entry: dict) -> str:
    """Resolve the display drug name for a chronic_medications entry,
    whether it carries the new ``drug_id`` or the legacy ``drug`` field."""
    drug_id = entry.get("drug_id") or ""
    if drug_id:
        rec = get_drug(str(drug_id))
        if rec is not None:
            return rec.names.get("en", "") or drug_id
    return str(entry.get("drug") or "")


@pytest.mark.unit
def test_f10_alcohol_use_disorder_has_mat_medications():
    data = load_chronic_medications()
    assert "F10" in data, "F10 (alcohol use disorder) must have chronic_medications entry"
    drugs = {_entry_drug_name(m) for m in data["F10"]["medications"]}
    assert "Naltrexone" in drugs, "SAMHSA first-line MAT absent"
    assert "Acamprosate" in drugs
    assert "Disulfiram" in drugs
    # Probabilities sum to roughly US MAT penetration (10-20 % per SAMHSA N-SSATS)
    probs = [float(m["probability"]) for m in data["F10"]["medications"]]
    assert 0.10 < sum(probs) < 0.35, f"MAT penetration out of SAMHSA band: Σp={sum(probs):.2f}"


@pytest.mark.unit
def test_c16_gastric_cancer_has_oral_fluoropyrimidine():
    data = load_chronic_medications()
    assert "C16" in data, "C16 (gastric cancer) must have chronic_medications entry"
    meds = data["C16"]["medications"]
    drugs = {_entry_drug_name(m) for m in meds}
    assert "Capecitabine" in drugs
    assert "Tegafur-Gimeracil-Oteracil" in drugs  # S-1, JP-first-line (legacy — no RxCUI)
    # Both tagged fluoropyrimidine for the active-regimen mutex guard
    assert all(m.get("drug_class") == "fluoropyrimidine" for m in meds)
    # Locale-exclusive: Capecitabine → not JP; S-1 → not US
    cape = next(m for m in meds if _entry_drug_name(m) == "Capecitabine")
    ts1 = next(m for m in meds if _entry_drug_name(m) == "Tegafur-Gimeracil-Oteracil")
    assert "JP" in cape["locale_exclude"]
    assert "US" in ts1["locale_exclude"]
