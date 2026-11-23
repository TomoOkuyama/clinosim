"""The FHIR Encounter's classHistory ends the ICU segment at the step-down and
adds the ward segment after it (Issue #3555)."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter

pytestmark = pytest.mark.unit

_ENC = {
    "encounter_id": "ENC-1",
    "encounter_type": "inpatient",
    "status": "finished",
    "admission_datetime": "2026-07-09T09:00:00",
    "discharge_datetime": "2026-07-17T11:00:00",
    "ward_id": "4W",
}


def _history(**kw) -> list[dict]:
    return _build_encounter(_ENC, "P-1", country="US", **kw)["classHistory"]


def _code(segment: dict) -> str:
    return segment["class"]["code"]


def test_icu_segment_ends_at_the_step_down_and_the_ward_follows() -> None:
    h = _history(icu_transferred_day=2, icu_discharge_day=5)
    assert [_code(s) for s in h] == ["IMP", "ACUTE", "IMP"]
    assert h[1]["period"] == {"start": "2026-07-11T09:00:00", "end": "2026-07-14T09:00:00"}
    assert h[2]["period"] == {"start": "2026-07-14T09:00:00", "end": "2026-07-17T11:00:00"}


def test_without_a_step_down_the_icu_runs_to_discharge() -> None:
    h = _history(icu_transferred_day=2, icu_discharge_day=None)
    assert [_code(s) for s in h] == ["IMP", "ACUTE"]
    assert h[1]["period"]["end"] == "2026-07-17T11:00:00"


def test_a_step_down_not_after_the_transfer_is_ignored() -> None:
    assert len(_history(icu_transferred_day=2, icu_discharge_day=2)) == 2
