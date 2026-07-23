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
        patient_id="p1",
        index=0,
        country="JP",
    )
    loc_obs = next(e["resource"] for e in entries if e["resource"]["id"].endswith("-loc"))
    coding_display = loc_obs["valueCodeableConcept"]["coding"][0]["display"]
    text = loc_obs["valueCodeableConcept"]["text"]
    assert coding_display == "無反応"
    assert coding_display == text


def test_avpu_coding_display_stays_english_for_us():
    entries = _build_vital_observations(
        {"consciousness_level": "U", "timestamp": "2026-01-01T08:00:00"},
        patient_id="p1",
        index=0,
        country="US",
    )
    loc_obs = next(e["resource"] for e in entries if e["resource"]["id"].endswith("-loc"))
    coding_display = loc_obs["valueCodeableConcept"]["coding"][0]["display"]
    assert coding_display == "Unresponsive"


def test_avpu_observation_code_display_is_fhirserver_canonical():
    """Issue #384 wave 4 (session 66): the AVPU Observation's
    `code.coding[0]` (LOINC 80288-4) MUST emit the fhirserver-verified
    canonical `"Level of consciousness"` (simple, no AVPU qualifier,
    no score suffix). Verified via direct fhirserver LOINC 2.82 SQLite
    Codes.Description query.

    Prior emits caused 1,252 errors persistently across v25-v29:
    - v25/v27/v28: hardcoded `"Level of consciousness AVPU"` (SHORTNAME)
    - v29: PR #388 hardcoded `"Level of consciousness AVPU score"` (wrong)

    The emit path is hardcoded in `_build_vital_observations` (does not
    go through code_lookup), so both this test AND the loinc.yaml value
    MUST be kept in sync. If future validator canonical genuinely
    changes, update BOTH here AND clinosim/codes/data/loinc.yaml."""
    for country in ("JP", "US"):
        entries = _build_vital_observations(
            {"consciousness_level": "U", "timestamp": "2026-01-01T08:00:00"},
            patient_id="p1",
            index=0,
            country=country,
        )
        loc_obs = next(e["resource"] for e in entries if e["resource"]["id"].endswith("-loc"))
        code_coding = loc_obs["code"]["coding"][0]
        assert code_coding["code"] == "80288-4"
        assert code_coding["display"] == "Level of consciousness", (
            f"country={country}: Observation.code.coding[0].display was "
            f"{code_coding['display']!r} — regressed to a non-canonical form. "
            f"See Issue #384. Canonical is fhirserver-verified simple "
            f'"Level of consciousness".'
        )
