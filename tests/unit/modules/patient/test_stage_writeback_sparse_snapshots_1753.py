"""Issue #1753 — longitudinal_history -> chronic_conditions[].stage writeback
miss. The engine's Markov pattern writes a stage into some but not every
yearly snapshot; the activator's ``_stage_at_year`` picked the latest
snapshot with year <= as_of_year even when that snapshot's
``chronic_stages`` dict did NOT contain the queried code. Result:
``chronic_conditions[].stage`` left empty for 93% of F00 dementia
carriers and 100% of C-chapter cancer carriers in the US p=10k seed=42
5-year cohort, even though the engine HAD computed a stage for them
elsewhere in longitudinal_history.

Fix: walk history snapshots in year order and return the stage from the
latest snapshot <= as_of_year that CONTAINS the code. If no snapshot
<= as_of_year has the code, fall back to the earliest snapshot that
does (forward-clamp — the engine assigned the stage after the as_of
year, but the condition is already on the problem list, so the stage
is still the best available information).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest

from clinosim.modules.patient.activator import _stage_at_year

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Lightweight stubs — avoid touching PersonRecord's full dataclass contract.
# ---------------------------------------------------------------------------


@dataclass
class _SnapStub:
    year: int
    chronic_stages: dict[str, str] = field(default_factory=dict)


@dataclass
class _PersonStub:
    longitudinal_history: list[_SnapStub]
    date_of_birth: date = date(1960, 1, 1)
    person_id: str = "P-TEST"


# ---------------------------------------------------------------------------
# Repro cases from the Issue
# ---------------------------------------------------------------------------


def test_stage_written_in_later_year_than_as_of_falls_back_to_latest_prior_hit():
    """The engine wrote F00 'mild' in year 2026. The caller queries
    as_of_year=2027. Pre-fix: year-2027 snapshot has empty
    chronic_stages so returns ''. Post-fix: walks back to year 2026
    which HAS the stage and returns 'mild'."""
    person = _PersonStub(
        longitudinal_history=[
            _SnapStub(year=2024, chronic_stages={}),
            _SnapStub(year=2025, chronic_stages={}),
            _SnapStub(year=2026, chronic_stages={"F00": "mild"}),
            _SnapStub(year=2027, chronic_stages={}),  # engine didn't write F00 this year
        ],
    )
    assert _stage_at_year(person, "F00", 2027) == "mild"


def test_stage_sparse_snapshots_walks_back_to_latest_hit():
    """Cancer stage-ladder scenario: AJCC stage was set in 2025 and
    then only re-written on event-years (progression). Interrogate
    year 2028: pre-fix empty, post-fix 'IIB'."""
    person = _PersonStub(
        longitudinal_history=[
            _SnapStub(year=2024, chronic_stages={}),
            _SnapStub(year=2025, chronic_stages={"C50": "IIA"}),
            _SnapStub(year=2026, chronic_stages={}),
            _SnapStub(year=2027, chronic_stages={"C50": "IIB"}),  # progression
            _SnapStub(year=2028, chronic_stages={}),  # stable, no re-write
        ],
    )
    assert _stage_at_year(person, "C50", 2028) == "IIB"


def test_as_of_year_before_any_stage_write_forward_clamps():
    """as_of=2024 is before any snapshot that carries the stage. Pre-fix
    returned '' (the year-2024 snapshot's chronic_stages is empty).
    Post-fix: forward-clamp to the earliest snapshot that HAS the code
    so the chronic condition carries SOME stage (better than ``''``,
    which the downstream narrative renders as 'stage unknown')."""
    person = _PersonStub(
        longitudinal_history=[
            _SnapStub(year=2024, chronic_stages={}),
            _SnapStub(year=2025, chronic_stages={"F00": "mild"}),
            _SnapStub(year=2026, chronic_stages={"F00": "moderate"}),
        ],
    )
    assert _stage_at_year(person, "F00", 2024) == "mild"


def test_stage_present_in_requested_year_still_prefers_requested():
    """When the requested year's snapshot DOES carry the stage, return
    it verbatim. The post-fix walk must not skip over the year-exact hit."""
    person = _PersonStub(
        longitudinal_history=[
            _SnapStub(year=2024, chronic_stages={"F00": "mild"}),
            _SnapStub(year=2025, chronic_stages={"F00": "moderate"}),
            _SnapStub(year=2026, chronic_stages={"F00": "severe"}),
        ],
    )
    assert _stage_at_year(person, "F00", 2025) == "moderate"


def test_as_of_year_none_returns_latest_hit():
    """as_of_year=None should return the most recent stage write
    (walks back from end). Pre-fix just returned history[-1]'s dict
    lookup, which would be '' if the engine stopped re-writing."""
    person = _PersonStub(
        longitudinal_history=[
            _SnapStub(year=2024, chronic_stages={"I48": "Permanent"}),
            _SnapStub(year=2025, chronic_stages={}),
            _SnapStub(year=2026, chronic_stages={}),
        ],
    )
    assert _stage_at_year(person, "I48", None) == "Permanent"


def test_empty_history_returns_empty_string():
    person = _PersonStub(longitudinal_history=[])
    assert _stage_at_year(person, "F00", 2025) == ""
    assert _stage_at_year(person, "F00", None) == ""


def test_code_absent_from_every_snapshot_returns_empty():
    """Legitimate 'no stage was ever assigned' case — the code is on the
    problem list but the engine never computed a stage for it. Should
    return '' honestly rather than inventing one."""
    person = _PersonStub(
        longitudinal_history=[
            _SnapStub(year=2024, chronic_stages={"I48": "Paroxysmal"}),
            _SnapStub(year=2025, chronic_stages={"I48": "Permanent"}),
        ],
    )
    assert _stage_at_year(person, "F00", 2025) == ""


def test_as_of_year_before_first_history_year_returns_empty():
    """Pre-scope invariant: when ``as_of_year`` precedes the earliest
    longitudinal snapshot, the person had not yet entered the
    longitudinal engine's scope for this disease; return ``""``. This
    is distinct from the ``test_as_of_year_before_any_stage_write_forward_clamps``
    case, which has a prior-year snapshot that merely lacks the stage
    (vs. no prior-year snapshot at all)."""
    person = _PersonStub(
        longitudinal_history=[
            _SnapStub(year=2025, chronic_stages={"F00": "mild"}),
            _SnapStub(year=2026, chronic_stages={"F00": "moderate"}),
        ],
    )
    assert _stage_at_year(person, "F00", 2024) == ""


# ---------------------------------------------------------------------------
# Backward compat / sentinel: pre-#1753 call sites that happened to work
# because the latest snapshot had the stage must continue to work.
# ---------------------------------------------------------------------------


def test_dense_history_latest_year_hit_backward_compat():
    """CKD / COPD / HbA1c-style dense writeback where every snapshot
    carries the stage — ``_stage_at_year(as_of=latest)`` returns the
    latest-year stage, same as pre-fix."""
    person = _PersonStub(
        longitudinal_history=[
            _SnapStub(year=2024, chronic_stages={"N18": "CKD G2"}),
            _SnapStub(year=2025, chronic_stages={"N18": "CKD G3a"}),
            _SnapStub(year=2026, chronic_stages={"N18": "CKD G3b"}),
        ],
    )
    assert _stage_at_year(person, "N18", 2026) == "CKD G3b"
    assert _stage_at_year(person, "N18", 2025) == "CKD G3a"
    assert _stage_at_year(person, "N18", None) == "CKD G3b"
