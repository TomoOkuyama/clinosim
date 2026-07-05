"""Unit tests guarding against wall-clock fields in discarded Bundle wrappers.

`_build_bundle()` and `_build_facility_bundle()` return a Bundle dict whose
`entry` list is what actually gets serialized (`fhir_r4_adapter.py`'s caller
only iterates `bundle.get("entry", [])`); the enclosing Bundle dict itself —
including a `timestamp` field previously set via `datetime.now()` — is
discarded. A wall-clock read there is a determinism footgun with no benefit
(TODO.md "Dead Bundle-timestamp footgun", 2026-07-02 grand design review).
"""

import pytest

from clinosim.modules.output.fhir_r4_adapter import _build_bundle, _build_facility_bundle

pytestmark = pytest.mark.unit


def test_build_bundle_has_no_timestamp_field():
    bundle = _build_bundle({}, "US")
    assert "timestamp" not in bundle


def test_build_facility_bundle_has_no_timestamp_field():
    config = {"available_departments": [], "wards": {}, "resource_capacity": {"inpatient_beds": 1}}
    bundle = _build_facility_bundle(config, "US")
    assert "timestamp" not in bundle
