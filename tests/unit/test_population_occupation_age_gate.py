"""Issue #360 G7: developmental-stage occupation labels for minors.

Pins the ``_sample_occupation`` age brackets that split the pre-fix
``age <= student_max`` catch-all (which emitted every child as "student")
into developmentally-appropriate categories.

Concrete failure this test guards
---------------------------------
Before the fix, ``POP-000004 (2 歳)`` in JP p=1000 output rendered as::

    {"code": {"text": "職業"}, "valueCodeableConcept": {"text": "学生"}}

iris4h-ai's Clinical Cockpit flagged this as clinically untrusted
(feedback 2026-07-22 G7). The fix splits the ``age <= student_max``
bracket by developmental stage while preserving the RNG-consumption
shape for older ages (F4 memoize test guards against downstream drift).

Scope
-----
* Ages 0-14 (within pre-fix ``student_max``): split into
  infant / preschool / elementary_student / middle_school_student.
* Ages 15+: unchanged from pre-fix behaviour to keep the RNG stream
  byte-identical (the F4 memoize test detects any shift).
* The smoking / alcohol age gate was attempted in this PR but reverted
  after tripping the same F4 memoize test — deferred (see
  ``clinosim/modules/population/engine.py`` NOTE comment).
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.output._fhir_localization import (
    _OCCUPATION_DISPLAY_EN,
    _OCCUPATION_DISPLAY_JA,
)
from clinosim.modules.population.engine import _sample_occupation

pytestmark = pytest.mark.unit


# Minimal demographics config sufficient to exercise _sample_occupation.
_DEMO: dict = {
    "occupation_distribution": {
        "age_thresholds": {
            "student_max_age": 14,
            "young_adult_max_age": 21,
            "young_adult_student_prob": 0.70,
            "retirement_min_age": 65,
        },
        "working_age": {
            "office": 0.60,
            "healthcare": 0.20,
            "service": 0.20,
        },
    }
}


def _rng() -> np.random.Generator:
    return np.random.default_rng(42)


# === Developmental-stage age brackets ===


@pytest.mark.parametrize(
    "age,expected",
    [
        (0, "infant"),
        (1, "infant"),
        (2, "infant"),  # the concrete iris4h-ai offender (POP-000004)
        (3, "preschool"),
        (5, "preschool"),
        (6, "elementary_student"),
        (11, "elementary_student"),
        (12, "middle_school_student"),
        (14, "middle_school_student"),
    ],
)
def test_minor_occupation_by_developmental_stage(age: int, expected: str) -> None:
    """The Issue #360 G7 core assertion: every age within the pre-fix
    ``student_max`` (0-14) bucket now returns a developmentally-
    appropriate label instead of the collapsed ``"student"``."""
    assert _sample_occupation(_DEMO, age, "F", _rng()) == expected


def test_two_year_old_never_returns_student() -> None:
    """Regression pin for the exact ``POP-000004 (2 歳)`` case flagged by
    iris4h-ai. Sample 20 times to catch any residual randomization
    (the helper is deterministic for ages < 3 so this is defense in depth)."""
    for _ in range(20):
        occ = _sample_occupation(_DEMO, 2, "F", _rng())
        assert occ != "student"
        assert occ == "infant"


# === RNG-preservation for older ages ===


def test_age_15_still_falls_through_to_working_age_split() -> None:
    """Age 15 (just above pre-fix ``student_max``) MUST NOT hit any of the
    new developmental brackets — the F4 memoize test relies on identical
    RNG consumption for ages >= 15."""
    result = _sample_occupation(_DEMO, 15, "M", _rng())
    # Age 15 falls through to the working-age dist (or "student" via the
    # young-adult-student branch). Either is acceptable; the point is
    # NONE of the developmental-stage labels reserved for younger ages
    # should appear.
    assert result not in {
        "infant",
        "preschool",
        "elementary_student",
        "middle_school_student",
    }


def test_adult_and_retiree_unchanged_from_pre_fix() -> None:
    """Regression pin: age 30 and age 70 (adult / retiree) go through
    the pre-fix branches unchanged. Guards against a future refactor
    that accidentally routes adults through a developmental bracket."""
    adult_occ = _sample_occupation(_DEMO, 30, "F", _rng())
    assert adult_occ in {"office", "healthcare", "service", "student"}
    retiree_occ = _sample_occupation(_DEMO, 70, "M", _rng())
    assert retiree_occ == "retired"


# === Localization dictionaries carry the new labels ===


@pytest.mark.parametrize(
    "occupation,ja,en",
    [
        ("infant", "乳児", "Infant"),
        ("preschool", "未就学児", "Preschool child"),
        ("elementary_student", "小学生", "Elementary school student"),
        ("middle_school_student", "中学生", "Middle school student"),
    ],
)
def test_new_occupation_labels_have_localizations(occupation: str, ja: str, en: str) -> None:
    """The new developmental-stage labels must have both JP and EN
    display translations in ``_fhir_localization`` — otherwise the JP
    Clinical Cockpit UI would fall back to the raw slug (defeating the
    G7 fix by replacing "学生" with "elementary_student" on the JP
    chart)."""
    assert _OCCUPATION_DISPLAY_JA.get(occupation) == ja
    assert _OCCUPATION_DISPLAY_EN.get(occupation) == en
