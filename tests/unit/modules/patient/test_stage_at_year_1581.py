"""Issue #1581 — encounter-time stage lookup via disease_stage_history."""

from __future__ import annotations

from datetime import date

from clinosim.modules.patient.activator import _stage_at_year
from clinosim.types.population import PersonRecord


def _person_with_history() -> PersonRecord:
    p = PersonRecord(
        person_id="PT-STAGE-1",
        household_id="HH-1",
        age=70,
        sex="M",
        date_of_birth=date(1954, 1, 1),
        chronic_conditions=["N18"],
    )
    p.disease_stages["N18"] = "CKD G5"
    p.disease_stage_history["N18"] = {
        2024: "CKD G2",
        2025: "CKD G3a",
        2026: "CKD G3b",
        2027: "CKD G4",
        2028: "CKD G5",
    }
    return p


def test_stage_at_year_returns_year_match():
    p = _person_with_history()
    assert _stage_at_year(p, "N18", 2024) == "CKD G2"
    assert _stage_at_year(p, "N18", 2026) == "CKD G3b"
    assert _stage_at_year(p, "N18", 2028) == "CKD G5"


def test_stage_at_year_floors_to_latest_prior():
    """Querying for a year with no exact history entry returns the
    stage at the latest history year ≤ the query year."""
    p = _person_with_history()
    p.disease_stage_history["N18"] = {2024: "CKD G2", 2028: "CKD G5"}  # sparse
    assert _stage_at_year(p, "N18", 2024) == "CKD G2"
    assert _stage_at_year(p, "N18", 2025) == "CKD G2"
    assert _stage_at_year(p, "N18", 2027) == "CKD G2"
    assert _stage_at_year(p, "N18", 2028) == "CKD G5"
    assert _stage_at_year(p, "N18", 2029) == "CKD G5"


def test_stage_at_year_fallback_to_latest_without_as_of_year():
    """as_of_year=None preserves pre-#1581 behaviour (latest-only)."""
    p = _person_with_history()
    assert _stage_at_year(p, "N18", None) == "CKD G5"


def test_stage_at_year_fallback_when_history_empty():
    """A code with no history entry falls back to the latest
    disease_stages dict value."""
    p = _person_with_history()
    p.disease_stage_history = {}
    assert _stage_at_year(p, "N18", 2024) == "CKD G5"


def test_glycemic_control_at_year_floor_match():
    """DM glycemic trajectory lookup — year match + floor-match
    semantics match the stage-history lookup."""
    from clinosim.modules.patient.activator import _glycemic_control_at_year

    p = PersonRecord(
        person_id="PT-DM-1",
        household_id="HH-1",
        age=65,
        sex="M",
        date_of_birth=date(1961, 1, 1),
        chronic_conditions=["E11.9"],
    )
    p.glycemic_trajectory = {2024: 0.80, 2026: 0.70, 2028: 0.55}
    assert _glycemic_control_at_year(p, 2024) == 0.80
    # Floor-match: 2025 → latest ≤ 2025 → 2024.
    assert _glycemic_control_at_year(p, 2025) == 0.80
    assert _glycemic_control_at_year(p, 2026) == 0.70
    assert _glycemic_control_at_year(p, 2027) == 0.70
    assert _glycemic_control_at_year(p, 2028) == 0.55
    # as_of_year=None → latest.
    assert _glycemic_control_at_year(p, None) == 0.55
    # Before earliest → None (not yet diagnosed).
    assert _glycemic_control_at_year(p, 2020) is None


def test_glycemic_control_at_year_empty_trajectory_returns_none():
    """A person without any trajectory entries returns None, so the
    activator falls through to its legacy ``gc = 1 - rand()^3``
    sampling path."""
    from clinosim.modules.patient.activator import _glycemic_control_at_year

    p = PersonRecord(
        person_id="PT-DM-EMPTY-1",
        household_id="HH-1",
        age=65,
        sex="M",
        date_of_birth=date(1961, 1, 1),
    )
    assert _glycemic_control_at_year(p, 2024) is None
    assert _glycemic_control_at_year(p, None) is None


def test_stage_at_year_before_history_returns_empty():
    """Querying for a year BEFORE the earliest history entry returns
    "" (no stage known at that date — the person did not yet have
    the condition staged)."""
    p = _person_with_history()
    assert _stage_at_year(p, "N18", 2020) == ""
