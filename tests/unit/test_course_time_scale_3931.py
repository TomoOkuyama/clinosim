"""The disease course is calibrated once per disease and severity, the same in every country (Issue #3931).

The disease trajectories are authored on the Japanese stay length, but a patient becomes clinically stable
around the US target length of stay (US practice discharges at stability). Run at the authored speed, a US
patient was still febrile or hypoperfused at the end of the sampled stay and the discharge gates held him
for days past the protocol's maximum. A stable Japanese patient stays until the sampled target by practice.
"""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_care_practice
from clinosim.modules.clinical_course.engine import (
    course_time_scale,
    course_time_scale_rules,
    get_daily_directive,
    natural_recovery_directive,
)
from clinosim.modules.disease.protocol import load_all_disease_protocols
from clinosim.types.patient import PatientPhysiologicalProfile

PROFILE = PatientPhysiologicalProfile(immune_reactivity=0.5, treatment_sensitivity=1.0)
ARCH = {"smooth_recovery": {"trajectory": {"inflammation_level": {0: -0.02, 4: -0.08, 8: -0.04}}}}


def test_rules_load_and_validate() -> None:
    rules = course_time_scale_rules()
    assert 0 < rules.min_scale <= 1.0 <= rules.max_scale


def test_scale_is_per_disease_and_severity() -> None:
    assert course_time_scale("bacterial_pneumonia", "moderate") == pytest.approx(2.8)
    assert course_time_scale("bacterial_pneumonia", "mild") != course_time_scale("bacterial_pneumonia", "severe")


def test_unknown_disease_or_severity_runs_at_the_authored_speed() -> None:
    assert course_time_scale("no_such_disease", "moderate") == 1.0
    assert course_time_scale("bacterial_pneumonia", "no_such_severity") == 1.0


def test_table_is_the_bounded_ratio_of_the_two_targets_for_every_protocol() -> None:
    """The calibration is traceable: japan mean / us mean, bounded, two decimals; none is missing."""
    rules = course_time_scale_rules()
    for disease_id, p in load_all_disease_protocols().items():
        for severity in ("mild", "moderate", "severe"):
            jp = (p.target_los.get("japan") or {}).get(severity)
            us = (p.target_los.get("us") or {}).get(severity)
            if not (jp and us):
                assert course_time_scale(disease_id, severity) == 1.0, (disease_id, severity)
                continue
            ratio = min(rules.max_scale, max(rules.min_scale, jp["mean"] / us["mean"]))
            assert course_time_scale(disease_id, severity) == pytest.approx(ratio, abs=0.006), (disease_id, severity)


def test_table_names_only_known_diseases() -> None:
    assert set(course_time_scale_rules().scales) <= set(load_all_disease_protocols())


def test_default_scale_leaves_the_directive_unchanged() -> None:
    for day in range(0, 12):
        a = get_daily_directive("smooth_recovery", day, PROFILE, protocol_archetypes=ARCH, age=60, rng=None)
        b = get_daily_directive(
            "smooth_recovery", day, PROFILE, protocol_archetypes=ARCH, age=60, rng=None, time_scale=1.0
        )
        assert a.changes == b.changes


def test_scale_compresses_the_trajectory_and_keeps_its_total() -> None:
    """Twice as fast: the day-d delta is twice the authored delta of day 2d, so the course is the
    same curve in half the days."""
    for day in range(0, 4):
        slow = get_daily_directive("smooth_recovery", 2 * day, PROFILE, protocol_archetypes=ARCH, age=60, rng=None)
        fast = get_daily_directive(
            "smooth_recovery", day, PROFILE, protocol_archetypes=ARCH, age=60, rng=None, time_scale=2.0
        )
        assert fast.changes["inflammation_level"] == pytest.approx(2.0 * slow.changes["inflammation_level"])


def test_natural_recovery_is_faster_by_the_scale() -> None:
    base = natural_recovery_directive(1, "bacterial_pneumonia", "moderate", PROFILE).changes
    fast = natural_recovery_directive(1, "bacterial_pneumonia", "moderate", PROFILE, time_scale=2.0).changes
    for var in ("inflammation_level", "oxygenation_impairment", "sympathetic_activation"):
        assert fast[var] == pytest.approx(2.0 * base[var])
    assert fast["anemia_level"] == base["anemia_level"]  # marrow recovery is not a course speed


def test_japanese_practice_keeps_a_stable_patient_to_the_sampled_target_and_the_us_does_not() -> None:
    assert load_care_practice("JP").hold_stable_patient_to_sampled_target is True
    assert load_care_practice("US").hold_stable_patient_to_sampled_target is False
