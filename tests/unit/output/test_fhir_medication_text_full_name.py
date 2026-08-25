"""Tests for full-name JA localization of ``medicationCodeableConcept.text`` (Issue #852).

Prior emit used the code-lookup-optimized ``base_name`` (first
whitespace token when no code_mapping match) as the source for
``.text`` localization. Multi-word product-family names whose only JA
mapping key is the FULL form (``Cefcapene pivoxil``,
``Magnesium sulfate``, ``Regular insulin``, ``ICS/LABA inhaler``,
``Lactated Ringer``, ``Hypertonic Saline``, …) never resolved — the
first-token truncation dropped the qualifier and the resulting single
word was not in the JA dict. Result: 8,283 (2.3 %) MedicationAdministration
+ 1,113 (1.0 %) MedicationRequest resources shipped a Latin ``.text``
while ``coding[0].display`` on the same resource was already in JA.

Fix: localize ``drug_name_clean`` (the pre-truncation cleaned name)
rather than ``base_name``. ``base_name`` is still used for
``drug_codes`` lookup; only the ``.text`` value now carries the full
localized form.
"""

from __future__ import annotations

from clinosim.locale.loader import load_drug_names_ja
from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

# --- localizer resolves the multi-word product-family names ---


def test_localize_multi_word_drug_names_hit_ja_dict():
    """The 11 product-family names Issue #852 identified all resolve to JA."""
    cases = [
        ("Cefcapene pivoxil", "セフカペンピボキシル"),
        ("Cefditoren pivoxil", "セフジトレンピボキシル"),
        ("Magnesium sulfate", "硫酸マグネシウム"),
        ("Normal saline", "生理食塩液"),
        ("Potassium chloride", "塩化カリウム"),
        ("Regular insulin", "レギュラーインスリン"),
        ("Lactated Ringer", "乳酸リンゲル液"),
        ("Hypertonic Saline", "高張食塩液"),
        ("Unfractionated Heparin", "未分画ヘパリン"),
        ("Calcium/Vitamin D", "カルシウム/ビタミンD"),
        ("ICS/LABA inhaler", "吸入ステロイド／β2刺激薬配合吸入剤"),
    ]
    for en, expected_ja in cases:
        result = _localize_drug_name(en, "JP")
        assert result == expected_ja, f"{en!r}: got {result!r}"


def test_localize_ics_laba_short_form():
    """`ICS/LABA` (short form, appears in narrative text) also resolves."""
    assert _localize_drug_name("ICS/LABA", "JP") == "吸入ステロイド／β2刺激薬配合"


def test_localize_us_passes_through():
    """US output must not localize."""
    for en in ("Cefcapene pivoxil", "Magnesium sulfate", "Regular insulin"):
        assert _localize_drug_name(en, "US") == en


# --- drug_names_ja.yaml integrity ---


def test_drug_names_ja_contains_ics_laba_entries():
    ja_dict = load_drug_names_ja()
    assert "ics/laba inhaler" in ja_dict
    assert "ics/laba" in ja_dict


def test_drug_names_ja_contains_all_issue_852_full_forms():
    """Every drug the Issue #852 sweep flagged has a full-form JA entry."""
    ja_dict = load_drug_names_ja()
    for full_name in (
        "cefcapene pivoxil",
        "cefditoren pivoxil",
        "magnesium sulfate",
        "normal saline",
        "potassium chloride",
        "regular insulin",
        "lactated ringer",
        "hypertonic saline",
        "unfractionated heparin",
        "calcium/vitamin d",
        "ics/laba inhaler",
    ):
        assert full_name in ja_dict, f"missing JA entry for {full_name!r}"


# --- integrated MR + MAR emit paths use the full name ---


def _build_mr(drug_name: str) -> dict:
    """Minimal fixture invoking the MR builder path via _resolve_medication_concept."""
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept

    concept, _rate_note = _resolve_medication_concept(drug_name, order_code="", country="JP")
    return concept


def test_mr_medicationCodeableConcept_text_is_full_ja_name_cefcapene():
    """`Cefcapene pivoxil` in Order.display_name → `.text = セフカペンピボキシル`
    (not truncated to `Cefcapene`)."""
    concept = _build_mr("Cefcapene pivoxil")
    assert concept["text"] == "セフカペンピボキシル"


