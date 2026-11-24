"""A weight-based prescription is dosed from the weight charted at the prescribing visit (Issue #3636)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.anthropometrics import build_anthropometric_observations
from clinosim.modules.output.fhir_r4.lib.dosage import build_dosage_instruction
from clinosim.modules.output.fhir_r4.lib.inline_bb import _encounter_body

pytestmark = pytest.mark.unit


def _patient(dob: str, weight: float = 9.6, height: float = 75.0) -> dict:
    return {
        "patient_id": "POP-T3636",
        "sex": "M",
        "date_of_birth": dob,
        "age": 0,
        "height_cm": height,
        "weight_kg": weight,
    }


def _ctx(patient: dict, enc_id: str, admitted: str) -> SimpleNamespace:
    return SimpleNamespace(
        patient_data=patient,
        country="US",
        record={"encounters": [{"encounter_id": enc_id, "admission_datetime": admitted}]},
    )


def _charted_weight(patient: dict, enc_id: str, admitted: str) -> float:
    obs = build_anthropometric_observations(patient, {"encounter_id": enc_id, "admission_datetime": admitted}, "US")
    weights = [o["valueQuantity"]["value"] for o in obs if o["code"]["coding"][0]["code"] == "29463-7"]
    return weights[0]


def test_child_body_is_the_weight_charted_on_the_visit() -> None:
    patient = _patient("2025-12-01")
    ctx = _ctx(patient, "enc-1", "2026-02-01T10:00:00")
    height, weight = _encounter_body(ctx, "enc-1")
    assert weight == _charted_weight(patient, "enc-1", "2026-02-01T10:00:00")
    assert weight < 9.6  # the end-of-window profile weight overdoses a 2-month-old


def test_per_kg_dose_text_agrees_with_the_charted_weight() -> None:
    patient = _patient("2025-12-01")
    ctx = _ctx(patient, "enc-1", "2026-02-01T10:00:00")
    order = {
        "display_name": "Amoxicillin 45mg/kg",
        "dose_quantity": 45.0,
        "dose_unit": "mg/kg",
        "route": "PO",
        "frequency": "BID",
        "frequency_per_day": 2,
    }
    body = _encounter_body(ctx, "enc-1")
    value = build_dosage_instruction(order, country="US", body=body)["doseAndRate"][0]["doseQuantity"]["value"]
    assert abs(value / 45.0 - _charted_weight(patient, "enc-1", "2026-02-01T10:00:00")) < 0.1


def test_adult_keeps_the_profile_body() -> None:
    patient = _patient("1960-01-01", weight=70.0, height=170.0)
    ctx = _ctx(patient, "enc-1", "2026-02-01T10:00:00")
    assert _encounter_body(ctx, "enc-1") == (170.0, 70.0)


def test_unknown_encounter_or_birth_date_keeps_the_profile_body() -> None:
    patient = _patient("2025-12-01")
    ctx = _ctx(patient, "enc-1", "2026-02-01T10:00:00")
    assert _encounter_body(ctx, "enc-other") == (75.0, 9.6)
    undated = _patient("")
    assert _encounter_body(_ctx(undated, "enc-1", "2026-02-01T10:00:00"), "enc-1") == (75.0, 9.6)


def test_no_weight_stays_no_body() -> None:
    patient = _patient("1960-01-01", weight=0.0, height=0.0)
    ctx = _ctx(patient, "enc-1", "2026-02-01T10:00:00")
    assert _encounter_body(ctx, "enc-1") is None
