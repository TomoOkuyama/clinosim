"""Issue #3971: the remaining intravenous antibiotics the protocols order are
dosed for the Cockcroft-Gault creatinine clearance from the bands their labels
state (FDA label for the US, PMDA package insert for JP), and a drug or
country whose label states no clearance table is left unchanged."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from clinosim.modules.order.engine import enrich_medication_order, protocol_medication_orders
from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.simulator.renal_antibiotic_dose import (
    RenalAntibioticDosing,
    RenalDoseContext,
    _rules,
    apply_renal_dose,
)
from clinosim.types.encounter import Order, OrderResult
from clinosim.types.staff import StaffRoster

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 3, 28, 15, 0)
_AGE, _WEIGHT = 70, 70.0


def _patient() -> SimpleNamespace:
    return SimpleNamespace(
        patient_id="P1",
        age=_AGE,
        sex="M",
        date_of_birth=date(2026 - _AGE, 3, 28),
        weight_kg=_WEIGHT,
        height_cm=170.0,
        current_medications=[],
        baseline_vitals=None,
    )


def _creatinine_for(crcl: float) -> float:
    """The serum creatinine (mg/dL) that gives ``crcl`` mL/min for the test
    patient (a 70-year-old man of 70 kg)."""
    return (140 - _AGE) * _WEIGHT / (72 * crcl)


def _order(drug: str, dose: str, country: str) -> Order:
    (order,) = protocol_medication_orders(
        {"drug_id": drug, "dose": dose},
        order_id="ORD-E1-ADM-M01",
        encounter_id="E1",
        patient_id="P1",
        country=country,
        ordered_datetime=_ADM + timedelta(hours=1),
        ordered_by="DR",
    )
    order.display_name = f"{order.display_name} {dose}"  # the regimen the order names
    return enrich_medication_order(order)  # as the MAR does before the renal decision


def _context(crcl: float, country: str) -> RenalDoseContext:
    result = OrderResult(
        result_datetime=_ADM + timedelta(minutes=30),
        performed_by="T",
        lab_name="Creatinine",
        value=_creatinine_for(crcl),
        unit="mg/dL",
        flag="",
    )
    return RenalDoseContext([result], country)


@pytest.fixture(autouse=True)
def _charted_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    """The weight charted on the encounter is the test patient's weight."""
    monkeypatch.setattr(
        "clinosim.modules.population.encounter_anthropometry.encounter_weight_kg",
        lambda patient, *args, **kwargs: patient.weight_kg,
    )


def _adjust(drug: str, dose: str, country: str, crcl: float) -> Order:
    order = _order(drug, dose, country)
    apply_renal_dose(order, _patient(), _ADM, _ADM + timedelta(hours=1), _context(crcl, country))
    assert order.renal_crcl_ml_min == pytest.approx(crcl, abs=0.1)
    return order


def _regimen(order: Order) -> tuple[float | None, str, str | None, int | None]:
    return (order.dose_quantity, order.dose_unit, order.frequency, order.frequency_per_day)


