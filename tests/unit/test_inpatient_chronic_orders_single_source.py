"""Inpatient chronic-med order tests — single source of truth (Issue #432).

``_generate_home_medication_orders`` in ``inpatient.py`` MUST derive
"Home medication (continue)" orders from ``patient.current_medications``
(the single source of truth set at population time), NOT re-sample the
chronic_medications YAML.

Rationale: re-sampling produces the pathological pattern where activator
picks Warfarin at population time (setting ``current_medications =
['Warfarin 3mg']``), then inpatient re-samples the same YAML with a
different rng and picks Apixaban — so the discharged 'home medication
(continue)' order does not match the patient's home meds. The Issue #432
FHIR-side verification (patient-unit warfarin+DOAC concurrent = 0) fails
if inpatient re-samples independently even with activator-side class
exclusivity.

The ``medication_holds`` logic (renal contraindication, disease-specific
holds) MUST continue to fire against the current_medications-derived
drug names.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from clinosim.simulator.inpatient import _generate_home_medication_orders
from clinosim.types.patient import ChronicCondition, PatientProfile


def _patient(current_meds: list[str], chronic_codes: tuple[str, ...] = ("I48",)) -> PatientProfile:
    from clinosim.types.patient import HomeMedication

    p = PatientProfile(patient_id="POP-000001")
    # #452 PR 3: attribute-assign bypasses PatientProfile.__post_init__.
    p.current_medications = [HomeMedication(drug_name=m) for m in current_meds]
    p.chronic_conditions = [ChronicCondition(code=c) for c in chronic_codes]
    return p


def test_orders_match_current_medications_exactly():
    """When ``current_medications = ['Warfarin 3mg']`` and chronic I48
    is on the record, the resulting orders MUST include Warfarin and
    MUST NOT include Apixaban — regardless of what a YAML re-sample
    might have picked."""
    p = _patient(["Warfarin 3mg"], chronic_codes=("I48",))
    orders, _monitoring = _generate_home_medication_orders(
        p,
        encounter_id="ENC-1",
        admission_time=datetime(2026, 1, 1, 8, 0),
        attending_id="PR-1",
        rng=np.random.default_rng(0),
    )
    names = [o.display_name for o in orders]
    assert any("Warfarin" in n for n in names), f"Warfarin missing from orders: {names}"
    assert not any("Apixaban" in n for n in names), f"Apixaban unexpectedly ordered: {names}"


def test_empty_current_medications_produces_zero_home_orders():
    """A patient with chronic conditions but no home meds MUST NOT
    receive re-sampled orders from the YAML."""
    p = _patient([], chronic_codes=("I48",))
    orders, _ = _generate_home_medication_orders(
        p,
        encounter_id="ENC-2",
        admission_time=datetime(2026, 1, 1, 8, 0),
        attending_id="PR-1",
        rng=np.random.default_rng(0),
    )
    assert len(orders) == 0, f"empty current_meds should yield 0 orders, got {len(orders)}"


def test_medication_hold_from_protocol_still_applies():
    """medication_holds logic (disease-specific hold via disease protocol)
    MUST still apply when the drug comes from ``current_medications``."""

    class _Protocol:
        medication_holds = [{"reason": "Test hold", "drugs": ["warfarin"]}]

    p = _patient(["Warfarin 3mg"], chronic_codes=("I48",))
    orders, _ = _generate_home_medication_orders(
        p,
        encounter_id="ENC-3",
        admission_time=datetime(2026, 1, 1, 8, 0),
        attending_id="PR-1",
        rng=np.random.default_rng(0),
        protocol=_Protocol(),
    )
    names = [o.display_name for o in orders]
    assert not any("Warfarin" in n for n in names), f"Warfarin should be held by protocol hold, got: {names}"


def test_multiple_home_meds_all_ordered():
    """Multi-drug current_medications (e.g. HF triad) all appear in orders."""
    p = _patient(["Furosemide 20mg", "Carvedilol 2.5mg", "Enalapril 5mg"], chronic_codes=("I50",))
    orders, _ = _generate_home_medication_orders(
        p,
        encounter_id="ENC-4",
        admission_time=datetime(2026, 1, 1, 8, 0),
        attending_id="PR-1",
        rng=np.random.default_rng(0),
    )
    names = [o.display_name for o in orders]
    for drug in ("Furosemide", "Carvedilol", "Enalapril"):
        assert any(drug in n for n in names), f"{drug} missing from HF triad orders: {names}"


def test_current_medications_not_in_yaml_still_ordered():
    """If ``current_medications`` contains a drug not listed in the YAML
    (e.g. from a different indication or LLM-suggested), it MUST still
    be ordered — the point is that current_medications is authoritative."""
    p = _patient(["Some Unusual Drug 10mg"], chronic_codes=("I48",))
    orders, _ = _generate_home_medication_orders(
        p,
        encounter_id="ENC-5",
        admission_time=datetime(2026, 1, 1, 8, 0),
        attending_id="PR-1",
        rng=np.random.default_rng(0),
    )
    names = [o.display_name for o in orders]
    assert any("Some Unusual Drug" in n for n in names), f"custom current_med not ordered: {names}"
