"""Issue #2640: every culture result comes from a culture order, and every culture order is resulted."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.observation.microbiology import culture_draws, culture_results, specimen_for_order
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit

_T = datetime(2025, 4, 21, 15, 14)


def _order(name: str, when: datetime, status: OrderStatus = OrderStatus.PLACED, oid: str = "") -> Order:
    return Order(
        order_id=oid or f"O-{name}-{when:%d%H%M}",
        encounter_id="ENC-1",
        order_type=OrderType.LAB,
        display_name=name,
        ordered_datetime=when,
        status=status,
    )


def test_culture_orders_name_their_specimen() -> None:
    assert specimen_for_order("Blood_culture_repeat") == "blood"
    assert specimen_for_order("Sputum_culture") == "sputum"
    assert specimen_for_order("Urine_culture") == "urine"
    assert specimen_for_order("CBC") == ""


def test_each_draw_is_one_culture_at_its_order_time() -> None:
    orders = [
        _order("Blood_culture", _T, oid="a"),
        _order("Blood_culture", _T, oid="b"),  # second set of the same draw
        _order("Sputum_culture", _T + timedelta(minutes=5)),
        _order("Blood_culture_repeat", _T + timedelta(days=4)),
        _order("Urine_culture", _T, status=OrderStatus.CANCELLED),
        _order("CBC", _T),
    ]
    draws = culture_draws(orders, "ENC-1")
    assert draws == [("blood", _T), ("sputum", _T + timedelta(minutes=5)), ("blood", _T + timedelta(days=4))]
    results = culture_results("bacterial_pneumonia", draws, "ENC-1", 42)
    assert [(r.specimen, r.collected_datetime) for r in results] == draws


def test_a_disease_without_a_profile_has_no_growth() -> None:
    results = culture_results("hip_fracture", [("urine", _T)], "ENC-1", 42)
    assert len(results) == 1 and results[0].growth is False


def test_repeat_draw_after_a_negative_culture_is_no_growth() -> None:
    for i in range(40):
        first, repeat = culture_results("sepsis", [("blood", _T), ("blood", _T + timedelta(days=3))], f"E{i}", 7)
        if not first.growth:
            assert repeat.growth is False
        elif repeat.growth:
            assert repeat.organism_snomed == first.organism_snomed


def test_hai_culture_is_ordered_at_collection() -> None:
    from types import SimpleNamespace

    from clinosim.determinism import default_rng
    from clinosim.modules.hai.enricher import _append_hai_culture
    from clinosim.modules.output.fhir_r4.labs.microbiology import culture_orders_for

    rec = SimpleNamespace(patient=SimpleNamespace(patient_id="p1"), encounters=[], microbiology=[], orders=[])
    hai = SimpleNamespace(encounter_id="ENC-1", hai_id="hai-1", hai_type="cauti", organism_snomed="112283007")
    spec = {"specimen": "urine", "specimen_snomed": "122575003", "test_loinc": "630-4"}
    _append_hai_culture(rec, hai, spec, "2025-01-31", {}, default_rng(1))
    assert [o.display_name for o in rec.orders] == ["Urine_culture"]
    assert culture_orders_for(rec.microbiology[0], rec.orders) == rec.orders
