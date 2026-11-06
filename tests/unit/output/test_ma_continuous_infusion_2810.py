"""Issue #2810: the MedicationAdministration builder uses the shared
continuous-infusion predicate (order.absolute_dose.is_continuous_infusion)."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import _build_ma_device_block

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("dose", ["0.1 mcg/kg/min", "5 mL/h", "Heparin drip", "Continuous infusion"])
def test_an_iv_infusion_gets_the_infusion_pump(dose: str) -> None:
    block = _build_ma_device_block({"route": "IV", "dose": dose}, "IV", "US")
    assert block and block[0]["reference"] == "Device/dev-infusion-pump"


@pytest.mark.parametrize(("route", "dose"), [("IV", "1 g"), ("PO", "5 mL/h")])
def test_a_bolus_or_non_iv_dose_gets_no_pump(route: str, dose: str) -> None:
    assert _build_ma_device_block({"route": route, "dose": dose}, route, "US") is None
