"""Issue #3019: eGFR is computed from serum creatinine, age and sex with the
country's equation, not scaled from the renal state.

Adults: JP — JSN (Matsuo 2009) 194 x Cr^-1.094 x age^-0.287 (x 0.739 female);
US — CKD-EPI 2021 race-free. Children: JP — Uemura 2013 (height-based
reference Cr, age 2-18); US — bedside Schwartz 0.413 x height / Cr (age 1-17).
Younger children have no Cr-based equation and get no eGFR.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.physiology.egfr import estimated_gfr

pytestmark = pytest.mark.unit


def test_jsn_cr_2_08_82_year_old_woman_is_about_18() -> None:
    assert estimated_gfr(2.08, 82, "F", 150.0, "JP") == pytest.approx(18.16, abs=0.05)


def test_jsn_male_has_no_female_factor() -> None:
    assert estimated_gfr(1.0, 50, "M", 170.0, "JP") == pytest.approx(194 * 50**-0.287, rel=1e-6)


def test_us_uses_ckd_epi_2021() -> None:
    # Female 60 y, Cr 1.0 → 64 (CKD-EPI 2021, Inker 2021); male 90 y, Cr 0.85 → 83.
    assert estimated_gfr(1.0, 60, "F", 160.0, "US") == pytest.approx(64.5, abs=0.1)
    assert estimated_gfr(0.85, 90, "M", 170.0, "US") == pytest.approx(82.5, abs=0.1)


def test_us_child_uses_bedside_schwartz() -> None:
    assert estimated_gfr(0.5, 8, "F", 128.0, "US") == pytest.approx(0.413 * 128 / 0.5)


def test_jp_child_uses_uemura_2013() -> None:
    x = 1.28
    ref_cr = -1.259 * x**5 + 7.815 * x**4 - 18.57 * x**3 + 21.39 * x**2 - 11.71 * x + 2.628
    assert estimated_gfr(0.5, 8, "M", 128.0, "JP") == pytest.approx(110.2 * ref_cr / 0.5 + 2.93)


@pytest.mark.parametrize(("age", "country"), [(1, "JP"), (0, "US")])
def test_no_equation_for_infants(age: int, country: str) -> None:
    assert estimated_gfr(0.3, age, "F", 75.0, country) is None


def test_true_labs_egfr_follows_true_creatinine() -> None:
    from clinosim.simulator.lab_pipeline import patient_true_labs
    from clinosim.types.clinical import PhysiologicalState

    patient = SimpleNamespace(
        sex="F",
        age=82,
        height_cm=150.0,
        address=SimpleNamespace(country="JP"),
        chronic_conditions=[],
        patient_id="P1",
        current_medications=[],
    )
    labs = patient_true_labs(PhysiologicalState(renal_function=0.3), patient, datetime(2026, 1, 5, 6), {})
    assert labs["eGFR"] == pytest.approx(estimated_gfr(labs["Creatinine"], 82, "F", 150.0, "JP"))


def test_reported_egfr_is_the_equation_on_the_same_draw_creatinine() -> None:
    from clinosim.simulator.lab_pipeline import relate_egfr_to_creatinine
    from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

    at = datetime(2026, 1, 5, 8)
    patient = SimpleNamespace(
        sex="F", age=82, height_cm=150.0, address=SimpleNamespace(country="JP"), current_medications=[]
    )

    def _order(oid: str, name: str, value: float) -> Order:
        return Order(
            order_id=oid,
            patient_id="P1",
            order_type=OrderType.LAB,
            display_name=name,
            status=OrderStatus.RESULTED,
            result=OrderResult(result_datetime=at, lab_name=name, value=value, unit=""),
        )

    cr, egfr = _order("O1", "Creatinine", 2.08), _order("O2", "eGFR", 110.0)
    relate_egfr_to_creatinine([cr, egfr], patient, "JP")
    assert egfr.result is not None
    assert egfr.result.value == 18
    assert egfr.result.flag == "L"


def test_an_infants_egfr_order_is_not_resulted() -> None:
    from clinosim.simulator.lab_pipeline import relate_egfr_to_creatinine
    from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

    patient = SimpleNamespace(sex="F", age=0, height_cm=70.0, address=SimpleNamespace(country="US"))
    order = Order(
        order_id="O2",
        patient_id="P1",
        order_type=OrderType.LAB,
        display_name="eGFR",
        status=OrderStatus.RESULTED,
        result=OrderResult(result_datetime=datetime(2026, 1, 5), lab_name="eGFR", value=100.0, unit=""),
    )
    dropped = relate_egfr_to_creatinine([order], patient, "US")
    assert order.status == OrderStatus.CANCELLED and order.result is None
    assert len(dropped) == 1
