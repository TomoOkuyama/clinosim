"""DiagnosisCandidate/DifferentialDiagnosis must live in clinosim.types (types rule).

Guards against the types-location violation flagged in the 2026-07-02 grand
design review: these dataclasses previously lived inside
clinosim/modules/diagnosis/engine.py instead of clinosim/types/.
"""

import pytest

from clinosim.types.diagnosis import DiagnosisCandidate, DifferentialDiagnosis

pytestmark = pytest.mark.unit


def test_diagnosis_candidate_importable_from_types():
    c = DiagnosisCandidate(disease_code="bacterial_pneumonia", icd_code="J18.9",
                            display_name="Pneumonia", probability=0.5)
    assert c.probability == 0.5


def test_differential_diagnosis_importable_from_types():
    diff = DifferentialDiagnosis()
    assert diff.candidates == []
    assert diff.top_candidate is None


def test_engine_still_reexports_for_backward_compat():
    from clinosim.modules.diagnosis.engine import DiagnosisCandidate as EngineCandidate
    from clinosim.modules.diagnosis.engine import DifferentialDiagnosis as EngineDifferential
    assert EngineCandidate is DiagnosisCandidate
    assert EngineDifferential is DifferentialDiagnosis
