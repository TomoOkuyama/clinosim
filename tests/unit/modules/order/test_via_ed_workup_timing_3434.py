"""Issue #3434: the work-up of a via-ED admission is ordered in the ED.

The ED period of a via-ED admission is ``[admission - admitted_ed_stay(),
admission]``. Labs, imaging and first-line drugs of the admission order set
are placed from the ED arrival (bounded by the ED end); ward orders stay at
the admission time. Only the anchor changes: the draws are the ones a stay
without an ED period consumes.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.order.engine import place_admission_orders
from clinosim.modules.triage.engine import admitted_ed_stay
from clinosim.types.encounter import OrderType

pytestmark = pytest.mark.unit

_ADM = datetime(2024, 4, 1, 20, 0)
_ED = (_ADM - admitted_ed_stay(), _ADM)


def _protocol() -> dict:
    return {
        "order_protocols": {
            "admission_orders": {
                "labs": [{"test": "CBC", "urgency": "stat"}, {"test": "Troponin_I", "urgency": "stat"}],
                "supportive": [
                    {"type": "IV_fluid", "detail": "NS 80 mL/h"},
                    {"type": "IV_fluid", "detail": "LR 30 mL/kg bolus over 3 hours"},
                    {"type": "bed_rest", "detail": "Bed rest"},
                    {"type": "bronchodilator", "detail": "Salbutamol 2.5mg nebulizer q4h"},
                ],
                "imaging": [{"test": "Chest_Xray", "urgency": "stat"}],
            }
        },
        "drugs": {"first_line": {"us": [{"drug": "Aspirin", "dose": "325mg PO once"}]}},
    }


def _place(ed_period, seed: int = 1):
    return place_admission_orders(
        _protocol(), "P1", "ENC-1", _ADM, "us", np.random.default_rng(seed), ed_period=ed_period
    )


def test_workup_orders_fall_inside_the_ed_period() -> None:
    orders = _place(_ED)
    workup = [o for o in orders if o.order_type in (OrderType.LAB, OrderType.IMAGING) or o.display_name == "Aspirin"]
    assert len(workup) >= 4
    for o in workup:
        assert _ED[0] <= o.ordered_datetime <= _ED[1], (o.display_name, o.ordered_datetime)


def test_initial_treatment_is_ordered_in_the_ed() -> None:
    orders = _place(_ED)
    (neb,) = [o for o in orders if o.display_name.startswith("bronchodilator")]
    assert _ED[0] <= neb.ordered_datetime <= _ED[1]


def test_fluid_bolus_is_ordered_in_the_ed_and_maintenance_fluid_on_the_ward() -> None:
    orders = _place(_ED)
    (bolus,) = [o for o in orders if "bolus" in o.display_name]
    (maintenance,) = [o for o in orders if "NS 80 mL/h" in o.display_name]
    assert _ED[0] <= bolus.ordered_datetime <= _ED[1]
    assert maintenance.ordered_datetime >= _ADM


def test_ward_orders_stay_at_the_admission_time() -> None:
    orders = _place(_ED)
    ward = [o for o in orders if "NS 80 mL/h" in o.display_name or o.display_name.startswith("bed_rest")]
    assert len(ward) == 2
    assert all(o.ordered_datetime >= _ADM for o in ward)


def test_order_time_is_bounded_by_the_ed_end() -> None:
    orders = _place((_ADM, _ADM))
    workup = [o for o in orders if o.order_type in (OrderType.LAB, OrderType.IMAGING)]
    assert workup
    assert all(o.ordered_datetime == _ADM for o in workup)


def test_reanchoring_moves_no_draw() -> None:
    """Same seed: the stream is left where the plain placement leaves it and
    every workup order keeps the offset its draw gave it."""
    rng_plain, rng_ed = np.random.default_rng(5), np.random.default_rng(5)
    plain = place_admission_orders(_protocol(), "P1", "ENC-1", _ADM, "us", rng_plain)
    anchored = place_admission_orders(_protocol(), "P1", "ENC-1", _ADM, "us", rng_ed, ed_period=_ED)
    assert rng_plain.random() == rng_ed.random()
    assert [o.order_id for o in plain] == [o.order_id for o in anchored]
    shift = _ED[0] - _ADM
    for p, a in zip(plain, anchored, strict=True):
        if (
            p.order_type in (OrderType.LAB, OrderType.IMAGING)
            or p.display_name in ("Aspirin",)
            or "bronchodilator" in p.display_name
            or "bolus" in p.display_name
        ):
            assert a.ordered_datetime == p.ordered_datetime + shift
        else:
            assert a.ordered_datetime == p.ordered_datetime
