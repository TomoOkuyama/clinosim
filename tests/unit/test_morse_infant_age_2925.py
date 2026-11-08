"""Issue #2925: an infant's recorded age 0 is read as 0, not as the 70-year
default, for the Morse fall-history item."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(("age", "expected"), [(0, 0), (5, 5), (None, 70)])
def test_morse_fall_history_reads_the_recorded_age(monkeypatch, age, expected) -> None:
    from clinosim.modules.observation import nursing, nursing_enricher
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.encounter import ADLAssessment
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    seen: list[int] = []

    def _spy(age_arg: int, unit: float) -> bool:
        seen.append(age_arg)
        return False

    monkeypatch.setattr(nursing, "morse_fall_history", _spy)
    patient = PatientProfile(patient_id="p", age=0)
    if age is None:
        patient.age = None  # type: ignore[assignment]
    else:
        patient.age = age
    rec = CIFPatientRecord(patient=patient, adl_assessments=[ADLAssessment()])
    nursing_enricher.enrich_nursing(EnricherContext(config=None, master_seed=1, records=[rec]))
    assert seen == [expected]
