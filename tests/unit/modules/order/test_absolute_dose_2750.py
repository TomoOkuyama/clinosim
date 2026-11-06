"""Issue #2750: administrations of per-kg / per-m² orders state the absolute amount given."""

from __future__ import annotations

import pytest

from clinosim.modules.order.absolute_dose import absolute_dose, body_surface_area, is_continuous_infusion
from clinosim.modules.output.fhir_r4.lib.dosage import _parse_dose_for_mar

pytestmark = pytest.mark.unit


def test_bsa_dose_is_per_m2_times_mosteller_bsa() -> None:
    bsa = body_surface_area(170, 68)  # sqrt(170 x 68 / 3600) = 1.792 m²
    assert bsa == pytest.approx(1.792, abs=0.001)
    assert absolute_dose(400, "mg/m2", 170, 68) == (717.0, "mg")


def test_weight_dose_is_per_kg_times_weight() -> None:
    assert absolute_dose(20, "mg/kg", 175, 70) == (1400.0, "mg")
    assert absolute_dose(0.1, "mg/kg", 175, 70) == (7.0, "mg")


def test_rates_and_absolute_doses_have_no_conversion() -> None:
    assert absolute_dose(0.5, "mg/kg/h", 175, 70) is None
    assert absolute_dose(40, "mg", 175, 70) is None


def test_the_administration_parser_does_not_truncate_a_per_unit_dose() -> None:
    assert "dose_quantity" not in _parse_dose_for_mar("400mg/m2")
    assert "dose_quantity" not in _parse_dose_for_mar("0.5 mg/kg/h")
    assert _parse_dose_for_mar("718mg IV") == {"dose_quantity": 718.0, "dose_unit": "mg", "route": "IV"}


def test_a_continuous_infusion_rate_is_not_a_dose() -> None:
    assert is_continuous_infusion("DRIP", "Norepinephrine 0.05-0.3ug/kg/min IV drip")
    assert is_continuous_infusion("", "Dobutamine 2-20ug/kg/min")
    assert not is_continuous_infusion("DAILY", "Vancomycin")
