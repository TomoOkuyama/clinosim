"""NEWS2 is scored only on complete vital-sign sets (Issue #3644)."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from clinosim.modules.observation.nursing import compute_news2, news2_inputs_complete
from clinosim.modules.observation.nursing_enricher import enrich_nursing
from clinosim.simulator.enrichers import EnricherContext
from clinosim.simulator.oxygen_course import OxygenCourse
from clinosim.simulator.vitals_pipeline import _generate_vitals
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import VitalSignRecord
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

FULL = {
    "respiratory_rate": 18,
    "spo2": 96,
    "temperature_celsius": 37.0,
    "systolic_bp": 120,
    "heart_rate": 80,
    "consciousness_level": "A",
}


def test_complete_set_is_scored_as_before() -> None:
    assert news2_inputs_complete(FULL)
    assert compute_news2(FULL) == 0


@pytest.mark.parametrize("missing", list(FULL))
def test_a_set_missing_any_parameter_is_incomplete(missing: str) -> None:
    vs = {k: v for k, v in FULL.items() if k != missing}
    assert not news2_inputs_complete(vs)
    assert not news2_inputs_complete({**FULL, missing: None})


def test_blank_consciousness_level_is_incomplete() -> None:
    assert not news2_inputs_complete({**FULL, "consciousness_level": ""})


def _enrich(vitals: list[VitalSignRecord]) -> list[VitalSignRecord]:
    rec = CIFPatientRecord(patient=PatientProfile(patient_id="p-3644", age=70), vital_signs=vitals)
    enrich_nursing(EnricherContext(config=None, master_seed=5, records=[rec]))
    return rec.vital_signs


def test_enricher_skips_temperature_only_and_monitor_rows() -> None:
    t = datetime(2026, 5, 11, 13, 46)
    full = VitalSignRecord(
        timestamp=t,
        temperature_celsius=39.0,
        heart_rate=110,
        systolic_bp=118,
        respiratory_rate=22,
        spo2=93.0,
        consciousness_level="A",
        on_supplemental_oxygen=True,
    )
    temp_only = VitalSignRecord(
        timestamp=t + timedelta(minutes=35),
        temperature_celsius=39.0,
        consciousness_level="",
        on_supplemental_oxygen=None,
    )
    monitor = VitalSignRecord(
        timestamp=t + timedelta(hours=2), heart_rate=100, spo2=94.0, consciousness_level="", on_supplemental_oxygen=True
    )
    out = _enrich([full, temp_only, monitor])
    assert out[0].news2_score is not None
    assert out[1].news2_score is None
    assert out[2].news2_score is None


def test_generated_partial_rows_carry_no_news2_and_no_oxygen_assertion() -> None:
    state = PhysiologicalState()
    state.inflammation_level = 0.9
    state.oxygenation_impairment = 0.5
    patient = PatientProfile(patient_id="p-3644b", age=70)
    rng = np.random.default_rng(1)
    vitals: list[VitalSignRecord] = []
    for day in range(6):
        vitals += _generate_vitals(
            state, patient, day, datetime(2026, 5, 1, 8, 0), rng, "bacterial_pneumonia", "N1", None, OxygenCourse()
        )
    partial = [v for v in vitals if v.spo2 is None]
    assert partial, "no temperature-only row generated"
    assert all(v.on_supplemental_oxygen is None for v in partial)
    scored = _enrich(vitals)
    assert all(v.news2_score is None for v in scored if v.consciousness_level == "" or v.respiratory_rate is None)


def test_progress_state_keeps_oxygen_when_the_latest_row_did_not_measure_it() -> None:
    from clinosim.modules.document.narrative._progress_exam import current_states
    from tests.unit.modules.document.narrative.test_progress_exam_course_3235_3247 import _ctx, _v

    on_o2 = _v(2, 8, spo2=93.0, on_supplemental_oxygen=True)
    temp_only = _v(2, 9, temperature_celsius=39.0, on_supplemental_oxygen=None)
    states = current_states(_ctx([on_o2, temp_only], day=2, lang="en"), [on_o2, temp_only], [])
    assert states.get("on_oxygen") == {"high"}
