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


def test_stage_at_year_before_history_returns_empty():
    """Querying for a year BEFORE the earliest history entry returns
    "" (no stage known at that date — the person did not yet have
    the condition staged)."""
    p = _person_with_history()
    assert _stage_at_year(p, "N18", 2020) == ""
