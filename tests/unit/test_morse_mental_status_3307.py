"""Issue #3307: the Morse Fall Scale mental-status item scores a patient who
forgets their limitations, not only an impaired level of consciousness.

The item is "Oriented to own ability 0 / Overestimates or forgets limitations
15" (Morse, Morse & Tylko 1989, as reproduced in AHRQ Preventing Falls in
Hospitals, Tool 3H). An alert patient with dementia at CDR 1 or worse, or with
in-hospital delirium from its onset, now scores 15; the rule lives in
``nursing_scores.yaml``.
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.modules.observation.nursing_enricher import enrich_nursing
from clinosim.simulator.enrichers import EnricherContext
from clinosim.types.encounter import ADLAssessment, VitalSignRecord
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit

_DAYS = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]


def _record(chronic: list[ChronicCondition], complications: list | None = None) -> CIFPatientRecord:
    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="p-3307", age=82, chronic_conditions=chronic),
        vital_signs=[VitalSignRecord(consciousness_level="A")],
        adl_assessments=[ADLAssessment(date=d, barthel_score=60) for d in _DAYS],
        complications_occurred=list(complications or []),
    )
    enrich_nursing(EnricherContext(config=None, master_seed=7, records=[rec]))
    return rec


@pytest.mark.parametrize(("stage", "expected"), [("CDR 0.5", 0), ("CDR 1", 15), ("CDR 2", 15), ("CDR 3", 15)])
def test_alert_patient_with_staged_dementia(stage: str, expected: int) -> None:
    rec = _record([ChronicCondition(code="F00.9", stage=stage)])
    assert [a.morse_mental for a in rec.nursing_risk_assessments] == [expected] * len(_DAYS)


def test_alert_patient_without_cognitive_impairment_scores_zero() -> None:
    rec = _record([ChronicCondition(code="I10")])
    assert [a.morse_mental for a in rec.nursing_risk_assessments] == [0, 0, 0]


def test_delirium_scores_from_its_onset() -> None:
    rec = _record(
        [ChronicCondition(code="I10")],
        [{"name": "delirium", "onset_day": 1, "onset_datetime": "2026-01-02T14:00:00", "source": "complication"}],
    )
    assert [a.morse_mental for a in rec.nursing_risk_assessments] == [0, 15, 15]


def test_the_rule_draws_nothing() -> None:
    plain = _record([ChronicCondition(code="I10")]).nursing_risk_assessments
    demented = _record([ChronicCondition(code="I10"), ChronicCondition(code="F00.9", stage="CDR 2")])
    for a, b in zip(plain, demented.nursing_risk_assessments, strict=True):
        assert b.morse_total - a.morse_total == 15
        assert (a.braden_total, a.braden_sensory, a.braden_moisture) == (
            b.braden_total,
            b.braden_sensory,
            b.braden_moisture,
        )
