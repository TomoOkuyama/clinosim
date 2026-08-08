"""Smoke tests for the canonical `patient_factory` fixture (Issue #567).

Locks the fixture's public surface:

- default builds a valid ``PatientProfile``
- kwargs map to the underlying fields
- ``current_meds`` list[str] is promoted to ``HomeMedication`` (post-init
  bypass workaround, Issue #452 PR 3)
- ``chronic_icds`` list[str] is promoted to ``ChronicCondition``
- explicit ``chronic_conditions`` takes precedence over ``chronic_icds``
"""

from __future__ import annotations

from datetime import date

from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile


def test_patient_factory_default_returns_patient_profile(patient_factory) -> None:
    p = patient_factory()
    assert isinstance(p, PatientProfile)
    assert p.patient_id == "POP-000001"
    assert p.age == 65
    assert p.sex == "M"
    # DOB derived: 2026 - 65 = 1961-01-01
    assert p.date_of_birth == date(1961, 1, 1)


def test_patient_factory_kwargs_propagate(patient_factory) -> None:
    p = patient_factory(patient_id="p1", age=40, sex="F", date_of_birth=date(1985, 3, 15))
    assert p.patient_id == "p1"
    assert p.age == 40
    assert p.sex == "F"
    assert p.date_of_birth == date(1985, 3, 15)


def test_patient_factory_current_meds_promoted_to_home_medication(patient_factory) -> None:
    p = patient_factory(current_meds=["Warfarin 3mg", "Amlodipine 5mg"])
    assert all(isinstance(m, HomeMedication) for m in p.current_medications)
    assert [m.drug_name for m in p.current_medications] == ["Warfarin 3mg", "Amlodipine 5mg"]


def test_patient_factory_chronic_icds_promoted_to_chronic_condition(patient_factory) -> None:
    p = patient_factory(chronic_icds=["I48", "E11.9"])
    assert all(isinstance(c, ChronicCondition) for c in p.chronic_conditions)
    assert [c.code for c in p.chronic_conditions] == ["I48", "E11.9"]


def test_patient_factory_explicit_chronic_conditions_wins_over_icds(patient_factory) -> None:
    """Escape hatch — tests that need severity_score / extra fields on a
    ``ChronicCondition`` supply the full instance and the ``chronic_icds``
    shortcut is ignored on that call."""
    explicit = [ChronicCondition(code="I48", severity_score=0.7)]
    p = patient_factory(chronic_conditions=explicit, chronic_icds=["ignored"])
    assert p.chronic_conditions == explicit


def test_patient_factory_baseline_chronic_medications_wired(patient_factory) -> None:
    baseline = [HomeMedication(drug_name="Metformin", dose="500mg", route="PO", frequency="BID")]
    p = patient_factory(baseline_chronic_medications=baseline)
    assert p.baseline_chronic_medications == baseline
