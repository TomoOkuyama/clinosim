"""Issue #2648: the 24-hour fluid output counts more than urine."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim import determinism
from clinosim.simulator.vitals_pipeline import _generate_daily_io

pytestmark = pytest.mark.unit


def _io(day: int, seed: int = 7):
    state = SimpleNamespace(volume_status=1.0, inflammation_level=0.0, renal_function=1.0)
    patient = SimpleNamespace(patient_id="POP-000123")
    return _generate_daily_io(state, patient, day, datetime(2025, 3, 1, 9, 0), determinism.default_rng(seed))


def test_some_days_record_stool_output() -> None:
    days = [_io(d) for d in range(1, 15)]
    assert any(r.output_other_ml > 0 for r in days)
    assert any(r.output_other_ml == 0 for r in days)
    for r in days:
        assert r.net_balance_ml == r.intake_iv_ml + r.intake_oral_ml - (
            r.output_urine_ml + r.output_drain_ml + r.output_other_ml
        )


def test_other_output_does_not_draw_from_the_stay_stream() -> None:
    """Urine and intake come from the stay RNG exactly as before."""
    a, b = _io(5, seed=11), _io(5, seed=11)
    assert (a.intake_iv_ml, a.intake_oral_ml, a.output_urine_ml) == (
        b.intake_iv_ml,
        b.intake_oral_ml,
        b.output_urine_ml,
    )
    rng = determinism.default_rng(11)
    state = SimpleNamespace(volume_status=1.0, inflammation_level=0.0, renal_function=1.0)
    _generate_daily_io(state, SimpleNamespace(patient_id="POP-000123"), 5, datetime(2025, 3, 1, 9, 0), rng)
    after = rng.random()
    ref = determinism.default_rng(11)
    ref.normal(0, 1), ref.normal(0, 1), ref.normal(0, 1)  # iv, oral, urine
    assert after == ref.random()
