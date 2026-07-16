"""Unit tests for `_populate_observation_identifier_and_last_updated` walker.

JP_Observation_LabResult_eCS (JP-CLINS 1.12.0) declares `identifier` and
`meta.lastUpdated` with `min=1`. The walker is a single seam that runs
regardless of country (base FHIR admits both as optional; universal
emission keeps US output consistent and cost-free).

Feedback fix (2026-07-16, PR-D). Regression guard.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4_adapter import (
    _CLINOSIM_OBSERVATION_ID_SYSTEM,
    _populate_observation_identifier_and_last_updated,
)

pytestmark = pytest.mark.unit


def test_identifier_populated_from_resource_id():
    r: dict = {"resourceType": "Observation", "id": "lab-enc-1-0000", "effectiveDateTime": "2026-04-15T20:53:00+09:00"}
    _populate_observation_identifier_and_last_updated(r)
    assert r["identifier"] == [{"system": _CLINOSIM_OBSERVATION_ID_SYSTEM, "value": "lab-enc-1-0000"}]


def test_meta_lastupdated_falls_back_to_effective_datetime():
    r: dict = {"resourceType": "Observation", "id": "obs1", "effectiveDateTime": "2026-04-15T20:53:00+09:00"}
    _populate_observation_identifier_and_last_updated(r)
    assert r["meta"]["lastUpdated"] == "2026-04-15T20:53:00+09:00"


def test_meta_lastupdated_falls_back_to_issued():
    r: dict = {"resourceType": "Observation", "id": "obs1", "issued": "2026-04-15T20:53:00+09:00"}
    _populate_observation_identifier_and_last_updated(r)
    assert r["meta"]["lastUpdated"] == "2026-04-15T20:53:00+09:00"


def test_meta_lastupdated_falls_back_to_effective_period_end():
    r: dict = {
        "resourceType": "Observation",
        "id": "obs1",
        "effectivePeriod": {"start": "2026-04-15T20:00:00+09:00", "end": "2026-04-15T20:53:00+09:00"},
    }
    _populate_observation_identifier_and_last_updated(r)
    assert r["meta"]["lastUpdated"] == "2026-04-15T20:53:00+09:00"


def test_idempotent_leaves_builder_populated_identifier_untouched():
    r: dict = {
        "resourceType": "Observation",
        "id": "obs1",
        "identifier": [{"system": "http://example.com/other", "value": "PRE-EXISTING"}],
        "effectiveDateTime": "2026-04-15T20:53:00+09:00",
    }
    _populate_observation_identifier_and_last_updated(r)
    assert r["identifier"] == [{"system": "http://example.com/other", "value": "PRE-EXISTING"}]


def test_idempotent_leaves_builder_populated_lastupdated_untouched():
    r: dict = {
        "resourceType": "Observation",
        "id": "obs1",
        "meta": {"profile": ["p1"], "lastUpdated": "2025-01-01T00:00:00+09:00"},
        "effectiveDateTime": "2026-04-15T20:53:00+09:00",
    }
    _populate_observation_identifier_and_last_updated(r)
    assert r["meta"]["lastUpdated"] == "2025-01-01T00:00:00+09:00"
    assert r["meta"]["profile"] == ["p1"]  # unrelated meta fields preserved


def test_no_effective_datetime_no_lastupdated():
    """When the resource has no datetime source, don't fabricate one."""
    r: dict = {"resourceType": "Observation", "id": "obs1"}
    _populate_observation_identifier_and_last_updated(r)
    # identifier populated, but lastUpdated should NOT be a stub
    assert r["identifier"][0]["value"] == "obs1"
    assert "lastUpdated" not in r.get("meta", {})


def test_ignores_non_observation_resources():
    r: dict = {"resourceType": "Patient", "id": "pt1"}
    _populate_observation_identifier_and_last_updated(r)
    assert "identifier" not in r
    assert "meta" not in r
