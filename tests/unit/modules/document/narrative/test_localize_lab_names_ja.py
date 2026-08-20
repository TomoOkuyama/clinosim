"""prompt v11 hard-guard: JA post-processor for EN lab names in
LLM narrative output.

Rule 5 D of the JA narrative_seed_bundle.yaml prompt asks the LLM to
translate English lab names (Albumin → アルブミン, Creatinine →
クレアチニン, etc.) to canonical Japanese katakana in JA output. The
prompt is a soft guardrail — the p=10000 s500 dataset showed 1,063 EN
lab hits across 900 new ED_NOTE narratives even with the LOCALIZATION
rule in place. This deterministic post-processor is the hard guard.

Standard medical abbreviations (BUN, CRP, BNP, WBC, HbA1c, eGFR, Cr,
PT-INR, Na, K, Cl, Ca, Mg, P, AST, ALT, ALP, LDH, LDL, HDL, TG, etc.)
are DELIBERATELY preserved as-is — those are Japanese medical standard
and localizing them would harm readability.
"""

from __future__ import annotations

from clinosim.modules.document.narrative.replacement_strategy import (
    _localize_lab_names_in_sections_ja,
    _localize_lab_names_in_text_ja,
)


# ---- single-word lab names → JA -----------------------------------------


def test_albumin_localized():
    assert _localize_lab_names_in_text_ja("Albumin 4.0 g/dL [L]") == "アルブミン 4.0 g/dL [L]"


def test_creatinine_localized():
    assert _localize_lab_names_in_text_ja("Creatinine 1.2 mg/dL") == "クレアチニン 1.2 mg/dL"


def test_glucose_localized():
    assert _localize_lab_names_in_text_ja("Glucose 180 mg/dL [H]") == "血糖 180 mg/dL [H]"


def test_lactate_localized():
    assert _localize_lab_names_in_text_ja("Lactate 3.5 mmol/L") == "乳酸 3.5 mmol/L"


# ---- compound lab names (longest-match first) ---------------------------


def test_total_bilirubin_takes_precedence_over_bilirubin():
    """'Total bilirubin' must match as one unit, not 'Total' + 'Bilirubin' —
    otherwise emits 'Total ビリルビン' which is neither JA nor EN."""
    assert _localize_lab_names_in_text_ja("Total bilirubin 3.0 mg/dL") == "総ビリルビン 3.0 mg/dL"


def test_direct_bilirubin_compound_match():
    assert _localize_lab_names_in_text_ja("Direct bilirubin 0.4 mg/dL") == "直接ビリルビン 0.4 mg/dL"


def test_urea_nitrogen_compound_match():
    assert _localize_lab_names_in_text_ja("Urea nitrogen 25 mg/dL") == "尿素窒素 25 mg/dL"


def test_white_blood_cell_compound_match():
    assert _localize_lab_names_in_text_ja("White blood cell 12000 /uL") == "白血球 12000 /uL"


def test_troponin_i_compound_match():
    assert _localize_lab_names_in_text_ja("Troponin I 0.05 ng/mL") == "トロポニンI 0.05 ng/mL"


def test_total_protein_compound_match():
    assert _localize_lab_names_in_text_ja("Total protein 6.8 g/dL") == "総蛋白 6.8 g/dL"


# ---- abbreviations preserved (JA medical standard) ---------------------


def test_bun_preserved():
    assert _localize_lab_names_in_text_ja("BUN 25 mg/dL") == "BUN 25 mg/dL"


def test_crp_preserved():
    assert _localize_lab_names_in_text_ja("CRP 12.5 mg/dL") == "CRP 12.5 mg/dL"


def test_bnp_preserved():
    assert _localize_lab_names_in_text_ja("BNP 808.8 pg/mL [H]") == "BNP 808.8 pg/mL [H]"


def test_ast_alt_preserved():
    assert _localize_lab_names_in_text_ja("AST 67 U/L [H], ALT 62 U/L [H]") == "AST 67 U/L [H], ALT 62 U/L [H]"


def test_hbA1c_preserved():
    assert _localize_lab_names_in_text_ja("HbA1c 7.2 %") == "HbA1c 7.2 %"


def test_egfr_and_cr_preserved():
    assert _localize_lab_names_in_text_ja("eGFR 45 mL/min, Cr 1.5 mg/dL") == "eGFR 45 mL/min, Cr 1.5 mg/dL"