# (drug, written dose, country, clearance, dose, unit, frequency, per day)
_BANDS = [
    # US cefazolin: 35-54 full dose at >= 8 h (the q8h order stands); 11-34
    # half the dose every 12 h; <= 10 half the dose every 18 to 24 h (24 h).
    ("cefazolin", "2g IV q8h", "US", 34, 1.0, "g", "Q12H", 2),
    ("cefazolin", "2g IV q8h", "US", 11, 1.0, "g", "Q12H", 2),
    ("cefazolin", "2g IV q8h", "US", 10, 1.0, "g", "DAILY", 1),
    ("cefazolin", "2g IV q8h", "US", 5, 1.0, "g", "DAILY", 1),
    # US ampicillin / sulbactam: 15-29 every 12 h; 5-14 every 24 h.
    ("ampicillin_sulbactam", "3g IV q6h", "US", 29, 3.0, "g", "Q12H", 2),
    ("ampicillin_sulbactam", "3g IV q6h", "US", 15, 3.0, "g", "Q12H", 2),
    ("ampicillin_sulbactam", "3g IV q6h", "US", 14, 3.0, "g", "DAILY", 1),
    ("ampicillin_sulbactam", "3g IV q6h", "US", 5, 3.0, "g", "DAILY", 1),
    # US levofloxacin 750 mg: 20-49 750 mg every 48 h; 10-19 500 mg every 48 h.
    ("levofloxacin", "750mg IV daily", "US", 49, 750.0, "mg", "Q48H", None),
    ("levofloxacin", "750mg IV daily", "US", 20, 750.0, "mg", "Q48H", None),
    ("levofloxacin", "750mg IV daily", "US", 19, 500.0, "mg", "Q48H", None),
    ("levofloxacin", "750mg IV daily", "US", 10, 500.0, "mg", "Q48H", None),
    # JP levofloxacin 500 mg: 20-49 250 mg daily; < 20 250 mg every 2 days.
    ("levofloxacin", "500mg IV daily", "JP", 49, 250.0, "mg", "DAILY", 1),
    ("levofloxacin", "500mg IV daily", "JP", 20, 250.0, "mg", "DAILY", 1),
    ("levofloxacin", "500mg IV daily", "JP", 19, 250.0, "mg", "Q48H", None),
    # US ciprofloxacin IV 400 mg: 5-29 200 to 400 mg every 18 to 24 h (400 mg, 24 h).
    ("ciprofloxacin", "400mg IV q12h", "US", 29, 400.0, "mg", "DAILY", 1),
    ("ciprofloxacin", "400mg IV q8h", "US", 5, 400.0, "mg", "DAILY", 1),
    # JP ciprofloxacin IV: 30-60 200 mg every 12 h; < 30 200 mg every 24 h.
    ("ciprofloxacin", "400mg IV q8h", "JP", 60, 200.0, "mg", "Q12H", 2),
    ("ciprofloxacin", "400mg IV q8h", "JP", 30, 200.0, "mg", "Q12H", 2),
    ("ciprofloxacin", "400mg IV q8h", "JP", 29, 200.0, "mg", "DAILY", 1),
    # US cefotaxime: < 20 half the dose.
    ("cefotaxime", "2g IV q8h", "US", 19, 1.0, "g", "Q8H", 3),
    # US aztreonam: 10-30 half the dose; < 10 a quarter, at the usual interval.
    ("aztreonam", "2g IV q8h", "US", 30, 1.0, "g", "Q8H", 3),
    ("aztreonam", "2g IV q8h", "US", 10, 1.0, "g", "Q8H", 3),
    ("aztreonam", "2g IV q8h", "US", 9, 500.0, "mg", "Q8H", 3),
    # US imipenem / cilastatin 500 mg q6h: 60-89 400 mg; 30-59 300 mg; 15-29 200 mg.
    ("imipenem_cilastatin", "500mg IV q6h", "US", 89, 400.0, "mg", "Q6H", 4),
    ("imipenem_cilastatin", "500mg IV q6h", "US", 60, 400.0, "mg", "Q6H", 4),
    ("imipenem_cilastatin", "500mg IV q6h", "US", 59, 300.0, "mg", "Q6H", 4),
    ("imipenem_cilastatin", "500mg IV q6h", "US", 30, 300.0, "mg", "Q6H", 4),
    ("imipenem_cilastatin", "500mg IV q6h", "US", 29, 200.0, "mg", "Q6H", 4),
    ("imipenem_cilastatin", "500mg IV q6h", "US", 15, 200.0, "mg", "Q6H", 4),
]


@pytest.mark.parametrize(("drug", "dose", "country", "crcl", "qty", "unit", "freq", "per_day"), _BANDS)
def test_a_clearance_in_each_band_gives_the_label_dose_and_interval(
    drug: str, dose: str, country: str, crcl: float, qty: float, unit: str, freq: str, per_day: int | None
) -> None:
    order = _adjust(drug, dose, country, crcl)
    assert _regimen(order) == (qty, unit, freq, per_day)
    assert order.renal_dose_adjusted
    assert f"CrCl {crcl}" in order.clinical_intent and f"CCr {crcl}" in order.clinical_intent_ja


