"""A discharge hold is logged only for a drug the patient took (Issue #2992).

"Held" describes a medication the patient was taking (a home medication or a
drug ordered during the stay). A protocol discharge drug the patient never
took is dropped without a hold entry, so no note says it "was held".
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.codes.drugs import drug_key
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative._safety_skips import safety_skip_line
from clinosim.simulator.discharge_rx import build_discharge_rx

pytestmark = pytest.mark.unit


def _holds(patient, ordered: tuple[str, ...] = ()) -> set[str]:
    protocol = load_disease_protocol("heart_failure_exacerbation")
    held: set[str] = set()
    for seed in range(30):
        patient.safety_skip_log.clear()
        build_discharge_rx(
            patient,
            "heart_failure_exacerbation",
            protocol,
            "PR-1",
            datetime(2026, 1, 1),
            np.random.default_rng(seed),
            country_key="us",
            final_renal_function=0.2,
            ordered_drugs=ordered,
        )
        held |= {drug_key(e.candidate_drug) for e in patient.safety_skip_log if e.event_type == "hold"}
    return held


def test_a_protocol_drug_the_patient_never_took_has_no_hold(patient_factory) -> None:
    assert "lisinopril" not in _holds(patient_factory())


def test_a_home_medication_held_at_discharge_is_logged(patient_factory) -> None:
    assert "lisinopril" in _holds(patient_factory(current_meds=["Lisinopril"]))


def test_a_drug_ordered_during_the_stay_held_at_discharge_is_logged(patient_factory) -> None:
    assert "lisinopril" in _holds(patient_factory(), ordered=("Lisinopril 10mg PO daily",))


def test_a_hold_reason_ending_in_a_period_is_not_doubled() -> None:
    skip = {"event_type": "hold", "considered": "Lisinopril", "avoided_due_to": "use one agent."}
    assert not safety_skip_line(skip, "en", prefix="safety_skips").endswith("..")
