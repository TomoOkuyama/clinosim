"""Positive/negative fixture tests for the JP-CLINS lab compliance axis.

CRITICAL: this test file is load-bearing. The axis's whole purpose is to
distinguish "measured zero" from "silently returning zero because the
code was broken" (the same class of failure the axis was designed to
detect in the JP-CLINS eCS profile itself — Open slicing +
``value:display`` discriminator silently accepts display mismatches).

Every metric MUST have at least one negative fixture that drives it
below 100% independently of the others. If a negative fixture stops
tripping (e.g. someone widens acceptance to make baseline "pass"), the
axis has silently regressed and should be treated as broken.
"""

from __future__ import annotations

from clinosim.eval.axes.jp_clins_lab_compliance import (
    _check_cs_usage,
    _check_fixed_display,
    _check_rule_satisfaction,
)
from clinosim.eval.engine import Outcome

# eCS SD constants — DO NOT swap for a local alias; the whole test's
# point is that these strings match production output byte-for-byte.
_CORELABO_JLAC10 = "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_CoreLabo_CS"
_LOCALCODE = "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_LocalCode_CS"
_JSLM_GENERIC_OID = "urn:oid:1.2.392.200119.4.1005"  # pre-migration primary system
_LOINC = "http://loinc.org"

# Two arbitrary code choices from CoreLabo CS v2026.03.31 (K + WBC parent),
# with Fixed display values pinned from the eCS SD extraction.
_WBC_17DIGIT = "2A990000001930952"
_WBC_FIXED_DISPLAY = "WBC"
_WBC_JP_LOCAL_DISPLAY = "白血球数"


def _lab_obs(codings: list[dict]) -> dict:
    """Minimal FHIR Observation with lab category — the axis reads
    ``category[].coding[].code == 'laboratory'`` and ``code.coding[]``."""
    return {
        "resourceType": "Observation",
        "category": [{"coding": [{"code": "laboratory"}]}],
        "code": {"coding": codings, "text": _WBC_JP_LOCAL_DISPLAY},
        "status": "final",
    }


# --------------------------------------------------------------------------- #
# Positive fixture — compliant Observation, all three metrics MUST hit 100%.


def _positive_obs() -> dict:
    return _lab_obs(
        [
            {"system": _CORELABO_JLAC10, "code": _WBC_17DIGIT, "display": _WBC_FIXED_DISPLAY},
            {"system": _LOCALCODE, "code": "wbc", "display": _WBC_JP_LOCAL_DISPLAY},
        ]
    )


def test_positive_fixture_cs_usage_100pct():
    check = _check_cs_usage([_positive_obs()])
    assert check.outcome == Outcome.PASS
    assert check.detail["ratio"] == 1.0


def test_positive_fixture_fixed_display_100pct():
    check = _check_fixed_display([_positive_obs()])
    assert check.outcome == Outcome.PASS
    assert check.detail["ratio"] == 1.0
    assert check.detail["numerator"] == 1
    assert check.detail["denominator"] == 1


def test_positive_fixture_rule_satisfaction_100pct():
    check = _check_rule_satisfaction([_positive_obs()])
    assert check.outcome == Outcome.PASS
    assert check.detail["ratio"] == 1.0


# --------------------------------------------------------------------------- #
# Negative fixture #1 — display mismatch on the CoreLabo coding.
# Only Metric 2 (Fixed display) must drop. The others must stay at 100%,
# proving the metric is independent from CS usage / rule satisfaction.


def _neg_display_obs() -> dict:
    return _lab_obs(
        [
            {"system": _CORELABO_JLAC10, "code": _WBC_17DIGIT, "display": _WBC_JP_LOCAL_DISPLAY},  # BROKEN
            {"system": _LOCALCODE, "code": "wbc", "display": _WBC_JP_LOCAL_DISPLAY},
        ]
    )


def test_negative_display_fixed_display_0pct():
    check = _check_fixed_display([_neg_display_obs()])
    assert check.outcome == Outcome.FAIL
    assert check.detail["ratio"] == 0.0
    assert check.detail["numerator"] == 0
    assert check.detail["denominator"] == 1  # CoreLabo coding is a slice-typed denominator


def test_negative_display_cs_usage_still_100pct():
    check = _check_cs_usage([_neg_display_obs()])
    assert check.outcome == Outcome.PASS


def test_negative_display_rule_satisfaction_still_100pct():
    check = _check_rule_satisfaction([_neg_display_obs()])
    assert check.outcome == Outcome.PASS


# --------------------------------------------------------------------------- #
# Negative fixture #2 — pre-migration system (JSLM generic OID + LOINC).
# ALL THREE metrics must FAIL because none of the systems is JP-CLINS-defined.
# This mirrors the baseline (v29) shape exactly.


def _neg_baseline_obs() -> dict:
    return _lab_obs(
        [
            {"system": _JSLM_GENERIC_OID, "code": "2A990", "display": "WBC"},
            {"system": _LOINC, "code": "6690-2", "display": "Leukocytes [#/volume] in Blood by Automated count"},
        ]
    )


def test_negative_baseline_cs_usage_0pct():
    check = _check_cs_usage([_neg_baseline_obs()])
    assert check.outcome == Outcome.FAIL
    assert check.detail["ratio"] == 0.0


