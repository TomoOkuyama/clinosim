"""A diagnosed delivery complication leaves a trace in the record: vital signs,
laboratory results and orders (Issue #3662). A delivery without a complication
is unchanged."""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import drug_ref
from clinosim.locale.loader import load_code_mapping, load_perinatal_config
from tests.unit.simulator.test_perinatal_complication_coding import _CESAREAN, _VAGINAL, _deliver

pytestmark = pytest.mark.unit


def _labs(rec) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in rec.lab_results:
        out.setdefault(r.lab_name, []).append(r.value)
    return out


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("pid", [_VAGINAL, _CESAREAN])
def test_preeclampsia_has_hypertension_labs_and_treatment(pid: str, country: str) -> None:
    rec = _deliver(pid, ["O14.9"], country=country)
    enc = rec.encounters[0]
    hypertensive = [v for v in rec.vital_signs if v.systolic_bp >= 140 or v.diastolic_bp >= 90]
    assert len(hypertensive) >= 3
    labs = _labs(rec)
    assert {"Plt", "AST", "ALT", "Creatinine"} <= set(labs)
    names = {o.display_name for o in rec.orders}
    assert {"Magnesium Sulfate", "Labetalol"} <= names
    for r in rec.lab_results:
        assert enc.admission_datetime <= r.result_datetime < enc.discharge_datetime
    for o in rec.orders:
        assert o.ordered_datetime >= enc.admission_datetime
        assert o.encounter_id == enc.encounter_id
        if o.order_type.value == "lab":
            assert o.result is not None and o.result in rec.lab_results
    mar_orders = {m.order_id for m in rec.medication_administrations}
    mg = [o for o in rec.orders if o.display_name == "Magnesium Sulfate"]
    assert mg and all(o.order_id in mar_orders for o in mg)
    assert len({o.order_id for o in rec.orders}) == len(rec.orders)


def test_gestational_diabetes_has_glucose_results() -> None:
    labs = _labs(_deliver(_VAGINAL, ["O24.9"]))
    assert labs["Glucose"] and all(g >= 100 for g in labs["Glucose"])
    assert "HbA1c" in labs


def test_premature_rupture_has_infection_markers() -> None:
    assert {"WBC", "CRP"} <= set(_labs(_deliver(_VAGINAL, ["O42.9"])))


@pytest.mark.parametrize("pid", [_VAGINAL, _CESAREAN])
def test_delivery_without_an_applicable_complication_is_unchanged(pid: str) -> None:
    plain = _deliver(pid, [])
    dropped = _deliver(pid, ["O60.1"])  # dropped at term: no effect applies
    assert plain.lab_results == [] and dropped.lab_results == []
    assert [o.order_id for o in plain.orders] == [o.order_id for o in dropped.orders]
    assert plain.vital_signs == dropped.vital_signs


def test_other_vitals_of_a_complicated_delivery_keep_the_shared_stream() -> None:
    """Only the sets inside the effect window are overridden, and only their BP."""
    plain = _deliver(_VAGINAL, [])
    pre = _deliver(_VAGINAL, ["O14.9"])
    assert len(plain.vital_signs) == len(pre.vital_signs)
    for a, b in zip(plain.vital_signs, pre.vital_signs, strict=True):
        assert (a.timestamp, a.heart_rate, a.temperature_celsius) == (b.timestamp, b.heart_rate, b.temperature_celsius)


def test_effect_rows_resolve_in_both_countries() -> None:
    effects = load_perinatal_config()["complications"]["effects"]
    for code in ("O14.9", "O24.9", "O42.9"):
        assert code in effects
    for effect in effects.values():
        for lab in effect.get("labs") or []:
            for country in ("US", "JP"):
                assert lab["lab"] in load_code_mapping("lab", country), (lab["lab"], country)
            assert lab["value"][0] <= lab["value"][1]
        for order in effect.get("orders") or []:
            assert drug_ref(order["drug"]), order["drug"]
            assert order["anchor"] in ("admission", "delivery")
