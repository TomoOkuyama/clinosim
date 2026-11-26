"""Issue #3896: the regimens a complication orders follow the severity and the
source (C. difficile), the IV PPI steps down to an oral one, and a held home
anticoagulant gets an explicit discharge decision.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from clinosim.simulator import daily_loop as dl
from clinosim.types.encounter import OrderResult, OrderStatus
from tests.unit.simulator.test_complication_treatment_3864 import (  # noqa: F401
    _CDIFF,
    ADMIT,
    ONSET_ORDER,
    _fire,
    _given,
    _meds,
    _run,
    _stay,
    _weight,
)

pytestmark = pytest.mark.unit


def _lab(run, name: str, value: float, unit: str) -> None:
    run.lab_results.append(
        OrderResult(
            result_datetime=ADMIT + timedelta(days=4, hours=2),
            performed_by="T",
            lab_name=name,
            value=value,
            unit=unit,
            flag="",
        )
    )


def _cdiff(monkeypatch, country: str, wbc: float | None = None, creatinine: float = 0.9):
    stay, run = _stay(country), _run(creatinine=creatinine)
    if wbc is not None:
        _lab(run, "WBC", wbc, "/uL")
    _fire(monkeypatch, stay, run, "c_diff_colitis", _CDIFF)
    return run


def _cdiff_orders(run):
    return [o for o in _meds(run, "antibiotic") if "-COMPTX-" in o.order_id]


def test_jp_non_severe_first_episode_gets_oral_metronidazole_500_mg_tid_for_10_days(monkeypatch) -> None:
    run = _cdiff(monkeypatch, "japan", wbc=9000.0)
    (order,) = _cdiff_orders(run)
    assert (order.drug_id, order.route, order.status) == ("metronidazole", "PO", OrderStatus.PLACED)
    assert (order.dose_quantity, order.dose_unit, order.frequency_per_day, order.duration_days) == (500.0, "mg", 3, 10)
    assert _given(run, order)


@pytest.mark.parametrize(("wbc", "creatinine"), [(15000.0, 0.9), (22000.0, 0.9), (9000.0, 1.6), (9000.0, 3.0)])
def test_jp_severe_cdi_gets_oral_vancomycin_125_mg_qid(monkeypatch, wbc, creatinine) -> None:
    run = _cdiff(monkeypatch, "japan", wbc=wbc, creatinine=creatinine)
    (order,) = _cdiff_orders(run)
    assert (order.drug_id, order.route) == ("vancomycin", "PO")
    assert (order.dose_quantity, order.frequency_per_day, order.duration_days) == (125.0, 4, 10)


@pytest.mark.parametrize(("wbc", "creatinine"), [(14999.0, 1.5), (None, 1.5), (None, 0.9)])
def test_jp_cdi_below_both_severity_limits_is_non_severe(monkeypatch, wbc, creatinine) -> None:
    run = _cdiff(monkeypatch, "japan", wbc=wbc, creatinine=creatinine)
    assert [o.drug_id for o in _cdiff_orders(run)] == ["metronidazole"]


@pytest.mark.parametrize("wbc", [None, 9000.0, 20000.0])
def test_us_cdi_keeps_oral_vancomycin_whatever_the_severity(monkeypatch, wbc) -> None:
    run = _cdiff(monkeypatch, "us", wbc=wbc)
    (order,) = _cdiff_orders(run)
    assert (order.drug_id, order.route, order.dose_quantity, order.frequency_per_day) == ("vancomycin", "PO", 125.0, 4)


def test_the_severity_is_read_at_the_onset_not_from_a_later_result(monkeypatch) -> None:
    stay, run = _stay("japan"), _run(creatinine=0.9)
    run.lab_results.append(
        OrderResult(
            result_datetime=ONSET_ORDER + timedelta(days=2),
            performed_by="T",
            lab_name="WBC",
            value=30000.0,
            unit="/uL",
            flag="",
        )
    )
    _fire(monkeypatch, stay, run, "c_diff_colitis", _CDIFF)
    assert [o.drug_id for o in _cdiff_orders(run)] == ["metronidazole"]


def test_metronidazole_course_continues_at_discharge_and_is_not_held() -> None:
    from clinosim.simulator.complication_actions import complication_discharge_specs
    from clinosim.types.encounter import Order, OrderType

    order = Order(
        order_id="ORD-E1-COMPTX-D4-c_diff_colitis-0",
        order_type=OrderType.MEDICATION,
        display_name="Metronidazole",
        drug_id="metronidazole",
        ordered_datetime=ONSET_ORDER,
        status=OrderStatus.PLACED,
        dose_quantity=500.0,
        dose_unit="mg",
        frequency="TID",
        frequency_per_day=3,
        route="PO",
        duration_days=10,
    )
    (spec,) = complication_discharge_specs([order], "japan", discharge_time=ONSET_ORDER + timedelta(days=4))
    assert (spec["drug_id"], spec["duration_days"], spec["from_complication"]) == ("metronidazole", 6, True)


def test_dl_module_still_exposes_the_loop() -> None:
    assert callable(dl._apply_complications)


def test_no_protocol_defines_a_lower_cdi_risk_alternative_so_the_stopped_antibiotic_is_not_replaced() -> None:
    """The stop of the inciting antibiotic orders a replacement only where the
    protocol authors a lower-risk alternative (``replacement_block``). No
    protocol does: when one adds the block this test fails, and the ordering of
    the replacement has to be implemented with it, not left silent."""
    from clinosim.simulator.complication_actions import complication_action_rules
    from tests.unit.simulator.test_complication_treatment_3864 import _complications  # noqa: F401

    block = complication_action_rules().stop_actions["stop_offending_antibiotic"].replacement_block
    assert block == "lower_cdi_risk_alternative"
    from pathlib import Path

    from clinosim.datafiles import load_data_yaml

    root = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "disease" / "reference_data"
    defining = [p.stem for p in sorted(root.glob("*.yaml")) if block in (load_data_yaml(p).get("drugs") or {})]
    assert defining == []


def test_the_stop_marker_says_no_replacement_antibiotic_is_ordered(monkeypatch) -> None:
    from clinosim.types.encounter import Order, OrderType

    stay = _stay()
    running = Order(
        order_id="ORD-E1-ADM-M02",
        order_type=OrderType.MEDICATION,
        display_name="Levofloxacin",
        drug_id="levofloxacin",
        ordered_datetime=ADMIT,
        status=OrderStatus.PLACED,
        dose_quantity=750.0,
        dose_unit="mg",
        frequency="DAILY",
        frequency_per_day=1,
        route="IV",
    )
    run = _run([running], creatinine=0.9)
    _fire(monkeypatch, stay, run, "c_diff_colitis", _CDIFF)
    (marker,) = [o for o in run.orders if o.display_name == "DISCONTINUE: Levofloxacin"]
    assert "no replacement antibiotic" in marker.clinical_intent
    assert "代わりの抗菌薬は発注しない" in marker.clinical_intent_ja
    # the hold of an anticoagulant keeps its own wording
    assert "replacement" not in dl.t("order_intent.complication_anticoagulant_hold", "en", day=4, complication="x")
