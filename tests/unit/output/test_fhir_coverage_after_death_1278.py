"""Issue #1278: Coverage lifecycle reconciliation on patient death.

`_derive_coverage_status` (Issue #944) flips ``Coverage.status`` based
on ``period.end`` vs the simulation snapshot date. It has no visibility
into the patient's ``deceasedDateTime``, so at p=10k s=354 audit ~92 %
of deceased patients kept a ``period.end`` past DOD and 36-60 % kept
``status="active"`` — real payers cancel enrollment at DOD.

`_drop_entries_after_death` already treats Coverage as start-gated
(Issue #1219): rows starting after DOD drop, everything else survives.
This test locks in the added reconciliation step: for surviving
Coverage rows, clamp ``period.end`` to DOD and flip ``status`` to
``"cancelled"``.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4 import _drop_entries_after_death

pytestmark = pytest.mark.unit


def _entry(resource: dict) -> dict:
    return {"resource": resource}


def test_coverage_period_end_after_dod_clamped_to_dod() -> None:
    coverage = {
        "resourceType": "Coverage",
        "id": "cov-1",
        "status": "active",
        "period": {"start": "2026-01-01", "end": "2026-12-31"},
    }
    kept = _drop_entries_after_death([_entry(coverage)], "2026-04-26")
    assert len(kept) == 1
    resource = kept[0]["resource"]
    assert resource["period"]["start"] == "2026-01-01"
    assert resource["period"]["end"] == "2026-04-26"


def test_coverage_status_active_flipped_to_cancelled_on_death() -> None:
    coverage = {
        "resourceType": "Coverage",
        "id": "cov-2",
        "status": "active",
        "period": {"start": "2026-01-01", "end": "2026-12-31"},
    }
    kept = _drop_entries_after_death([_entry(coverage)], "2026-04-26")
    assert kept[0]["resource"]["status"] == "cancelled"


def test_coverage_period_end_before_dod_left_intact() -> None:
    """A pre-DOD FY row is not touched — it already ended in the patient's lifetime."""
    coverage = {
        "resourceType": "Coverage",
        "id": "cov-3",
        "status": "cancelled",
        "period": {"start": "2024-04-01", "end": "2025-03-31"},
    }
    kept = _drop_entries_after_death([_entry(coverage)], "2026-04-26")
    assert kept[0]["resource"]["period"]["end"] == "2025-03-31"
    assert kept[0]["resource"]["status"] == "cancelled"


def test_coverage_starting_after_dod_dropped() -> None:
    """Preserves the Issue #1219 gate: an enrolment starting after DOD is bogus."""
    coverage = {
        "resourceType": "Coverage",
        "id": "cov-4",
        "status": "active",
        "period": {"start": "2026-05-01", "end": "2027-03-31"},
    }
    kept = _drop_entries_after_death([_entry(coverage)], "2026-04-26")
    assert kept == []


def test_coverage_status_cancelled_stays_cancelled() -> None:
    """Rows already cancelled are not re-flipped (idempotent reconciliation)."""
    coverage = {
        "resourceType": "Coverage",
        "id": "cov-5",
        "status": "cancelled",
        "period": {"start": "2026-01-01", "end": "2026-12-31"},
    }
    kept = _drop_entries_after_death([_entry(coverage)], "2026-04-26")
    assert kept[0]["resource"]["status"] == "cancelled"
    assert kept[0]["resource"]["period"]["end"] == "2026-04-26"


def test_coverage_without_period_end_left_alone() -> None:
    coverage = {
        "resourceType": "Coverage",
        "id": "cov-6",
        "status": "active",
        "period": {"start": "2026-01-01"},
    }
    kept = _drop_entries_after_death([_entry(coverage)], "2026-04-26")
    resource = kept[0]["resource"]
    assert "end" not in resource["period"]
    assert resource["status"] == "cancelled"
