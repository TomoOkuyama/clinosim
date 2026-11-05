"""Issue #2687: phosphate, magnesium and total CO2 are modelled analytes."""

from __future__ import annotations

import pytest

from clinosim.modules.observation.engine import get_lab_unit
from clinosim.modules.physiology.engine import derive_lab_values
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("lab", "unit"), [("Phosphate", "mg/dL"), ("Mg", "mg/dL"), ("CO2", "mmol/L")])
def test_each_analyte_has_a_unit_and_a_reference_range(lab: str, unit: str) -> None:
    from clinosim.locale.loaders.clinical import load_reference_ranges

    assert get_lab_unit(lab) == unit
    for country in ("US", "JP"):
        assert lab in (load_reference_ranges(country).get("ranges") or {})


def test_normal_physiology_sits_in_the_reference_range() -> None:
    labs = derive_lab_values(PhysiologicalState(), "M", 50)
    assert 2.5 <= labs["Phosphate"] <= 4.5
    assert 1.7 <= labs["Mg"] <= 2.3
    assert 22 <= labs["CO2"] <= 29


def test_total_co2_follows_bicarbonate() -> None:
    labs = derive_lab_values(PhysiologicalState(), "M", 50)
    assert labs["HCO3"] < labs["CO2"] < labs["HCO3"] + 2.0
    acid = derive_lab_values(PhysiologicalState(ph_status=-0.6), "M", 50)
    assert acid["CO2"] < labs["CO2"]


def test_phosphate_and_magnesium_rise_with_renal_failure() -> None:
    normal = derive_lab_values(PhysiologicalState(), "M", 50)
    aki = derive_lab_values(PhysiologicalState(renal_function=0.3), "M", 50)
    assert aki["Phosphate"] > 4.5 > normal["Phosphate"]
    assert aki["Mg"] > normal["Mg"]
