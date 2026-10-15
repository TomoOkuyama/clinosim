"""PHQ-9 (Patient Health Questionnaire-9) assessment emission.

Issue #1137 mental_health/ cluster axis 2. Verifies the observation-
engine wiring for PHQ-9: integer-valued score in [0, 27], LOINC
canonical 44249-1 via US code map, baseline 10 (moderate band)
with 20% test-retest CV, no reference-range flag (severity grade
rather than lab abnormality).
"""

from __future__ import annotations

import numpy as np

from clinosim.locale.loader import load_code_mapping
from clinosim.modules.observation.engine import (
    BASELINE_LAB_NORMALS,
    BIOLOGICAL_CV,
    LAB_UNITS,
    PHYSIOLOGIC_LIMITS,
    PRECISION,
    determine_flag,
    generate_lab_result,
    get_lab_unit,
)


def test_phq9_canonical_catalog_wiring() -> None:
    """PHQ-9 is registered in every analyte-catalog table used by
    the outpatient lab-emission loop. Missing from any one would
    silently drop the Observation."""
    assert "PHQ-9" in BASELINE_LAB_NORMALS
    assert "PHQ-9" in BIOLOGICAL_CV
    assert "PHQ-9" in LAB_UNITS
    assert "PHQ-9" in PHYSIOLOGIC_LIMITS
    assert "PHQ-9" in PRECISION


def test_phq9_unit_is_score_ucum() -> None:
    """UCUM ``{score}`` annotation is the canonical FHIR
    Observation.unit for standardized assessment scores."""
    assert get_lab_unit("PHQ-9") == "{score}"


def test_phq9_physiologic_limits_scoring_rule() -> None:
    """PHQ-9 total score 0-27 is a scoring-rule invariant
    (9 items × 0-3 points), not a physiologic range."""
    assert PHYSIOLOGIC_LIMITS["PHQ-9"] == (0.0, 27.0)


def test_phq9_precision_is_integer() -> None:
    """PHQ-9 is integer-valued by construction — precision=0 rounds
    the post-noise float to an int."""
    assert PRECISION["PHQ-9"] == 0


def test_phq9_us_loinc_mapping() -> None:
    """US code map maps PHQ-9 → LOINC 44249-1 (PHQ-9 total score).
    This is the FHIR Observation.code.coding[0].code consumed by
    the US coding strategy."""
    us_map = load_code_mapping("lab", "US")
    assert us_map.get("PHQ-9") == "44249-1"


def test_phq9_generate_lab_result_integer_in_range() -> None:
    """``generate_lab_result("PHQ-9", baseline, rng)`` returns an
    integer-rounded value in [0, 27] respecting the PHQ-9 scoring
    rule. Spot-check at the moderate (10) baseline."""
    rng = np.random.default_rng(42)
    for _ in range(50):
        value = generate_lab_result("PHQ-9", 10.0, rng)
        # Score must be numeric (not qualitative string).
        assert isinstance(value, (int, float))
        assert float(value).is_integer(), f"PHQ-9 value {value} is not an integer"
        assert 0 <= float(value) <= 27, f"PHQ-9 value {value} outside scoring range"


def test_phq9_determine_flag_returns_none_without_reference_range() -> None:
    """PHQ-9 is a severity score, not a lab abnormality — it has no
    reference range entry so ``determine_flag`` returns None
    (FHIR Observation.interpretation omitted)."""
    assert determine_flag("PHQ-9", 10, country="US") is None
    assert determine_flag("PHQ-9", 20, country="US") is None


def test_phq9_moderate_baseline_matches_f32_cohort_mode() -> None:
    """BASELINE_LAB_NORMALS["PHQ-9"] sits in the moderate (10-14)
    band per Kroenke 2001 severity scoring. Modeled as the F32
    cohort distribution mode consistent with Mitchell 2013 BMJ
    primary-care screening meta."""
    baseline = BASELINE_LAB_NORMALS["PHQ-9"]
    assert 10 <= baseline <= 14, f"baseline {baseline} not in moderate band"


# ===========================================================================
# GAD-7 (axis 3 of META #1137)
# ===========================================================================


def test_gad7_canonical_catalog_wiring() -> None:
    """GAD-7 is registered in every analyte-catalog table used by
    the outpatient lab-emission loop. Missing from any one would
    silently drop the Observation."""
    assert "GAD-7" in BASELINE_LAB_NORMALS
    assert "GAD-7" in BIOLOGICAL_CV
    assert "GAD-7" in LAB_UNITS
    assert "GAD-7" in PHYSIOLOGIC_LIMITS
    assert "GAD-7" in PRECISION


