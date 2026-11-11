"""Issue #3002: a "<load> loading, then <maintenance>" drug is one loading dose
and a maintenance order.

The JP acute-MI regimen lists clopidogrel as "300mg loading, then 75mg PO
daily"; it used to become a daily 300 mg order. The admission orders now carry
a one-time 300 mg order and a 75 mg daily order that replaces it
(``prior_order_id``) and is given from the next day.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from clinosim.modules.order.engine import place_admission_orders
from clinosim.simulator.medication_pipeline import _generate_mar, apply_drug_safety_gate_to_admission_orders
from clinosim.types.encounter import OrderType
from clinosim.types.staff import StaffRoster

pytestmark = pytest.mark.unit

_ADM = datetime(2024, 4, 1, 20, 0)
_MI = Path("clinosim/modules/disease/reference_data/acute_mi.yaml")


def _orders(country: str, drug: str) -> list:
    protocol = yaml.safe_load(_MI.read_text(encoding="utf-8"))
    orders = place_admission_orders(protocol, "P1", "ENC-1", _ADM, country, np.random.default_rng(1))
    return [o for o in orders if o.order_type == OrderType.MEDICATION and o.display_name == drug]


def test_jp_clopidogrel_is_one_loading_order_and_a_maintenance_order() -> None:
    load, maint = _orders("japan", "Clopidogrel")
    assert (load.dose_quantity, load.dose_unit, load.single_dose) == (300.0, "mg", True)
    assert load.frequency.lower() == "once"
    assert (maint.dose_quantity, maint.dose_unit, maint.frequency_per_day, maint.single_dose) == (75.0, "mg", 1, False)
    assert maint.route == "PO"
    assert maint.prior_order_id == load.order_id
    assert maint.administer_from == datetime(2024, 4, 2)


def test_us_ticagrelor_keeps_the_maintenance_frequency() -> None:
    load, maint = _orders("us", "Ticagrelor")
    assert (load.dose_quantity, load.single_dose) == (180.0, True)
    assert (maint.dose_quantity, maint.frequency_per_day) == (90.0, 2)


def test_jp_regimen_gives_300_mg_once_then_75_mg_daily() -> None:
    patient = SimpleNamespace(
        patient_id="P1", current_medications=[], age=65, allergies=[], chronic_conditions=[], safety_skip_log=[]
    )
    orders = apply_drug_safety_gate_to_admission_orders(
        _orders("japan", "Clopidogrel"), patient, "ENC-1", _ADM, "D1", country="us"
    )
    assert len(orders) == 2, "the maintenance order is the loading order's continuation, not a second P2Y12"
    given: list = []
    for day in range(4):
        given += _generate_mar(patient, orders, day, _ADM, roster=StaffRoster(), rng=np.random.default_rng(day))
    doses = sorted((m.actual_datetime or m.scheduled_datetime, m.dose) for m in given)
    loading = [(t, d) for t, d in doses if d.startswith("300")]
    daily = [(t, d) for t, d in doses if d.startswith("75")]
    assert len(loading) == 1 and loading[0][0].date() == _ADM.date()
    assert [t.date() for t, _ in daily] == [(_ADM + timedelta(days=d)).date() for d in (1, 2, 3)]


def test_maintenance_request_runs_from_the_day_after_the_load() -> None:
    from clinosim.modules.output.fhir_r4.medications.medications import _apply_order_end

    mr = {"dosageInstruction": [{"timing": {"repeat": {"frequency": 1, "period": 1, "periodUnit": "d"}}}]}
    order = {"administer_from": "2024-04-02T00:00:00", "end_datetime": "2024-04-10T10:00:00"}
    _apply_order_end(mr, order, "2024-04-01T20:30:00+09:00")
    assert mr["dosageInstruction"][0]["timing"]["repeat"]["boundsPeriod"]["start"].startswith("2024-04-02T00:00:00")
