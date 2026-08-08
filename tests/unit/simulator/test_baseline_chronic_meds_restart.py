"""Renal-hold restart from baseline_chronic_medications (Issue #433 C1).

Verifies:
1. `baseline_chronic_medications` is populated at activation as a snapshot of
   the initial chronic regimen.
2. When `build_discharge_rx` runs with `final_renal_function < 0.3`, metformin
   is held (not emitted in discharge items).
3. On a subsequent admission with `final_renal_function >= 0.3`, metformin is
   re-emitted BECAUSE baseline still carries it — even if `current_medications`
   from the intermediate admission lost the entry.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np

from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.simulator.discharge_rx import build_discharge_rx
from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile


def _metformin_patient(patient_factory) -> PatientProfile:
    """Wrap ``patient_factory`` with the metformin+E11.9 shape shared by the
    Issue #433 scenarios below. Kept as a module-local wrapper (not a pytest
    fixture) because callers pass in the ``patient_factory`` fixture."""
    metformin = HomeMedication(drug_name="Metformin", dose="500mg", route="PO", frequency="BID")
    p = patient_factory(
        patient_id="POP-TEST",
        household_id="HH-TEST",
        age=65,
        sex="F",
        date_of_birth=date(1960, 1, 1),
        chronic_conditions=[ChronicCondition(code="E11.9", severity_score=0.3)],
        baseline_chronic_medications=[metformin],
    )
    # Simulate activator populate: current = baseline at activation.
    p.current_medications = [metformin]
    return p


def _minimal_protocol() -> DiseaseProtocol:
    """Tiny AKI-like protocol with empty discharge_oral (chronic loop is the only source)."""
    return DiseaseProtocol(
        disease_id="test_disease",
        icd_codes={"primary": "N17.9"},
        incidence={"japan": {}, "us": {}},
        severity={"distribution": {"mild": 1.0, "moderate": 0.0, "severe": 0.0}},
    )


def _rx_drugs(patient: PatientProfile, protocol: DiseaseProtocol, renal: float) -> list[str]:
    rx = build_discharge_rx(
        patient,
        "test_disease",
        protocol,
        "PR-1",
        datetime(2026, 1, 1),
        np.random.default_rng(42),
        country_key="japan",
        final_renal_function=renal,
    )
    return [it["drug_name"] for it in rx.items]


def test_baseline_populated_from_current_meds_at_activation(patient_factory):
    p = _metformin_patient(patient_factory)
    assert len(p.baseline_chronic_medications) == 1
    assert p.baseline_chronic_medications[0].drug_name == "Metformin"


def test_renal_ok_emits_metformin_from_baseline(patient_factory):
    p = _metformin_patient(patient_factory)
    drugs = _rx_drugs(p, _minimal_protocol(), renal=0.9)
    assert "Metformin" in drugs


def test_renal_impaired_holds_metformin(patient_factory):
    """Renal function < 0.3 → nephrotoxic drug (Metformin) suppressed."""
    p = _metformin_patient(patient_factory)
    drugs = _rx_drugs(p, _minimal_protocol(), renal=0.2)
    assert "Metformin" not in drugs


def test_renal_recovered_re_emits_metformin_even_if_current_meds_lost_it(patient_factory):
    """The core #433 scenario: after AKI cleared metformin from current_medications
    (intermediate admission at renal=0.2 didn't re-emit it), the next admission at
    renal=0.9 restores it from baseline — chronic drug NOT permanently lost."""
    p = _metformin_patient(patient_factory)
    # Simulate the intermediate admission clearing metformin from current
    p.current_medications = []
    # baseline_chronic_medications unchanged (immutable snapshot)
    assert len(p.baseline_chronic_medications) == 1
    drugs = _rx_drugs(p, _minimal_protocol(), renal=0.9)
    assert "Metformin" in drugs, (
        "Metformin must re-emit from baseline even when absent from current_medications "
        "(this is the renal-hold restart fix for Issue #433)"
    )


def test_empty_baseline_falls_back_to_current_medications(patient_factory):
    """Backcompat: patient with empty baseline (older fixtures) uses current_medications."""
    p = patient_factory(
        patient_id="POP-LEGACY",
        household_id="HH-LEGACY",
        age=70,
        sex="M",
        date_of_birth=date(1955, 1, 1),
        chronic_conditions=[ChronicCondition(code="I10", severity_score=0.3)],
    )
    p.current_medications = [HomeMedication(drug_name="Amlodipine", dose="5mg", route="PO", frequency="daily")]
    # baseline_chronic_medications intentionally empty (fallback path)
    assert len(p.baseline_chronic_medications) == 0
    drugs = _rx_drugs(p, _minimal_protocol(), renal=0.9)
    assert "Amlodipine" in drugs
