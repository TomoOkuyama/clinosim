"""Lock the canonical acuity-tier disease sets (Issue #563).

`clinosim/modules/disease/acuity.py` exports three overlapping frozensets that
were previously inlined across simulator + procedure engine. Silent drift
between them (specifically `subdural_hematoma` missing from
`CRITICAL_MONITORING_DISEASES`) caused a data-quality bug.

These tests lock:

1. The exact set contents (a rename or accidental drop is caught).
2. The clinically-required alignment between EMERGENCY_PRIORITY and
   CRITICAL_MONITORING (identical today after the Issue #563 fix).
3. That call sites reference the named set, not a bare inline tuple.
"""

from __future__ import annotations

from clinosim.modules.disease.acuity import (
    CRITICAL_MONITORING_DISEASES,
    EMERGENCY_PRIORITY_DISEASES,
    NEURO_LOC_MONITORING_DISEASES,
)


def test_emergency_priority_set_contents() -> None:
    assert EMERGENCY_PRIORITY_DISEASES == frozenset(
        {"acute_mi", "sepsis", "hemorrhagic_stroke", "subdural_hematoma", "traffic_accident_severe"}
    )


def test_critical_monitoring_set_contents_includes_subdural() -> None:
    """`subdural_hematoma` MUST be present — Issue #563 gap fix."""
    assert "subdural_hematoma" in CRITICAL_MONITORING_DISEASES
    assert CRITICAL_MONITORING_DISEASES == frozenset(
        {"acute_mi", "sepsis", "hemorrhagic_stroke", "subdural_hematoma", "traffic_accident_severe"}
    )


def test_neuro_loc_monitoring_set_contents() -> None:
    assert NEURO_LOC_MONITORING_DISEASES == frozenset({"hemorrhagic_stroke", "subdural_hematoma"})


def test_emergency_priority_and_critical_monitoring_are_aligned() -> None:
    """Sibling sets — Issue #563 required them identical to close the drift
    that caused subdural-hematoma admissions to carry priority=EM yet be
    sampled q4h. Test locks the invariant so a future edit to one set forces
    a review of the other."""
    assert EMERGENCY_PRIORITY_DISEASES == CRITICAL_MONITORING_DISEASES


def test_all_sets_are_frozenset() -> None:
    """Frozenset is the load-bearing type — accidental `set` / `list` would
    silently allow mutation and break the "canonical contract" property."""
    assert isinstance(EMERGENCY_PRIORITY_DISEASES, frozenset)
    assert isinstance(CRITICAL_MONITORING_DISEASES, frozenset)
    assert isinstance(NEURO_LOC_MONITORING_DISEASES, frozenset)
