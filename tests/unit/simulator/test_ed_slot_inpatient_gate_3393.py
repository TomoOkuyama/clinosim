"""An ED visit is not simulated while the person is admitted (Issue #3393)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.simulator.phases import _ed_slot

pytestmark = pytest.mark.unit

_WHEN = datetime(2025, 3, 10, 14, 0)


class _Stays:
    def __init__(self, active: object | None) -> None:
        self._active = active

    def active_at(self, _records, _person_id, _when):
        return self._active


def _run(monkeypatch: pytest.MonkeyPatch, active: object | None) -> tuple[list, list]:
    person = SimpleNamespace(in_population_at=lambda _d: True)
    activated: list = []
    simulated: list = []
    ctx = SimpleNamespace(
        population=SimpleNamespace(get_person=lambda _pid: person),
        inpatient_stays=_Stays(active),
        patient_records=[],
        patient_cache={},
        master_seed=1,
        demo=None,
        roster=None,
        config=SimpleNamespace(country="US"),
    )
    sampler = SimpleNamespace(ctx=ctx, conditions=[], condition=lambda _s: ({}, None))
    monkeypatch.setattr(_ed_slot, "_activate_cached_person", lambda *a, **k: activated.append(1) or object())
    monkeypatch.setattr(_ed_slot, "neonate_excluded", lambda *a, **k: False)
    monkeypatch.setattr(_ed_slot, "_simulate_ed_visit", lambda *a, **k: simulated.append(1) or "rec")
    slot = SimpleNamespace(when=_WHEN, person_id="P1", rng=None)
    _ed_slot.dispatch_ed_slot(slot, sampler)  # type: ignore[arg-type]
    assert ctx.patient_records == (["rec"] if simulated else [])
    return activated, simulated


def test_slot_inside_an_inpatient_stay_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    activated, simulated = _run(monkeypatch, active=object())
    assert simulated == []
    assert activated == []  # the person cache is not touched either


def test_slot_outside_any_stay_is_simulated(monkeypatch: pytest.MonkeyPatch) -> None:
    _activated, simulated = _run(monkeypatch, active=None)
    assert simulated == [1]