# (drug, written dose, country, the lowest clearance above the label's bands)
_ABOVE = [
    ("cefazolin", "2g IV q8h", "US", 35),
    ("ampicillin_sulbactam", "3g IV q6h", "US", 30),
    ("levofloxacin", "750mg IV daily", "US", 50),
    ("levofloxacin", "500mg IV daily", "JP", 50),
    ("ciprofloxacin", "400mg IV q12h", "US", 30),
    ("ciprofloxacin", "400mg IV q8h", "JP", 61),
    ("cefotaxime", "2g IV q8h", "US", 20),
    ("aztreonam", "2g IV q8h", "US", 31),
    ("imipenem_cilastatin", "500mg IV q6h", "US", 90),
]


@pytest.mark.parametrize(("drug", "dose", "country", "crcl"), _ABOVE)
def test_a_clearance_above_the_bands_leaves_the_order_unchanged(
    drug: str, dose: str, country: str, crcl: float
) -> None:
    written = _regimen(_order(drug, dose, country))
    order = _adjust(drug, dose, country, crcl)
    assert _regimen(order) == written
    assert not order.renal_dose_adjusted


@pytest.mark.parametrize(
    ("drug", "dose", "country"),
    [
        # the PMDA package inserts give no clearance table in the dosage sections
        ("cefazolin", "1g IV q8h", "JP"),
        ("ampicillin_sulbactam", "3g IV q6h", "JP"),
        ("cefotaxime", "2g IV q8h", "JP"),
        ("cefmetazole", "1g IV q8h", "JP"),
        ("aztreonam", "2g IV q8h", "JP"),
        # adjusted by serum creatinine (interval = creatinine x 8 h), not by clearance
        ("gentamicin", "5mg/kg IV daily", "JP"),
        # ordered by no protocol whose orders the renal rule reads (hospital-acquired infection regimens only)
        ("cefepime", "1g IV q8h", "US"),
    ],
)
def test_a_drug_or_country_without_a_clearance_table_is_unchanged(drug: str, dose: str, country: str) -> None:
    written = _regimen(_order(drug, dose, country))
    order = _order(drug, dose, country)
    apply_renal_dose(order, _patient(), _ADM, _ADM + timedelta(hours=1), _context(8, country))
    assert _regimen(order) == written
    assert not order.renal_dose_adjusted


def test_an_order_given_less_often_than_the_band_is_not_made_more_frequent() -> None:
    """A once-daily cefazolin order is not turned into 1 g every 12 hours (the
    11-34 band); below 10 mL/min it is halved at its own 24-hour interval."""
    daily = _adjust("cefazolin", "2g IV", "US", 20)
    assert _regimen(daily) == (2.0, "g", "DAILY", 1) and not daily.renal_dose_adjusted
    low = _adjust("cefazolin", "2g IV", "US", 8)
    assert _regimen(low) == (1.0, "g", "DAILY", 1)


def test_a_single_dose_is_not_adjusted() -> None:
    order = _order("cefazolin", "2g IV q8h", "US")
    order.single_dose = True
    apply_renal_dose(order, _patient(), _ADM, _ADM + timedelta(hours=1), _context(8, "US"))
    assert (order.dose_quantity, order.dose_unit, order.renal_dose_adjusted) == (2.0, "g", False)


def test_an_order_of_another_dose_than_the_label_table_is_not_adjusted() -> None:
    order = _adjust("imipenem_cilastatin", "1000mg IV q8h", "US", 40)
    assert (order.dose_quantity, order.frequency, order.renal_dose_adjusted) == (1000.0, "Q8H", False)


def test_the_renamed_order_states_the_new_interval() -> None:
    order = _adjust("levofloxacin", "750mg IV daily", "US", 15)
    assert order.display_name == "Levofloxacin 500mg IV q48h"