def test_mr_medicationCodeableConcept_text_is_full_ja_name_magnesium():
    concept = _build_mr("Magnesium sulfate")
    assert concept["text"] == "硫酸マグネシウム"


def test_mr_medicationCodeableConcept_text_is_full_ja_name_normal_saline():
    concept = _build_mr("Normal saline")
    assert concept["text"] == "生理食塩液"


def test_mr_medicationCodeableConcept_text_is_full_ja_name_ics_laba():
    concept = _build_mr("ICS/LABA inhaler")
    assert concept["text"] == "吸入ステロイド／β2刺激薬配合吸入剤"


def test_mr_medicationCodeableConcept_text_us_passes_through():
    """US output preserves the English name unchanged."""
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept

    concept, _ = _resolve_medication_concept("Cefcapene pivoxil", order_code="", country="US")
    assert concept["text"] == "Cefcapene pivoxil"


# --- regression: Issue #852 fix must fire even when Order.order_code is pre-set ---
#
# Prior to this regression pass, the JA multi-word extension was nested
# inside ``if not code_value and drug_name_clean:``; when disease YAMLs
# supplied ``Order.order_code`` up front (Magnesium Sulfate = MHLW HOT7
# 2355002, Normal saline / Regular insulin / Potassium chloride /
# Lactated Ringer / Hypertonic Saline / Unfractionated Heparin similarly
# pre-coded), the outer block was skipped and the extension never ran —
# ``.text`` fell back to the first whitespace token (``Magnesium`` /
# ``Regular`` / …) even though the JA dict had a multi-word entry.
# JP p=10000 s500 sample: 6,327 records (165 MR + 6,162 MA) leaked.


def test_mr_text_with_preset_order_code_full_display_magnesium():
    """Order.display_name='Magnesium Sulfate 2g IV over 20min' + order_code='2355002'
    → .text='硫酸マグネシウム' (not 'Magnesium').

    Reproduces the JP p=10000 s500 regression the fix targets: disease-YAML-supplied
    MHLW HOT7 code makes code_value truthy up front; the JA multi-word extension
    must run regardless.
    """
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept

    concept, _ = _resolve_medication_concept("Magnesium Sulfate 2g IV over 20min", order_code="2355002", country="JP")
    assert concept["text"] == "硫酸マグネシウム", f"got {concept['text']!r}"


def test_mr_text_with_preset_order_code_normal_saline():
    """Normal saline with pre-set order_code must still localize."""
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept

    concept, _ = _resolve_medication_concept("Normal saline 500mL IV", order_code="3319400A2039", country="JP")
    assert concept["text"] == "生理食塩液"


def test_mr_text_with_preset_order_code_regular_insulin():
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept

    concept, _ = _resolve_medication_concept("Regular insulin sliding scale", order_code="2492400A", country="JP")
    assert concept["text"] == "レギュラーインスリン"


def test_mr_text_with_preset_order_code_unfractionated_heparin():
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept

    concept, _ = _resolve_medication_concept(
        "Unfractionated Heparin 5000IU IV bolus", order_code="3334401A", country="JP"
    )
    assert concept["text"] == "未分画ヘパリン"


def test_ma_text_with_preset_code_yj_magnesium():
    """MedicationAdministration path — same regression, MA builder site."""
    from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_admin

    mar = {
        "order_id": "ORD-TEST-001",
        "drug_name": "Magnesium Sulfate 2g IV over 20min",
        "code_yj": "2355002",
        "scheduled_datetime": "2026-01-01T10:00:00",
        "actual_datetime": "2026-01-01T10:05:00",
        "status": "given",
        "dose": "2.0g DAILY",
        "route": "IV",
        "administered_by": "NS-IM-001",
    }
    result = _build_medication_admin(mar, patient_id="POP-TEST", index=0, country="JP", encounter_id="ENC-TEST")
    assert result["medicationCodeableConcept"]["text"] == "硫酸マグネシウム", (
        f"got {result['medicationCodeableConcept']['text']!r}"
    )