def test_electrolytes_short_form_preserved():
    """Na, K, Cl, Ca, Mg, P are the JA standard short forms — do NOT
    swap for the full-word translations (Sodium → ナトリウム etc.)."""
    text = "Na 138 mEq/L, K 4.1 mEq/L, Cl 102 mEq/L, Ca 9.5 mg/dL, Mg 2.0 mg/dL, P 3.5 mg/dL"
    assert _localize_lab_names_in_text_ja(text) == text


# ---- mixed sentences (real ED_NOTE excerpts) ---------------------------


def test_mixed_prose_localizes_only_full_words():
    text = "検査: Albumin 4.0 g/dL [L]、AST 67.0 U/L [H]、ALT 62.0 U/L [H]、BNP 808.8 pg/mL [H]"
    expected = "検査: アルブミン 4.0 g/dL [L]、AST 67.0 U/L [H]、ALT 62.0 U/L [H]、BNP 808.8 pg/mL [H]"
    assert _localize_lab_names_in_text_ja(text) == expected


def test_multi_lab_mixed_all_swapped():
    text = "Creatinine 2.1, Glucose 180, Albumin 3.2, Lactate 4.0"
    expected = "クレアチニン 2.1, 血糖 180, アルブミン 3.2, 乳酸 4.0"
    assert _localize_lab_names_in_text_ja(text) == expected


# ---- case insensitivity ------------------------------------------------


def test_uppercase_lab_name():
    assert _localize_lab_names_in_text_ja("ALBUMIN 4.0 g/dL") == "アルブミン 4.0 g/dL"


def test_lowercase_lab_name():
    assert _localize_lab_names_in_text_ja("albumin 4.0 g/dL") == "アルブミン 4.0 g/dL"


# ---- non-matching text passes through ---------------------------------


def test_pure_japanese_prose_unchanged():
    text = "本態性高血圧 (Stage 2, 中等度) の経過観察。BP 131/81 mmHg。"
    assert _localize_lab_names_in_text_ja(text) == text


def test_empty_string_unchanged():
    assert _localize_lab_names_in_text_ja("") == ""


def test_bp_and_vitals_not_touched():
    """BP / HR / RR / SpO2 / T are vitals, not labs — pattern must
    not accidentally match them."""
    text = "BP 120/80 mmHg, HR 72, RR 16, SpO2 98%, T 36.5°C"
    assert _localize_lab_names_in_text_ja(text) == text


# ---- sections wrapper -------------------------------------------------


def test_sections_wrapper_applies_to_every_value():
    sections = {
        "subjective": "労作時呼吸困難",
        "assessment": "Albumin 4.0 g/dL [L] を認め、循環不全と判断。",
        "plan": "Creatinine の再検査を明日実施。",
    }
    localized = _localize_lab_names_in_sections_ja(sections)
    assert localized["subjective"] == "労作時呼吸困難"
    assert localized["assessment"] == "アルブミン 4.0 g/dL [L] を認め、循環不全と判断。"
    assert localized["plan"] == "クレアチニン の再検査を明日実施。"


def test_sections_wrapper_returns_new_dict():
    """Caller-visible immutability: input dict is not mutated."""
    original = {"a": "Albumin 4.0"}
    _ = _localize_lab_names_in_sections_ja(original)
    assert original == {"a": "Albumin 4.0"}


# ---- word boundary safety --------------------------------------------


def test_no_match_inside_larger_word():
    """'Album' inside 'Album...' must not partially match — regex uses
    word boundaries. Simulates a hallucinated LLM word that happens to
    start with 'Album'."""
    # NB: 'Albumin' followed by more letters would not word-boundary.
    assert _localize_lab_names_in_text_ja("Album cover") == "Album cover"
    # But standalone Albumin does match:
    assert _localize_lab_names_in_text_ja("Album Albumin cover") == "Album アルブミン cover"


def test_plural_platelets_matches_singular_pattern():
    """Both 'Platelet' and 'Platelets' are in the JA map → both localize
    to 血小板 (singular JA form is idiomatic)."""
    assert _localize_lab_names_in_text_ja("Platelet 200 x10^3/uL") == "血小板 200 x10^3/uL"
    assert _localize_lab_names_in_text_ja("Platelets 200 x10^3/uL") == "血小板 200 x10^3/uL"
