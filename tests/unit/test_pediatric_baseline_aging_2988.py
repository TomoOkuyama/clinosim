"""Issue #2988: a child's baseline heart and respiratory rate follow the age
at each visit (Fleming et al., Lancet 2011 centiles), keeping the child's
own centile; adults are unchanged."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.observation.pediatric_ranges import carry_vital_centile, pediatric_vital_range
from clinosim.modules.physiology.engine import derive_vital_signs, initialize_state
from clinosim.types.patient import BaselineVitals, PatientPhysiologicalProfile

pytestmark = pytest.mark.unit

_NOON = datetime(2026, 5, 1, 12, 0)


def _true_vitals(baseline: BaselineVitals, age_months: int | None) -> dict[str, float]:
    state = initialize_state(PatientPhysiologicalProfile(), [], "POP-2988")
    return derive_vital_signs(state, baseline, _NOON, age_months=age_months)


def _newborn() -> BaselineVitals:
    # The term-newborn baseline of perinatal.yaml, set at birth.
    return BaselineVitals(heart_rate=138, respiratory_rate=40, reference_age_months=0)


def test_the_same_childs_baseline_hr_at_3_years_is_lower_than_at_3_months() -> None:
    baby = _newborn()
    at_3_months = _true_vitals(baby, 3)
    at_3_years = _true_vitals(baby, 36)
    assert at_3_years["heart_rate"] < at_3_months["heart_rate"] - 25
    assert at_3_years["respiratory_rate"] < at_3_months["respiratory_rate"] - 10


@pytest.mark.parametrize("vital", ["heart_rate", "respiratory_rate"])
@pytest.mark.parametrize("age_months", [36, 48, 60, 96, 150])
def test_a_median_baby_stays_on_the_median(vital: str, age_months: int) -> None:
    birth = pediatric_vital_range(vital, 0)
    later = pediatric_vital_range(vital, age_months)
    assert birth is not None and later is not None
    assert carry_vital_centile(vital, birth.median, 0, age_months) == pytest.approx(later.median)


def test_the_childs_centile_is_kept() -> None:
    # A newborn at the 99th centile (181) is at the 99th centile at 4 years (131).
    assert carry_vital_centile("heart_rate", 181, 0, 48) == pytest.approx(131)
    # Halfway between median and 1st centile stays halfway.
    birth, later = pediatric_vital_range("heart_rate", 0), pediatric_vital_range("heart_rate", 48)
    assert birth is not None and later is not None
    value = carry_vital_centile("heart_rate", (birth.median + birth.low) / 2, 0, 48)
    assert value == pytest.approx((later.median + later.low) / 2)


def test_an_adult_baseline_is_unchanged() -> None:
    adult = BaselineVitals(heart_rate=72, respiratory_rate=16)
    assert _true_vitals(adult, None)["heart_rate"] == _true_vitals(adult, 40 * 12)["heart_rate"]
    assert carry_vital_centile("heart_rate", 72, None, 480) is None
    assert carry_vital_centile("heart_rate", 72, 480, 492) is None


def test_activation_records_the_age_of_a_childs_baseline() -> None:
    from datetime import date

    import numpy as np

    from clinosim.locale.loader import load_demographics
    from clinosim.modules.patient.activator import activate_patient
    from clinosim.types.population import PersonRecord

    def _activate(age: int) -> BaselineVitals:
        person = PersonRecord(
            person_id=f"P-{age}", household_id="H", age=age, sex="F", date_of_birth=date(2026 - age, 1, 1)
        )
        return activate_patient(person, np.random.default_rng(1), load_demographics("US")).baseline_vitals

    child, adult = _activate(4), _activate(40)
    assert child.reference_age_months == 4 * 12 + 6
    assert adult.reference_age_months is None
