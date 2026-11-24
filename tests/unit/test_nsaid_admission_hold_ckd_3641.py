"""A home NSAID is held at admission when the kidneys are already impaired,
whatever the static renal reserve (Issue #3641)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.simulator.medication_pipeline import _generate_home_medication_orders

pytestmark = pytest.mark.unit


def _orders(patient, *, renal_function: float, reserve: float):
    patient.physiological_profile.renal_reserve = reserve
    return _generate_home_medication_orders(
        patient,
        encounter_id="ENC-1",
        admission_time=datetime(2026, 1, 1, 8, 0),
        attending_id="PR-1",
        rng=np.random.default_rng(0),
        state=SimpleNamespace(renal_function=renal_function),
    )[0]


def test_ckd_with_reserve_above_half_holds_the_nsaid_and_logs_it(patient_factory):
    p = patient_factory(current_meds=["Celecoxib 200mg"], chronic_icds=["N18.4"])
    orders = _orders(p, renal_function=0.07, reserve=0.6)
    assert not any("Celecoxib" in o.display_name for o in orders)
    holds = [e for e in p.safety_skip_log if e.event_type == "hold"]
    assert [h.candidate_drug.split()[0] for h in holds] == ["Celecoxib"]
    assert "renal" in holds[0].active_conflict.lower()


def test_normal_renal_function_keeps_the_nsaid(patient_factory):
    p = patient_factory(current_meds=["Celecoxib 200mg"], chronic_icds=["M17"])
    orders = _orders(p, renal_function=0.9, reserve=0.9)
    assert any("Celecoxib" in o.display_name for o in orders)
    assert not [e for e in p.safety_skip_log if e.event_type == "hold"]


def test_reduce_drug_keeps_the_reserve_guard(patient_factory):
    """ACE inhibitors are annotated only with a low reserve, as before."""
    p = patient_factory(current_meds=["Enalapril 5mg"], chronic_icds=["N18.3"])
    orders = _orders(p, renal_function=0.5, reserve=0.6)
    (order,) = [o for o in orders if "Enalapril" in o.display_name]
    assert "reduced" not in order.clinical_intent.lower()
