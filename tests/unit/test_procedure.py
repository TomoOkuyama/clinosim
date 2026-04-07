"""Unit tests for procedure engine."""

import numpy as np
import pytest
from datetime import datetime

from clinosim.modules.procedure.engine import (
    simulate_surgery,
    generate_rehab_sessions,
    ProcedureRecord,
    RehabSession,
)
from clinosim.types.patient import PatientProfile, PatientPhysiologicalProfile, ChronicCondition


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def hip_patient():
    return PatientProfile(
        patient_id="TEST-HIP",
        age=82,
        sex="F",
        chronic_conditions=[
            ChronicCondition(code="I10", severity_score=0.2),
            ChronicCondition(code="M81", severity_score=0.3),
        ],
    )


class MockProtocol:
    procedure = {
        "typical_duration_minutes": {"mean": 90, "sd": 30},
        "anesthesia": "spinal or general",
        "estimated_blood_loss_ml": {"mean": 300, "sd": 150},
    }


@pytest.mark.unit
class TestSurgery:
    def test_produces_procedure_record(self, hip_patient, rng):
        record, impacts = simulate_surgery(
            hip_patient, "hip_fracture", "ENC-001",
            datetime(2024, 6, 15, 18, 0), MockProtocol(), rng, "JP",
        )
        assert isinstance(record, ProcedureRecord)
        assert record.procedure_type in ("ORIF", "hemiarthroplasty")
        assert record.asa_class >= 2
        assert record.estimated_blood_loss_ml > 0
        assert record.duration_minutes > 0

    def test_state_impacts(self, hip_patient, rng):
        _, impacts = simulate_surgery(
            hip_patient, "hip_fracture", "ENC-001",
            datetime(2024, 6, 15, 18, 0), MockProtocol(), rng, "JP",
        )
        assert "anemia_level" in impacts or "inflammation_level" in impacts
        assert impacts.get("inflammation_level", 0) > 0  # surgical trauma

    def test_jp_surgery_timing(self, hip_patient, rng):
        record, _ = simulate_surgery(
            hip_patient, "hip_fracture", "ENC-001",
            datetime(2024, 6, 15, 18, 0), MockProtocol(), rng, "JP",
        )
        hours_to_surgery = (record.start_datetime - datetime(2024, 6, 15, 18, 0)).total_seconds() / 3600
        assert hours_to_surgery >= 12  # JP: at least 12h


@pytest.mark.unit
class TestRehab:
    def test_generates_sessions(self, rng):
        sessions = generate_rehab_sessions(
            "TEST-001", "ENC-001",
            datetime(2024, 6, 17, 10, 0), 30, rng, "JP",
        )
        assert len(sessions) > 20  # ~27 sessions for 30-day stay
        assert all(isinstance(s, RehabSession) for s in sessions)

    def test_sessions_have_activities(self, rng):
        sessions = generate_rehab_sessions(
            "TEST-001", "ENC-001",
            datetime(2024, 6, 17, 10, 0), 30, rng, "JP",
        )
        for s in sessions[:5]:
            assert len(s.activities) > 0
            assert s.therapy_type == "PT"

    def test_pain_decreases_over_time(self, rng):
        sessions = generate_rehab_sessions(
            "TEST-001", "ENC-001",
            datetime(2024, 6, 17, 10, 0), 30, rng, "JP",
        )
        early = [s.pain_score for s in sessions[:5] if s.pain_score is not None]
        late = [s.pain_score for s in sessions[-5:] if s.pain_score is not None]
        if early and late:
            assert sum(early) / len(early) >= sum(late) / len(late)  # pain should decrease
