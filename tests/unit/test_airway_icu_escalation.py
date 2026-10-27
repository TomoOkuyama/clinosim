"""Intubation, ventilator and ICU transfer follow consciousness / oxygenation / perfusion (#2091)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.device.engine import _evaluate_indications
from clinosim.modules.procedure.engine import build_intubation_procedure, generate_bedside_procedures
from clinosim.simulator.daily_loop import airway_escalation_needed, icu_escalation_needed
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("state", "airway", "icu"),
    [
        (PhysiologicalState(), False, False),
        (PhysiologicalState(consciousness_impairment=0.8), True, True),
        (PhysiologicalState(consciousness_impairment=0.45), False, False),
        (PhysiologicalState(oxygenation_impairment=0.65), True, True),
        (PhysiologicalState(oxygenation_impairment=0.4), False, False),
        (PhysiologicalState(perfusion_status=0.25), False, True),
    ],
)
def test_escalation_thresholds(state: PhysiologicalState, airway: bool, icu: bool) -> None:
    assert airway_escalation_needed(state) is airway
    assert icu_escalation_needed(state) is icu


@pytest.mark.parametrize(("country", "code"), [("US", "31500"), ("JP", "J044")])
def test_intubation_procedure_record(country: str, code: str) -> None:
    rec = build_intubation_procedure("P1", "E1", datetime(2026, 5, 2, 3, 0), country, "PROC-P1-AIR1")
    assert rec.procedure_type == "intubation" and rec.procedure_code == code
    assert rec.start_datetime == datetime(2026, 5, 2, 3, 0) and rec.encounter_id == "E1"


@pytest.mark.parametrize("disease", ["hemorrhagic_stroke", "subdural_hematoma", "bacterial_pneumonia"])
def test_disease_list_no_longer_intubates(disease: str) -> None:
    for seed in range(40):
        procs = generate_bedside_procedures(
            "P1", "E1", disease, datetime(2026, 5, 1), "severe", np.random.default_rng(seed)
        )
        assert all(p.procedure_type != "intubation" for p in procs)


def test_ventilator_needs_intubation_and_hypoxia_uses_oxygenation() -> None:
    copd = PhysiologicalState(respiratory_fraction=1.0)
    assert "intubated" not in _evaluate_indications(copd, True, False, intubated=False)
    assert "intubated" in _evaluate_indications(copd, True, False, intubated=True)
    assert "hypoxia" in _evaluate_indications(
        PhysiologicalState(oxygenation_impairment=0.65), True, False, intubated=False
    )
