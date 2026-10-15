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
