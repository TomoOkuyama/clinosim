"""Issue #1335 (META #1392 Cluster A part 3) — acute-illness medication holds.

``medication_pipeline`` reads each disease YAML's ``medication_holds`` block
and suppresses chronic home-med continuation orders for drugs it names. Prior
to Issue #1335 the AKI YAML held Metformin + NSAIDs only (not ACE-I / ARB —
the KDIGO-recommended hold list), and the cerebral_infarction YAML declared
no holds at all (no aspiration-risk PO bisphosphonate hold).

This suite verifies the newly added YAML holds land as declared:
- AKI (``acute_kidney_injury``): Metformin + NSAIDs + ACE-I + ARB families
- Acute stroke (``cerebral_infarction``): PO bisphosphonates
"""

from __future__ import annotations

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol


@pytest.mark.parametrize(
    "drug",
    [
        "Metformin",
        "Celecoxib",
        "Ibuprofen",
        "Naproxen",
        "Diclofenac",
        "Loxoprofen",
        "Enalapril",
        "Lisinopril",
        "Captopril",
        "Ramipril",
        "Losartan",
        "Valsartan",
        "Candesartan",
        "Olmesartan",
        "Telmisartan",
    ],
)
def test_aki_holds_include_drug(drug: str):
    """Every drug listed here must appear in some AKI ``medication_holds``
    entry's ``drugs`` list. Regression against silent list-shrinkage."""
    aki = load_disease_protocol("acute_kidney_injury")
    all_held = {d for hold in aki.medication_holds for d in hold.get("drugs", [])}
    assert drug in all_held, f"{drug} missing from AKI medication_holds; got {sorted(all_held)}"


@pytest.mark.parametrize(
    "drug",
    ["Alendronate", "Risedronate", "Ibandronate", "Minodronate"],
)
def test_cerebral_infarction_holds_include_po_bisphosphonate(drug: str):
    """Every PO bisphosphonate must be held on acute stroke admissions
    (dysphagia / NG-tube aspiration risk)."""
    ci = load_disease_protocol("cerebral_infarction")
    all_held = {d for hold in ci.medication_holds for d in hold.get("drugs", [])}
    assert drug in all_held, f"{drug} missing from cerebral_infarction medication_holds; got {sorted(all_held)}"


def test_aki_amlodipine_not_held():
    """Regression: DHP-CCB Amlodipine is SAFE in AKI (no efferent-tone
    mechanism), must NOT be in the hold list. Guards against
    overly-aggressive future edits."""
    aki = load_disease_protocol("acute_kidney_injury")
    all_held = {d for hold in aki.medication_holds for d in hold.get("drugs", [])}
    assert "Amlodipine" not in all_held, "Amlodipine is safe in AKI — must not be in medication_holds"


def test_cerebral_infarction_amlodipine_not_held():
    """Regression: acute stroke does not contraindicate Amlodipine."""
    ci = load_disease_protocol("cerebral_infarction")
    all_held = {d for hold in ci.medication_holds for d in hold.get("drugs", [])}
    assert "Amlodipine" not in all_held
