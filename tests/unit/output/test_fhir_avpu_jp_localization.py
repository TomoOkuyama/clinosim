"""Regression test for AVPU consciousness-level Observation JP localization.

`_build_vital_observations`'s AVPU block localized `.text` correctly (via the
`loc_label_ja` lookup) but left `valueCodeableConcept.coding[].display`
hardcoded to the English string regardless of `country` — a JP output could
leak English coding display text while `.text` was properly Japanese,
inconsistent with the rest of the codebase's `_severity_coding()`-style
pattern where both `text` and `coding[].display` are localized together.
"""

import pytest

from clinosim.modules.output._fhir_observations import _build_vital_observations

pytestmark = pytest.mark.unit


def test_avpu_coding_display_localized_for_jp():
    entries = _build_vital_observations(
        {"consciousness_level": "U", "timestamp": "2026-01-01T08:00:00"},
        patient_id="p1", index=0, country="JP",
    )
    loc_obs = next(e["resource"] for e in entries if e["resource"]["id"].endswith("-loc"))
    coding_display = loc_obs["valueCodeableConcept"]["coding"][0]["display"]
    text = loc_obs["valueCodeableConcept"]["text"]
    assert coding_display == "無反応"
    assert coding_display == text


def test_avpu_coding_display_stays_english_for_us():
    entries = _build_vital_observations(
        {"consciousness_level": "U", "timestamp": "2026-01-01T08:00:00"},
        patient_id="p1", index=0, country="US",
    )
    loc_obs = next(e["resource"] for e in entries if e["resource"]["id"].endswith("-loc"))
    coding_display = loc_obs["valueCodeableConcept"]["coding"][0]["display"]
    assert coding_display == "Unresponsive"