def test_negative_baseline_fixed_display_na_via_empty_denominator():
    """Baseline: NO coding uses a Fixed-display slice system, so the
    denominator is 0. The axis MUST treat this as N/A — NOT FAIL, NOT
    PASS. Rationale: during migration, "no slice-typed coding emitted
    at all" (baseline) must be distinguishable from "slice-typed
    codings emitted but display mismatches" (broken emission). Both
    would collapse to FAIL if 0/0 were treated as ratio=0.0, hiding
    root cause during PR 2..4 diagnostic reads."""
    check = _check_fixed_display([_neg_baseline_obs()])
    assert check.outcome == Outcome.NA
    assert check.detail["numerator"] == 0
    assert check.detail["denominator"] == 0


def test_negative_baseline_rule_satisfaction_0pct():
    check = _check_rule_satisfaction([_neg_baseline_obs()])
    assert check.outcome == Outcome.FAIL
    assert check.detail["ratio"] == 0.0


# --------------------------------------------------------------------------- #
# Negative fixture #3 — no LocalCode slice.
# Only Metric 3 (rule satisfaction) must FAIL; Metrics 1+2 stay at 100%,
# proving Metric 3 is discriminating LocalCode presence independently.


def _neg_no_localcode_obs() -> dict:
    return _lab_obs(
        [
            {"system": _CORELABO_JLAC10, "code": _WBC_17DIGIT, "display": _WBC_FIXED_DISPLAY},
            # No LocalCode coding — rule requires it.
        ]
    )


def test_negative_no_localcode_rule_satisfaction_0pct():
    check = _check_rule_satisfaction([_neg_no_localcode_obs()])
    assert check.outcome == Outcome.FAIL
    assert check.detail["ratio"] == 0.0


def test_negative_no_localcode_cs_usage_still_100pct():
    check = _check_cs_usage([_neg_no_localcode_obs()])
    assert check.outcome == Outcome.PASS


def test_negative_no_localcode_fixed_display_still_100pct():
    check = _check_fixed_display([_neg_no_localcode_obs()])
    assert check.outcome == Outcome.PASS


# --------------------------------------------------------------------------- #
# Mixed cohort — 1 compliant + 1 broken-display, expected ratios prove
# aggregation math is correct (not just per-observation short-circuit).


def test_mixed_cohort_partial_ratios():
    cohort = [_positive_obs(), _neg_display_obs()]
    m1 = _check_cs_usage(cohort)
    m2 = _check_fixed_display(cohort)
    m3 = _check_rule_satisfaction(cohort)
    assert m1.detail["ratio"] == 1.0  # both observations use JP-CLINS CS
    assert m2.detail == {"numerator": 1, "denominator": 2, "ratio": 0.5}
    assert m3.detail["ratio"] == 1.0  # both have LocalCode + CoreLabo


# --------------------------------------------------------------------------- #
# NA path — empty cohort returns NA on the count-based metrics.


def test_empty_cohort_returns_na_on_count_metrics():
    assert _check_cs_usage([]).outcome == Outcome.NA
    assert _check_rule_satisfaction([]).outcome == Outcome.NA


def test_non_lab_observations_ignored():
    """Non-lab (e.g. vital signs, social history) Observations must not
    reach these checks — filtering is done upstream by
    ``_iter_lab_observations``. Here we pass an empty list to represent
    a post-filter state and confirm NA."""
    assert _check_cs_usage([]).outcome == Outcome.NA


# --------------------------------------------------------------------------- #
# Per-resource semantics guard.
# The validator-side feedback (session 67 memo, §3) explicitly asked that
# Metric 2 count per-Observation, NOT per-coding. Otherwise a resource
# that legitimately carries many slice-typed codings (e.g. dual-standard
# JLAC10+JLAC11 emission or extra Uncoded fallback) would be penalized
# more heavily than a resource with a single broken coding. This test
# pins the per-resource semantic: an Observation with N slice-typed
# codings still counts as ONE denominator increment.


def test_metric2_is_per_resource_not_per_coding():
    """1 observation with 4 slice-typed codings — 3 correct, 1 broken.
    Per-coding math would give 3/4 = 75%. Per-resource math gives 0/1 =
    0% (the observation has at least one broken slice-typed coding, so
    the ENTIRE observation is non-conformant to the Fixed display
    rule)."""
    multi_coding_obs = _lab_obs(
        [
            {"system": _CORELABO_JLAC10, "code": _WBC_17DIGIT, "display": _WBC_FIXED_DISPLAY},  # OK
            {"system": _CORELABO_JLAC10, "code": "3H015000002399801", "display": "K"},  # OK
            {"system": _CORELABO_JLAC10, "code": _WBC_17DIGIT, "display": "白血球数"},  # BROKEN
            {"system": _CORELABO_JLAC10, "code": _WBC_17DIGIT, "display": _WBC_FIXED_DISPLAY},  # OK
            {"system": _LOCALCODE, "code": "wbc", "display": _WBC_JP_LOCAL_DISPLAY},
        ]
    )
    check = _check_fixed_display([multi_coding_obs])
    assert check.detail == {"numerator": 0, "denominator": 1, "ratio": 0.0}
    assert check.outcome == Outcome.FAIL
