"""Every dateTime of a MedicationRequest, boundsPeriod included, carries the
cohort country's offset (Issue #3042)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from clinosim.modules.output.fhir_r4.lib.fhir_time import tz_suffix_for_country
from clinosim.modules.output.fhir_r4.medications.medications import _apply_order_end
from clinosim.modules.output.fhir_r4.post_process.datetime_normalize import (
    _normalize_dt_and_fill_practitioner_display,
    _normalize_dt_fields,
)

pytestmark = pytest.mark.unit

_OUTPUT = Path(__file__).resolve().parents[2] / "clinosim" / "modules" / "output"


def _request() -> dict:
    # authoredOn as the builder holds it before the post-emit normalization.
    return {
        "resourceType": "MedicationRequest",
        "authoredOn": "2024-01-21T15:20:00",
        "dosageInstruction": [{"timing": {"repeat": {"frequency": 1, "period": 8, "periodUnit": "h"}}}],
    }


@pytest.mark.parametrize("country", ["US", "JP"])
def test_bounds_period_start_and_end_carry_the_country_offset(country: str) -> None:
    resource = _request()
    _apply_order_end(resource, {"end_datetime": datetime(2024, 1, 24, 22, 8, 50)}, resource["authoredOn"])
    _normalize_dt_fields(resource, country)
    bounds = resource["dosageInstruction"][0]["timing"]["repeat"]["boundsPeriod"]
    tz = tz_suffix_for_country(country)
    assert bounds["start"] == f"2024-01-21T15:20:00{tz}"
    assert bounds["end"] == f"2024-01-24T22:08:50{tz}"
    assert resource["authoredOn"].endswith(tz)


def test_a_loading_dose_start_carries_the_offset() -> None:
    resource = _request()
    order = {"end_datetime": "2024-01-24T08:00:00", "administer_from": "2024-01-22 08:00:00"}
    _apply_order_end(resource, order, resource["authoredOn"])
    _normalize_dt_fields(resource, "US")
    assert resource["dosageInstruction"][0]["timing"]["repeat"]["boundsPeriod"] == {
        "start": "2024-01-22T08:00:00Z",
        "end": "2024-01-24T08:00:00Z",
    }


def _emitted_period_keys() -> set[str]:
    keys: set[str] = set()
    for path in _OUTPUT.rglob("*.py"):
        keys |= set(re.findall(r'"([a-z][A-Za-z]*Period|period)"', path.read_text(encoding="utf-8")))
    return keys


@pytest.mark.parametrize("walker", ["fields", "fused"])
def test_every_period_the_builders_emit_is_normalized(walker: str) -> None:
    # Guard: a Period-typed element the walker does not know keeps a builder's
    # JST (or no) offset in US output, as boundsPeriod did.
    keys = _emitted_period_keys()
    assert {"boundsPeriod", "validityPeriod", "period"} <= keys
    for key in sorted(keys):
        node = {"x": {key: {"start": "2024-01-01T08:00:00+09:00", "end": "2024-01-02T08:00:00"}}}
        if walker == "fields":
            _normalize_dt_fields(node, "US")
        else:
            _normalize_dt_and_fill_practitioner_display(node, "US", None)
        assert node["x"][key] == {"start": "2024-01-01T08:00:00Z", "end": "2024-01-02T08:00:00Z"}, key
