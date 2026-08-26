"""Issue #854 Bucket B (PR-care-team): CareTeam opaque id + identifier
round-trip.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 →
#878-#888) to `CareTeam`. Post-#854 every CareTeam.id is
``careteam-<12hex>`` (21 chars, fixed). CareTeam is a leaf resource on
the p=200 sample — no downstream cross-refs.
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.encounters.care_team import (
    CARE_TEAM_KEY_SYSTEM,
    _resolve_care_team_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_CT_PATTERN = re.compile(r"^careteam-[0-9a-f]{12}$")


def test_resolve_care_team_id_opaque_shape() -> None:
    result = _resolve_care_team_id("ENC-001")
    assert _OPAQUE_CT_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 21


def test_resolve_care_team_id_deterministic() -> None:
    key = "ENC-001"
    assert _resolve_care_team_id(key) == _resolve_care_team_id(key)


def test_care_team_key_system_uri() -> None:
    assert CARE_TEAM_KEY_SYSTEM == "urn:clinosim:identifier:care-team-key"


def test_distinct_encounters_produce_distinct_ids() -> None:
    assert _resolve_care_team_id("ENC-001") != _resolve_care_team_id("ENC-002")
