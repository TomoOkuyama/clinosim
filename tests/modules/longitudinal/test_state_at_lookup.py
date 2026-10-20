"""`state_at(person, when)` lookup semantics.

Pure function; no RNG. See Phase 1 plan Task 4 brief for the API
contract and spec §5.1 for the signature.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from clinosim.modules.longitudinal import loader as loader_mod
from clinosim.modules.longitudinal.engine import state_at
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.snapshot import YearSnapshot
from clinosim.types.population import PersonRecord


@pytest.fixture(autouse=True)
def _clear_loader_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`state_at` is pure — isolate from any real yaml so these tests
    cannot be perturbed by future attribute additions."""
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    load_attribute_specs.cache_clear()


def _mk_person_with_history(years: list[int]) -> PersonRecord:
    p = PersonRecord(
        person_id="P1",
        household_id="HH1",
        age=55,
        sex="M",
        date_of_birth=date(1969, 6, 1),
    )
    p.longitudinal_history = [YearSnapshot(year=y, continuous={"hba1c": 7.0 + 0.1 * (y - years[0])}) for y in years]
    return p


@pytest.mark.unit
def test_state_at_resolves_integer_year() -> None:
    p = _mk_person_with_history([2021, 2022, 2023])
    snap = state_at(p, 2022)
    assert snap.year == 2022


@pytest.mark.unit
def test_state_at_resolves_datetime_year_component() -> None:
    p = _mk_person_with_history([2021, 2022, 2023])
    snap = state_at(p, datetime(2022, 6, 15, 10, 0))
    assert snap.year == 2022


@pytest.mark.unit
def test_state_at_resolves_date_year_component() -> None:
    p = _mk_person_with_history([2021, 2022, 2023])
    snap = state_at(p, date(2023, 1, 2))
    assert snap.year == 2023


@pytest.mark.unit
def test_state_at_raises_on_empty_state_history() -> None:
    p = PersonRecord(
        person_id="P-empty",
        household_id="HH1",
        age=55,
        sex="M",
        date_of_birth=date(1969, 6, 1),
    )
    with pytest.raises(IndexError, match="P-empty"):
        state_at(p, 2022)


@pytest.mark.unit
def test_state_at_raises_before_range() -> None:
    p = _mk_person_with_history([2021, 2022, 2023])
    with pytest.raises(IndexError, match="2020"):
        state_at(p, 2020)


@pytest.mark.unit
def test_state_at_raises_after_range() -> None:
    p = _mk_person_with_history([2021, 2022, 2023])
    with pytest.raises(IndexError, match="2025"):
        state_at(p, 2025)


@pytest.mark.unit
def test_year_boundary_encounters_resolve_to_correct_snapshot() -> None:
    """Review Focus 1. December-31 → year y; January-1 next year →
    year y+1. Year-granularity means intra-year encounters resolve
    to the same snapshot; cross-year boundary flips."""
    p = _mk_person_with_history([2022, 2023])
    dec31 = state_at(p, datetime(2022, 12, 31, 23, 59, 59))
    jan1 = state_at(p, datetime(2023, 1, 1, 0, 0, 0))
    assert dec31.year == 2022
    assert jan1.year == 2023


@pytest.mark.unit
def test_state_at_rejects_unsupported_when_type() -> None:
    p = _mk_person_with_history([2022])
    with pytest.raises(TypeError, match="when"):
        state_at(p, "2022")  # type: ignore[arg-type]
