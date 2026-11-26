"""One result per analyte per morning draw (Issue #3869).

The protocol's daily labs, the chronic-condition monitoring labs and the
complication monitoring labs are placed by three code paths. Each placed order
is resulted with its own noise, so two orders for one analyte in the same draw
gave two disagreeing values of one specimen. The three paths now share one
"already ordered for this draw" rule; deliberate repeats (qid/tid schedules,
hemolysis redraw, stat add-ons) are not collapsed.
"""

from __future__ import annotations

from datetime import datetime

from clinosim.modules.observation.order_routing import placed_lab_analytes
from clinosim.simulator.medication_pipeline import _place_chronic_monitoring_orders
from clinosim.types.encounter import Order, OrderStatus, OrderType

ADMIT = datetime(2025, 9, 1, 14, 0)
DRAW = datetime(2025, 9, 3, 5, 45)


def _lab(name: str, when: datetime = DRAW, oid: str = "X", status: OrderStatus = OrderStatus.PLACED) -> Order:
    return Order(
        order_id=f"ORD-E-{oid}-{name}",
        patient_id="P",
        order_type=OrderType.LAB,
        display_name=name,
        ordered_datetime=when,
        status=status,
    )


def _chronic(monitoring, drawn, day=2):
    return _place_chronic_monitoring_orders(
        monitoring, "P", day, ADMIT, None, encounter_id="E", ordered_by="DR", already_drawn=drawn
    )


def test_helper_collects_canonical_analytes_of_the_draw_including_panel_components() -> None:
    orders = [
        _lab("Creatinine"),
        _lab("CBC"),
        _lab("BNP", when=datetime(2025, 9, 3, 10, 0)),  # a different draw
        _lab("Potassium", status=OrderStatus.CANCELLED),
        Order(
            order_id="m", patient_id="P", order_type=OrderType.MEDICATION, display_name="Heparin", ordered_datetime=DRAW
        ),
    ]
    got = placed_lab_analytes(orders, DRAW)
    assert "Creatinine" in got
    assert {"WBC", "Hb", "Plt"} <= got  # CBC components
    assert "BNP" not in got
    assert "Potassium" not in got and "K" not in got
    assert "Heparin" not in got


def test_helper_resolves_aliases_to_the_canonical_name() -> None:
    assert placed_lab_analytes([_lab("PT-INR")], DRAW) == {"PT_INR"}


def test_chronic_daily_monitoring_skips_an_analyte_already_in_the_morning_draw() -> None:
    drawn = placed_lab_analytes([_lab("Creatinine")], DRAW)
    out = _chronic([{"test": "Creatinine", "frequency": "daily"}, {"test": "BNP", "frequency": "daily"}], drawn)
    assert [o.display_name for o in out] == ["BNP"]


def test_chronic_monitoring_skips_an_analyte_covered_by_a_panel_of_the_draw() -> None:
    drawn = placed_lab_analytes([_lab("BMP")], DRAW)
    assert _chronic([{"test": "Creatinine", "frequency": "daily"}], drawn) == []
    assert _chronic([{"test": "Glucose", "frequency": "daily"}], drawn) == []


def test_chronic_monitoring_unchanged_without_a_draw() -> None:
    out = _chronic([{"test": "Creatinine", "frequency": "daily"}], set())
    assert len(out) == 1
    assert len(_chronic([{"test": "Creatinine", "frequency": "daily"}], None)) == 1


def test_scheduled_repeats_are_not_collapsed() -> None:
    drawn = {"Glucose"}
    qid = _chronic([{"test": "Glucose", "frequency": "qid"}], drawn)
    tid = _chronic([{"test": "Glucose", "frequency": "tid"}], drawn)
    assert len(qid) == 4 and len(tid) == 3


def _daily(labs):
    import numpy as np

    from clinosim.modules.order.engine import place_daily_lab_orders

    protocol = {"order_protocols": {"daily_monitoring": {"labs": labs}}}
    return place_daily_lab_orders(protocol, "P", "E", 2, DRAW, 1.0, np.random.default_rng(0))


def test_protocol_scalar_lab_inside_a_listed_panel_is_not_ordered_again() -> None:
    orders = _daily([{"test": "BMP"}, {"test": "K"}, {"test": "Glucose"}, {"test": "CRP"}])
    names = [o.display_name for o in orders]
    assert "BMP" in names and "CRP" in names
    assert "K" not in names and "Glucose" not in names


def test_protocol_panel_overlapping_a_panel_is_kept_as_a_separate_specimen() -> None:
    names = [o.display_name for o in _daily([{"test": "BMP"}, {"test": "ABG_or_VBG"}])]
    assert names.count("BMP") == 1 and "ABG_or_VBG" in names


def test_protocol_scalar_listed_twice_is_ordered_once() -> None:
    names = [o.display_name for o in _daily([{"test": "CRP"}, {"test": "CRP"}])]
    assert names == ["CRP"]


def test_admission_workup_does_not_order_a_panel_member_again() -> None:
    import numpy as np

    from clinosim.modules.order.engine import place_admission_orders

    protocol = {"order_protocols": {"admission_orders": {"labs": [{"test": "BMP"}, {"test": "BUN"}, {"test": "CRP"}]}}}
    orders = place_admission_orders(protocol, "P", "E", ADMIT, "JP", np.random.default_rng(0))
    names = [o.display_name for o in orders if o.order_type == OrderType.LAB]
    assert "BUN" not in names and "BMP" in names and "CRP" in names
