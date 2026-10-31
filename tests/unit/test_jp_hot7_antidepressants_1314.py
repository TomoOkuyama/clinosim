"""Issue #1314 — JP HOT7 / YJ code mapping for antidepressants.

Pre-fix, ``locale/jp/code_mapping_drug.yaml`` did not register 7-digit
class-representative YJ codes for Duloxetine / Venlafaxine / Mirtazapine
(all PMDA-approved) — FHIR MedicationRequest emit fell through to the
eCS ``nocoded`` slice with the ``標準コードなし`` placeholder text.
Fluoxetine is NOT PMDA-approved for Japan and should not appear on
JP samples at all.

The fix:
  * Registered ``1179052`` (Duloxetine), ``1179051`` (Mirtazapine),
    ``1179055`` (Venlafaxine — Effexor SR) in the JP drug catalog.
    Each code was cross-verified against ``JP_MedicationCodeYJ_CS_full
    .json`` (≥ 1 product-level entry).
  * Added ``locale_exclude: ["JP"]`` to the Fluoxetine entries in
    ``chronic_medications.yaml`` F32 / F33 so the sampler skips it
    for JP patients.
"""

from __future__ import annotations

from clinosim.codes.drugs import jp_drug_code
from clinosim.locale.loader import load_code_mapping


def test_jp_yj_registered_for_duloxetine():
    assert (jp_drug_code("Duloxetine", "PO") or "")[:7] == "1179052"  # a full YJ product (Issue #2347)


def test_jp_yj_registered_for_mirtazapine():
    assert (jp_drug_code("Mirtazapine", "PO") or "")[:7] == "1179051"  # a full YJ product (Issue #2347)


def test_jp_yj_registered_for_venlafaxine():
    assert (jp_drug_code("Venlafaxine", "PO") or "")[:7] == "1179055"  # a full YJ product (Issue #2347)


def test_jp_yj_not_registered_for_fluoxetine():
    # Fluoxetine is NOT PMDA-approved. The mapping should NOT register
    # a code for it (no fabricated coding — feedback_verify_code_before
    # _believing_stale_comment / feedback_cif_fhir_quality_focus).
    m = load_code_mapping("drug", "JP")
    assert "Fluoxetine" not in m


def test_all_registered_yj_codes_exist_in_the_full_master():
    # Guard against future edits that might fabricate a YJ code: every
    # registered code MUST be a product-level entry in
    # ``JP_MedicationCodeYJ_CS_full.json`` (full YJ codes since Issue #2347).
    import json
    from pathlib import Path

    master_path = (
        Path(__file__).resolve().parents[2]
        / "clinosim"
        / "codes"
        / "authoritative"
        / "JP_MedicationCodeYJ_CS_full.json"
    )
    master = json.load(master_path.open())
    all_master_codes: set[str] = {c.get("code", "") for c in (master.get("concept") or [])}

    # Only check the 5 antidepressants this PR touched to keep the
    # test tightly-scoped; a broader master-consistency sweep is a
    # separate follow-up.
    for drug in ("Duloxetine", "Mirtazapine", "Venlafaxine", "Fluvoxamine"):
        yj_class = jp_drug_code(drug, "PO")
        assert yj_class, f"{drug} has no JP code in the drug catalog"
        assert yj_class in all_master_codes, f"{drug} code {yj_class} is not in the master"