def _mg(dose_text: str) -> float:
    """The mg of an administration's dose text ("500.0mg Q48H", "1.0g Q8H")."""
    amount = dose_text.split()[0]
    return float(amount[:-2]) if amount.endswith("mg") else float(amount[:-1]) * 1000


def _mar(order: Order, crcl: float, country: str, days: int) -> dict[int, list[float]]:
    """The mg given on each hospital day."""
    ctx = _context(crcl, country)
    by_day: dict[int, list[float]] = {}
    for day in range(days):
        for m in _generate_mar(
            _patient(), [order], day, _ADM, roster=StaffRoster(), rng=np.random.default_rng(day), renal=ctx
        ):
            by_day.setdefault((m.scheduled_datetime.date() - _ADM.date()).days, []).append(_mg(m.dose))
    return by_day


def test_us_levofloxacin_at_15_gives_750_mg_then_500_mg_every_48_hours() -> None:
    by_day = _mar(_order("levofloxacin", "750mg IV daily", "US"), 15, "US", 5)
    assert by_day == {0: [750.0], 2: [500.0], 4: [500.0]}


def test_jp_levofloxacin_at_30_gives_500_mg_on_the_first_day_then_250_mg_daily() -> None:
    by_day = _mar(_order("levofloxacin", "500mg IV daily", "JP"), 30, "JP", 3)
    assert by_day == {0: [500.0], 1: [250.0], 2: [250.0]}


def test_us_aztreonam_keeps_the_initial_dose_then_half_the_dose_every_8_hours() -> None:
    by_day = _mar(_order("aztreonam", "2g IV q8h", "US"), 20, "US", 3)
    # ordered at 16:00: the written 2 g, then 1 g at the 20:00 slot of the same day
    assert by_day == {0: [2000.0, 1000.0], 1: [1000.0] * 3, 2: [1000.0] * 3}


def test_the_bands_are_loaded_as_the_labels_state() -> None:
    drugs = _rules().drugs

    def bands(drug: str, country: str) -> list[tuple[int, float | None, float | None, int]]:
        return [(b.max_crcl, b.dose_factor, b.dose_mg, b.interval_hours) for b in drugs[drug][country].bands]

    assert bands("cefazolin", "US") == [(10, 0.5, None, 24), (34, 0.5, None, 12)]
    assert bands("ampicillin_sulbactam", "US") == [(14, 1.0, None, 24), (29, 1.0, None, 12)]
    assert bands("levofloxacin", "US") == [(19, None, 500, 48), (49, None, 750, 48)]
    assert bands("levofloxacin", "JP") == [(19, None, 250, 48), (49, None, 250, 24)]
    assert bands("ciprofloxacin", "US") == [(29, 1.0, None, 24)]
    assert bands("ciprofloxacin", "JP") == [(29, None, 200, 24), (60, None, 200, 12)]
    assert bands("cefotaxime", "US") == [(19, 0.5, None, 8)]
    assert bands("aztreonam", "US") == [(9, 0.25, None, 8), (30, 0.5, None, 8)]
    assert bands("imipenem_cilastatin", "US") == [(29, None, 200, 6), (59, None, 300, 6), (89, None, 400, 6)]
    for drug, country in (("levofloxacin", "US"), ("levofloxacin", "JP"), ("cefazolin", "US"), ("aztreonam", "US")):
        assert drugs[drug][country].first_dose_unchanged, (drug, country)
    for drug in ("cefepime", "gentamicin", "cefmetazole"):
        assert drug not in drugs
    for drug in ("cefazolin", "ampicillin_sulbactam", "cefotaxime", "aztreonam"):
        assert "JP" not in drugs[drug]


