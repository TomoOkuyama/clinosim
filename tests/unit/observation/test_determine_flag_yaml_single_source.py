"""Regression test for Issue #542: `determine_flag` reads reference ranges
from `clinosim/locale/<country>/reference_range_lab.yaml` so the CIF flag and
the FHIR ``Observation.interpretation`` (which reads the same YAML) agree.

Verifies:
- JP cohort uses JCCLS共用基準範囲2022 boundaries (from YAML), not the old
  hardcoded defaults.
- US cohort uses the US YAML boundaries.
- Panic / critical thresholds remain hardcoded and fire regardless of country.
- Empty / unknown lab names return None (unflagged).
"""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_reference_ranges
from clinosim.modules.observation.engine import (
    _PANIC_THRESHOLDS,
    _reference_ranges_by_sex,
    determine_flag,
)

pytestmark = pytest.mark.unit


class TestJpRangesMatchYaml:
    """JP cohort must flag against JCCLS boundaries in the JP YAML."""

    def test_wbc_jccls_upper_bound(self):
        # JCCLS WBC: 3300–8600. Pre-fix hardcoded upper was 9500.
        # 9000 is normal under old defaults, "H" under JCCLS.
        assert determine_flag("WBC", 9000, sex="F", country="JP") == "H"

    def test_wbc_jccls_within_range(self):
        assert determine_flag("WBC", 5000, sex="F", country="JP") is None

    def test_hb_male_jccls_lower_bound(self):
        # JCCLS Hb M: 13.7–16.8. Pre-fix hardcoded lower was 13.5.
        # 13.6 is normal under old defaults, "L" under JCCLS.
        assert determine_flag("Hb", 13.6, sex="M", country="JP") == "L"

    def test_ast_jccls_upper_bound(self):
        # JCCLS AST: 13–30. Pre-fix hardcoded upper was 35.
        assert determine_flag("AST", 33, sex="F", country="JP") == "H"


class TestUsRangesMatchYaml:
    def test_wbc_us_upper_bound(self):
        # US YAML WBC: 3500–10500.
        assert determine_flag("WBC", 11000, sex="F", country="US") == "H"
        assert determine_flag("WBC", 9000, sex="F", country="US") is None

    def test_troponin_sex_specific(self):
        # US YAML now carries the 4th Universal MI definition: F 0.03, M 0.04.
        assert determine_flag("Troponin_I", 0.035, sex="F", country="US") == "H"
        assert determine_flag("Troponin_I", 0.035, sex="M", country="US") is None


class TestPanicThresholdsAcrossCountries:
    """Critical / panic cutoffs are safety-critical and locale-agnostic."""

    def test_k_high_panic_fires_regardless_of_country(self):
        assert determine_flag("K", 7.0, country="US") == "critical"
        assert determine_flag("K", 7.0, country="JP") == "critical"

    def test_hb_low_panic_fires_regardless_of_country(self):
        assert determine_flag("Hb", 6.0, sex="M", country="US") == "critical"
        assert determine_flag("Hb", 6.0, sex="M", country="JP") == "critical"


class TestFallbackBehaviour:
    def test_unknown_lab_returns_none(self):
        assert determine_flag("NotARealLab", 42, country="US") is None

    def test_qualitative_string_result_returns_none(self):
        assert determine_flag("Urinalysis", "1+ protein", country="US") is None

    def test_default_country_is_us(self):
        # Issue #570 convention: no country supplied → US.
        assert determine_flag("WBC", 11000, sex="F") == "H"


class TestYamlLoaderRoundTrip:
    """The `_reference_ranges_by_sex` cache must produce the same values a
    downstream FHIR `Observation.referenceRange` would emit."""

    def test_jp_ranges_dict_matches_yaml(self):
        ranges = _reference_ranges_by_sex("JP")
        # JCCLS WBC 3300–8600
        assert ranges["WBC"]["all"] == (3300.0, 8600.0)
        # JCCLS Hb male 13.7–16.8
        assert ranges["Hb"]["M"] == (13.7, 16.8)
        # JCCLS AST 13–30
        assert ranges["AST"]["all"] == (13.0, 30.0)

    def test_us_ranges_dict_matches_yaml(self):
        ranges = _reference_ranges_by_sex("US")
        # US WBC 3500–10500
        assert ranges["WBC"]["all"] == (3500.0, 10500.0)


class TestPanicSetIsDocumentedConstant:
    """Guard against silent drift of the panic set (safety-critical)."""

    def test_panic_thresholds_present(self):
        assert "K" in _PANIC_THRESHOLDS
        assert "Hb" in _PANIC_THRESHOLDS
        assert "Glucose" in _PANIC_THRESHOLDS
        assert "Na" in _PANIC_THRESHOLDS
        assert "pH" in _PANIC_THRESHOLDS

    def test_panic_thresholds_shape(self):
        # (low_panic, high_panic) — either may be None (one-sided).
        for lab, (lo, hi) in _PANIC_THRESHOLDS.items():
            assert lo is None or isinstance(lo, (int, float)), lab
            assert hi is None or isinstance(hi, (int, float)), lab


class TestSourceLoaderMatches:
    """The raw YAML loader used by the FHIR emitter (``build_reference_range``)
    reads the same source as ``determine_flag``. A drift here would re-open the
    exact CIF-vs-FHIR discrepancy Issue #542 closed."""

    def test_jp_yaml_ranges_key_present(self):
        raw = load_reference_ranges("JP")
        assert "ranges" in raw
        assert "WBC" in raw["ranges"]

    def test_us_yaml_ranges_key_present(self):
        raw = load_reference_ranges("US")
        assert "ranges" in raw
        assert "WBC" in raw["ranges"]