def test_gad7_unit_is_score_ucum() -> None:
    assert get_lab_unit("GAD-7") == "{score}"


def test_gad7_physiologic_limits_scoring_rule() -> None:
    """GAD-7 total score 0-21 (7 items × 3 points)."""
    assert PHYSIOLOGIC_LIMITS["GAD-7"] == (0.0, 21.0)


def test_gad7_precision_is_integer() -> None:
    assert PRECISION["GAD-7"] == 0


def test_gad7_us_loinc_mapping() -> None:
    """US code map maps GAD-7 → LOINC 70274-6 (Generalized Anxiety
    Disorder-7)."""
    us_map = load_code_mapping("lab", "US")
    assert us_map.get("GAD-7") == "70274-6"


def test_gad7_generate_lab_result_integer_in_range() -> None:
    """``generate_lab_result("GAD-7", baseline, rng)`` returns an
    integer-rounded value in [0, 21]."""
    rng = np.random.default_rng(42)
    for _ in range(50):
        value = generate_lab_result("GAD-7", 8.0, rng)
        assert isinstance(value, (int, float))
        assert float(value).is_integer(), f"GAD-7 value {value} is not an integer"
        assert 0 <= float(value) <= 21, f"GAD-7 value {value} outside scoring range"


def test_gad7_mild_to_moderate_baseline_matches_f411_cohort_mode() -> None:
    """BASELINE_LAB_NORMALS["GAD-7"] sits at the mild→moderate
    transition (5-14 band) per Spitzer 2006 severity scoring,
    consistent with primary-care-cohort means."""
    baseline = BASELINE_LAB_NORMALS["GAD-7"]
    assert 5 <= baseline <= 14, f"baseline {baseline} outside mild-to-moderate band"


# ===========================================================================
# C-SSRS (axis 7 of META #1137)
# ===========================================================================


def test_cssrs_canonical_catalog_wiring() -> None:
    """C-SSRS is registered in every analyte-catalog table used by
    the outpatient lab-emission loop."""
    assert "C-SSRS" in BASELINE_LAB_NORMALS
    assert "C-SSRS" in BIOLOGICAL_CV
    assert "C-SSRS" in LAB_UNITS
    assert "C-SSRS" in PHYSIOLOGIC_LIMITS
    assert "C-SSRS" in PRECISION


def test_cssrs_unit_is_score_ucum() -> None:
    assert get_lab_unit("C-SSRS") == "{score}"


def test_cssrs_physiologic_limits_scoring_rule() -> None:
    """C-SSRS ideation severity 0-5 per Posner 2011."""
    assert PHYSIOLOGIC_LIMITS["C-SSRS"] == (0.0, 5.0)


def test_cssrs_precision_is_integer() -> None:
    assert PRECISION["C-SSRS"] == 0


def test_cssrs_us_loinc_mapping() -> None:
    """US code map maps C-SSRS → LOINC 93372-1 (Columbia Suicide
    Severity Rating Scale lifetime ideation severity scale)."""
    us_map = load_code_mapping("lab", "US")
    assert us_map.get("C-SSRS") == "93372-1"


def test_cssrs_generate_lab_result_integer_in_range() -> None:
    """``generate_lab_result("C-SSRS", baseline, rng)`` returns an
    integer-rounded value in [0, 5]."""
    rng = np.random.default_rng(42)
    for _ in range(50):
        value = generate_lab_result("C-SSRS", 1.0, rng)
        assert isinstance(value, (int, float))
        assert float(value).is_integer(), f"C-SSRS value {value} is not an integer"
        assert 0 <= float(value) <= 5, f"C-SSRS value {value} outside scoring range"


def test_cssrs_passive_baseline_matches_f32_cohort_mean() -> None:
    """BASELINE_LAB_NORMALS["C-SSRS"] sits at the passive-ideation
    tier (1 — wish to be dead) matching Posner 2011 cohort-weighted
    mean for F32/F33 patients. The outpatient emit path overrides
    this with a PHQ-9-band-conditioned baseline when the staged
    severity is known (axis 7 severity-sourced path)."""
    baseline = BASELINE_LAB_NORMALS["C-SSRS"]
    assert 0 <= baseline <= 2, f"baseline {baseline} outside expected passive-ideation range"
