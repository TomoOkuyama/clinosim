"""Issue #1757 — adult chronic onset events must not fire for a person who
ALREADY carries that chronic ICD at year-start.

Pre-fix repro: 384 patients had I10 in ``patient.chronic_conditions`` at
baseline AND re-added as ``new_complications`` in a subsequent year
(hypertension's i10_onset event fired despite the one_shot dedup check,
because that check compared the string ``emits_icd`` against a
``person_chronic`` list whose elements, in some data paths, are not plain
code strings but ``ChronicCondition``-shaped records, so the ``in`` test
returned False even though the code was present).

These tests exercise the ``step()`` dedup at the lowest level (no
``advance_one_year`` wrapping) so a regression surfaces regardless of
how the longitudinal engine marshalls the chronic list downstream.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.longitudinal.engine import advance_one_year, initial_snapshot
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.patterns.event import step
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helper: a lightweight stand-in for a ``ChronicCondition``-shaped record,
# used to prove the dedup is attribute-based rather than string-equality.
# ---------------------------------------------------------------------------


class _ChronicLike:
    """Shape-of-interest only — carries a ``.code`` attribute like
    ``clinosim.types.patient.ChronicCondition``. The dedup must accept
    this exactly as it accepts a plain code string."""

    def __init__(self, code: str) -> None:
        self.code = code


# ---------------------------------------------------------------------------
# Core repro: i10_onset must not fire when I10 is already in chronic list
# ---------------------------------------------------------------------------


def test_i10_onset_dedup_against_plain_string_chronic_list():
    """Baseline case: ``person_chronic`` is a plain ``list[str]``.
    One-shot dedup must suppress the fire across many RNG trials."""
    specs = load_attribute_specs()
    i10 = specs["i10_onset"]
    rng = np.random.default_rng(42)
    for _ in range(2000):
        result = step(
            ["I10", "E11.9"],
            [],
            rng,
            i10.body,
            context={"age": 60, "continuous": {}, "chronic_conditions": ["I10", "E11.9"]},
        )
        assert not result.fired, (
            "i10_onset.step() fired for a person who already carries I10 in chronic_conditions (plain-string list)."
        )


def test_i10_onset_dedup_against_chronic_condition_objects():
    """Repro of the #1757 bug: when ``person_chronic`` carries
    ``ChronicCondition``-shaped records (``.code`` attribute) rather than
    bare strings — the shape ``_derive_chronic_conditions`` produces for
    the PatientProfile view — the dedup must still suppress the fire."""
    specs = load_attribute_specs()
    i10 = specs["i10_onset"]
    rng = np.random.default_rng(42)
    chronic_objs = [_ChronicLike("I10"), _ChronicLike("E11.9")]
    fires = 0
    for _ in range(2000):
        result = step(
            chronic_objs,
            [],
            rng,
            i10.body,
            context={"age": 60, "continuous": {}, "chronic_conditions": chronic_objs},
        )
        if result.fired:
            fires += 1
    assert fires == 0, (
        f"i10_onset.step() fired {fires}/2000 trials for a person whose "
        f"chronic_conditions list carries ChronicCondition-shaped objects "
        f"containing I10 — the one_shot dedup must accept both shapes."
    )


# ---------------------------------------------------------------------------
# Spread check: every ``*_onset`` event behaves the same way
# ---------------------------------------------------------------------------


def test_every_onset_event_dedups_against_self_icd_in_chronic_list():
    """Comprehensive guard across the 30 adult-chronic onset yamls
    (Phase 4b.2.β). For each onset event, if the person already carries
    the ``emits_icd`` as a ``ChronicCondition``-shaped object, the event
    must not fire."""
    specs = load_attribute_specs()
    rng = np.random.default_rng(7)
    offenders: list[tuple[str, int]] = []
    for aid, spec in specs.items():
        if not aid.endswith("_onset"):
            continue
        emits_icd = getattr(spec.body, "emits_icd", "")
        if not emits_icd:
            continue
        chronic_objs = [_ChronicLike(emits_icd)]
        fires = 0
        for _ in range(500):
            result = step(
                chronic_objs,
                [],
                rng,
                spec.body,
                context={"age": 60, "continuous": {}, "chronic_conditions": chronic_objs},
            )
            if result.fired:
                fires += 1
        if fires > 0:
            offenders.append((aid, fires))
    assert not offenders, (
        f"{len(offenders)} onset events re-fire for a person already "
        f"carrying their emits_icd as a ChronicCondition-shaped object: "
        f"{offenders[:10]}"
    )


# ---------------------------------------------------------------------------
# Integration: advance_one_year over multiple years must never re-fire a
# baseline chronic. Mirrors the production ``advance_population`` call path.
# ---------------------------------------------------------------------------


def test_advance_one_year_does_not_re_fire_i10_for_baseline_i10_person():
    """Multi-year sweep across 50 patient seeds × 5 years. A patient
    whose ``chronic_conditions`` already contains ``I10`` at year 2024
    must never see ``I10`` appear in any subsequent year's
    ``new_complications``. Pre-fix, type-mismatched callers of the
    engine would allow this; the fix makes it structurally impossible
    regardless of the chronic list's element shape."""
    re_fires: list[tuple[int, int]] = []
    for seed in range(50):
        person = PersonRecord(
            person_id=f"P-REFIRE-{seed}",
            household_id="H",
            sex="M",
            age=60,
            date_of_birth=date(1964, 1, 1),
            chronic_conditions=["I10"],
        )
        initial_snapshot(person, 2024, np.random.default_rng(seed * 10))
        for yr in range(2025, 2030):
            snap = advance_one_year(person, year=yr, year_rng=np.random.default_rng(seed * 100 + yr))
            if "I10" in snap.new_complications:
                re_fires.append((seed, yr))
    assert not re_fires, (
        f"advance_one_year emitted I10 as a new complication for a "
        f"baseline-I10 person in {len(re_fires)} (seed, year) pairs: "
        f"{re_fires[:5]}"
    )
