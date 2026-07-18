"""JLAC10 analyte-code integrity (verified vs the official JSLM master, AD-57).

Guards against fabricated / mismapped codes: every JP-mapped lab must resolve to a
JLAC10 analyte code that exists in the code table, and key analytes must map to the
exact codes confirmed against the JSLM JLAC10 master v137.
"""

from pathlib import Path

import pytest
import yaml

import clinosim
from clinosim.codes import lookup

_ROOT = Path(clinosim.__file__).parent
_JLAC10 = yaml.safe_load((_ROOT / "codes/data/jlac10.yaml").read_text())["codes"]
_JP_MAP = yaml.safe_load((_ROOT / "locale/jp/code_mapping_lab.yaml").read_text())
_JP_MICRO_SUS_MAP = yaml.safe_load((_ROOT / "locale/jp/code_mapping_microbiology_susceptibility.yaml").read_text())


@pytest.mark.unit
class TestJLAC10Integrity:
    def test_every_mapped_code_exists(self):
        missing = {name: code for name, code in _JP_MAP.items() if code not in _JLAC10}
        assert not missing, f"JP lab codes absent from jlac10.yaml: {missing}"

    def test_every_code_has_english(self):
        """English-first principle: every code must carry an `en` field."""
        no_en = [c for c, e in _JLAC10.items() if not e.get("en")]
        assert not no_en, f"JLAC10 codes missing `en`: {no_en}"

    def test_no_microbiology_codes_used_for_chemistry(self):
        """Regression: blood gas must not reuse the 6A0xx microbiology range."""
        for analyte in ("pH", "pCO2", "pO2", "HCO3"):
            assert not _JP_MAP[analyte].startswith("6A"), f"{analyte} mapped to a microbiology code {_JP_MAP[analyte]}"

    @pytest.mark.parametrize(
        "analyte,code",
        [
            ("Na", "3H010"),
            ("K", "3H015"),
            ("Cl", "3H020"),
            ("Ca", "3H030"),
            ("Hb", "2A030"),
            ("Hct", "2A040"),
            ("BUN", "3C025"),
            ("T_Bil", "3J010"),
            ("LDH", "3B050"),
            ("Lactate", "3E010"),
            ("BNP", "4Z271"),
            ("PCT", "5C215"),
            ("pH", "3H050"),
            ("pCO2", "3H055"),
            ("pO2", "3H060"),
            ("HCO3", "3G125"),
            ("Troponin_I", "5C094"),
            ("CK_MB", "3B015"),
            ("TSH", "4A055"),
            ("ESR", "2Z010"),
            ("LDL", "3F077"),
            ("HDL", "3F070"),
            ("TG", "3F015"),
            ("TC", "3F050"),
            # --- Coagulation panel (LOINC 24373-3) additions; JSLM v137 verified.
            # NOTE on PT: JLAC10 analyte codes capture the analyte only — PT seconds
            # and PT-INR share `2B030` "プロトロンビン時間" because the result-
            # representation distinction lives in the 17-char full code's result-
            # identifier segment, not the 5-char analyte code. LOINC by contrast
            # uses distinct codes (5902-2 PT, 6301-6 PT-INR).
            ("APTT", "2B020"),
            ("PT", "2B030"),
            ("PT_INR", "2B030"),
            ("Fibrinogen", "2B100"),
            # --- Phase 2a addition (JSLM v137 row 2B140: D-Dダイマー / D-D dimer)
            ("D_dimer", "2B140"),
        ],
    )
    def test_verified_codes(self, analyte, code):
        """Codes confirmed against the JSLM JLAC10 master v137."""
        assert _JP_MAP[analyte] == code

    def test_display_resolves(self):
        assert lookup("jlac10", "5C094", "en") == "Troponin I"
        # ja entry uses the official JCCLS Japanese name with the English
        # abbreviation parenthesised (data-quality review 2026-06-23).
        assert lookup("jlac10", "4A055", "ja") == "甲状腺刺激ホルモン(TSH)"


_JP_MICRO_MAP = yaml.safe_load((_ROOT / "locale/jp/code_mapping_microbiology.yaml").read_text())


@pytest.mark.unit
class TestMicrobiologyJLAC10Integrity:
    def test_every_mapped_code_exists(self):
        missing = {specimen: code for specimen, code in _JP_MICRO_MAP.items() if code not in _JLAC10}
        assert not missing, f"JP microbiology codes absent from jlac10.yaml: {missing}"

    def test_all_four_specimens_mapped(self):
        assert set(_JP_MICRO_MAP) == {"blood", "urine", "sputum", "wound"}

    def test_verified_code(self):
        """JLAC10 has one generic culture-identification analyte code (6B010),
        not per-specimen codes — the specimen distinction lives in the 17-digit
        full code's material segment, which clinosim does not model. Verified
        against JSLM JLAC10 master v137, category 6B (微生物学的検査/培養同定検査),
        2026-07-04."""
        assert all(code == "6B010" for code in _JP_MICRO_MAP.values())

    def test_display_resolves(self):
        assert lookup("jlac10", "6B010", "en") == "Culture and identification (common bacteria)"
        assert lookup("jlac10", "6B010", "ja") == "培養同定(一般細菌)"


@pytest.mark.unit
class TestMicrobiologySusceptibilityJLAC10Integrity:
    def test_every_mapped_code_exists(self):
        missing = {loinc: code for loinc, code in _JP_MICRO_SUS_MAP.items() if code not in _JLAC10}
        assert not missing, f"JP susceptibility codes absent from jlac10.yaml: {missing}"

    def test_all_ten_antibiotics_mapped(self):
        # Keys are the antibiotic_loinc values from microbiology.yaml's `antibiotics`
        # dict (the join key SusceptibilityResult already carries — no CIF schema
        # change needed, mirrors the culture-code fix's use of `specimen`).
        assert set(_JP_MICRO_SUS_MAP) == {
            "18862-3",
            "18866-4",
            "18895-3",
            "18879-7",
            "18906-8",
            "18908-4",
            # session 58 Issue #264: 18991-2 / 18949-0 / 18943-3 / 18996-1 were
            # retired from LOINC. Substitutes are the corresponding real
            # active LOINCs (verified against LOINC 2.82).
            "19000-9",  # was 18991-2 (Vancomycin Susc Isolate)
            "18970-4",  # was 18949-0 (Piperacillin+Tazobactam Susc Isolate)
            "18943-1",  # was 18943-3 (Meropenem Susc Isolate)
            "18998-5",  # was 18996-1 (Trimethoprim+Sulfamethoxazole Susc Isolate)
        }

    def test_verified_code(self):
        """JLAC10 has one generic drug-susceptibility-test analyte code (6C010),
        not per-drug codes — the drug distinction lives in the 17-digit full
        code's result-identifier segment, which clinosim does not model.
        Verified against JSLM JLAC10 master v137, category 6C
        (微生物学的検査/薬剤感受性検査), 2026-07-04."""
        assert all(code == "6C010" for code in _JP_MICRO_SUS_MAP.values())

    def test_display_resolves(self):
        assert lookup("jlac10", "6C010", "en") == "Drug susceptibility test (common bacteria)"
        assert lookup("jlac10", "6C010", "ja") == "薬剤感受性検査(一般細菌)"
