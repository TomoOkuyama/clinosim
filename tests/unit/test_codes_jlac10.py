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
            assert not _JP_MAP[analyte].startswith("6A"), \
                f"{analyte} mapped to a microbiology code {_JP_MAP[analyte]}"

    @pytest.mark.parametrize("analyte,code", [
        ("Na", "3H010"), ("K", "3H015"), ("Cl", "3H020"), ("Ca", "3H030"),
        ("Hb", "2A030"), ("Hct", "2A040"), ("BUN", "3C025"), ("T_Bil", "3J010"),
        ("LDH", "3B050"), ("Lactate", "3E010"), ("BNP", "4Z271"), ("PCT", "5C215"),
        ("pH", "3H050"), ("pCO2", "3H055"), ("pO2", "3H060"), ("HCO3", "3G125"),
        ("Troponin_I", "5C094"), ("CK_MB", "3B015"), ("TSH", "4A055"), ("ESR", "2Z010"),
        ("LDL", "3F077"), ("HDL", "3F070"), ("TG", "3F015"), ("TC", "3F050"),
    ])
    def test_verified_codes(self, analyte, code):
        """Codes confirmed against the JSLM JLAC10 master v137."""
        assert _JP_MAP[analyte] == code

    def test_display_resolves(self):
        assert lookup("jlac10", "5C094", "en") == "Troponin I"
        assert lookup("jlac10", "4A055", "ja") == "TSH"
