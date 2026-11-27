"""Issue #3921: a rehabilitation session lies inside its inpatient stay; one
that cannot fit is dropped, never dated after discharge."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from clinosim.modules.procedure.engine import generate_rehab_sessions
from clinosim.simulator.encounter_setup import fit_rehab_sessions_in_stay
from clinosim.types.procedure import RehabSession

pytestmark = pytest.mark.unit

_ADMIT = datetime(2026, 3, 10, 9, 0)


def _session(start: datetime, minutes: int = 40) -> RehabSession:
    return RehabSession(session_id=f"S-{start:%d%H}", session_date=start, duration_minutes=minutes)


def test_session_after_discharge_is_dropped_and_the_rest_kept() -> None:
    end = _ADMIT + timedelta(days=5, hours=0, minutes=42)
    sessions = [_session(_ADMIT + timedelta(days=d, hours=1)) for d in range(1, 9)]
    kept = fit_rehab_sessions_in_stay(sessions, _ADMIT, end)
    assert [s.session_date for s in kept] == [s.session_date for s in sessions if s.session_date <= end]
    assert all(s.session_date + timedelta(minutes=s.duration_minutes) <= end for s in kept)
    assert len(kept) < len(sessions)


def test_session_that_runs_past_discharge_is_dropped() -> None:
    end = _ADMIT + timedelta(days=2, hours=1, minutes=30)
    s = _session(_ADMIT + timedelta(days=2, hours=1), minutes=40)  # would end 10 minutes after discharge
    assert fit_rehab_sessions_in_stay([s], _ADMIT, end) == []


def test_stay_in_progress_keeps_every_session() -> None:
    sessions = [_session(_ADMIT + timedelta(days=d)) for d in range(1, 4)]
    assert fit_rehab_sessions_in_stay(sessions, _ADMIT, None) == sessions


def test_session_before_admission_is_dropped() -> None:
    assert fit_rehab_sessions_in_stay([_session(_ADMIT - timedelta(hours=1))], _ADMIT, _ADMIT + timedelta(days=3)) == []


def test_generation_draw_count_is_unchanged_by_the_fit() -> None:
    """The fit runs after generation, so the master stream is where it was."""
    a, b = np.random.default_rng(7), np.random.default_rng(7)
    full = generate_rehab_sessions("P", "E", _ADMIT, 12, a, "JP")
    fit_rehab_sessions_in_stay(full, _ADMIT, _ADMIT + timedelta(days=4))
    again = generate_rehab_sessions("P", "E", _ADMIT, 12, b, "JP")
    assert [s.session_id for s in full] == [s.session_id for s in again]
    assert a.random() == b.random()


@pytest.mark.e2e
def test_hip_fracture_stays_have_no_rehab_session_after_discharge() -> None:
    from clinosim.simulator import run_forced
    from clinosim.types.config import ForcedScenario

    checked = 0
    for r in run_forced(ForcedScenario(disease_id="hip_fracture", count=6)).patients:
        stay = next(e for e in r.encounters if e.encounter_type.name == "INPATIENT")
        for s in r.rehab_sessions:
            if s.encounter_id != stay.encounter_id:
                continue
            checked += 1
            assert stay.admission_datetime <= s.session_date
            if stay.discharge_datetime is not None:
                assert s.session_date + timedelta(minutes=s.duration_minutes) <= stay.discharge_datetime
    assert checked