def test_a_band_gives_exactly_one_dose_rule() -> None:
    base = {"cockcroft_gault": _rules().cockcroft_gault.model_dump()}
    with pytest.raises(ValidationError):
        RenalAntibioticDosing.model_validate(
            {
                **base,
                "drugs": {
                    "x": {"US": {"bands": [{"max_crcl": 10, "interval_hours": 24, "dose_mg": 200, "dose_factor": 0.5}]}}
                },
            }
        )
    ok = RenalAntibioticDosing.model_validate(
        {**base, "drugs": {"x": {"US": {"bands": [{"max_crcl": 10, "interval_hours": 48, "dose_mg": 200}]}}}}
    )
    assert ok.drugs["x"]["US"].bands[0].dose_mg == 200
    with pytest.raises(ValidationError):
        RenalAntibioticDosing.model_validate(
            {**base, "drugs": {"x": {"US": {"bands": [{"max_crcl": 10, "interval_hours": 36, "dose_mg": 200}]}}}}
        )


def _morning_mar(drug: str, dose: str, crcl: float, days: int = 2) -> dict[int, list[tuple[str, float, str]]]:
    """(time, mg, drug name) given on each hospital day of an order written at
    06:00 on a 05:00 admission, so the order day has later slots."""
    adm = _ADM.replace(hour=5)
    (order,) = protocol_medication_orders(
        {"drug_id": drug, "dose": dose},
        order_id="ORD-E1-ADM-M01",
        encounter_id="E1",
        patient_id="P1",
        country="US",
        ordered_datetime=adm + timedelta(hours=1),
        ordered_by="DR",
    )
    order.display_name = f"{order.display_name} {dose}"
    enrich_medication_order(order)
    result = OrderResult(
        result_datetime=adm + timedelta(minutes=30),
        performed_by="T",
        lab_name="Creatinine",
        value=_creatinine_for(crcl),
        unit="mg/dL",
        flag="",
    )
    ctx = RenalDoseContext([result], "US")
    by_day: dict[int, list[tuple[str, float, str]]] = {}
    for day in range(days):
        for m in _generate_mar(
            _patient(), [order], day, adm, roster=StaffRoster(), rng=np.random.default_rng(day), renal=ctx
        ):
            by_day.setdefault((m.scheduled_datetime.date() - adm.date()).days, []).append(
                (m.scheduled_datetime.strftime("%H:%M"), _mg(m.dose), m.drug_name)
            )
    return {d: sorted(v) for d, v in by_day.items()}


def test_a_q8h_band_gives_the_written_first_dose_then_the_band_dose_in_the_order_days_later_slots() -> None:
    """Aztreonam at 20 mL/min: 2 g first (the label's initial dose), then 1 g
    at the order day's remaining 8-hourly slots, not only the first dose."""
    by_day = _morning_mar("aztreonam", "2g IV q8h", 20)
    # the urgent first dose follows the order; the 08:00 slot within 90 min of it is skipped
    assert [(t, mg) for t, mg, _ in by_day[0][1:]] == [("14:00", 1000.0), ("20:00", 1000.0)]
    assert by_day[0][0][1] == 2000.0
    assert by_day[0][0][2] == "Aztreonam 2g IV q8h"  # the first dose is named as written
    assert {name for _, _, name in by_day[0][1:]} == {"Aztreonam 1g IV q8h"}
    assert [mg for _, mg, _ in by_day[1]] == [1000.0] * 3


def test_a_q12h_band_gives_the_band_dose_at_the_order_days_later_slot() -> None:
    """Cefazolin at 20 mL/min: 2 g first, then 1 g at the 12-hourly slot."""
    by_day = _morning_mar("cefazolin", "2g IV q8h", 20)
    assert [mg for _, mg, _ in by_day[0]] == [2000.0, 1000.0]
    assert by_day[0][1][0] == "20:00"


def test_a_q24h_band_gives_one_dose_on_the_order_day() -> None:
    """Cefazolin at 8 mL/min (1 g every 24 hours): the written 2 g is the
    only dose of the order day, as for vancomycin."""
    by_day = _morning_mar("cefazolin", "2g IV q8h", 8)
    assert [mg for _, mg, _ in by_day[0]] == [2000.0]
    assert [mg for _, mg, _ in by_day[1]] == [1000.0]
