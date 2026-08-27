"""Issue #854 Bucket B (PR-encounter): Encounter opaque id + identifier
round-trip + cascade across ALL downstream cross-referencers.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 →
#878 [lab] → #879-880 [stand-alones] → #881 [mb-org/sus] → #882
[Specimen] → #883 [Condition] → #884 [DR] → #885 [ImagingStudy] → #886
[DocumentReference] → #887 [Composition] → #888 [ClinicalImpression] →
#889 [CareTeam]) to `Encounter` — the LEAK ROOT of the compound-id
anti-pattern.

Post-#854 every Encounter.id is ``enc-<12hex>`` (15 chars, fixed).
Structural key = the CIF ``encounter_id`` verbatim (e.g.
``ENC-POP-000001-000123`` or ``{IMP_id}-ED`` for synth-ED bridges).
Cross-refs on every downstream resource
(Observation/MR/MA/Procedure/DR/ImagingStudy/DocumentReference/
Composition/ClinicalImpression/CareTeam/Condition/AllergyIntolerance/
Specimen…) route through the shared ``encounter_ref`` helper — never
string-format the CIF value directly.
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.encounters.encounter import (
    ENCOUNTER_ID_PREFIX,
    ENCOUNTER_KEY_SYSTEM,
    encounter_ref,
    resolve_encounter_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_ENC_PATTERN = re.compile(r"^enc-[0-9a-f]{12}$")


# === Resolver contract ===


def test_resolve_encounter_id_opaque_shape() -> None:
    """Fixed 16 chars: ``enc-`` (4) + 12 hex."""
    result = resolve_encounter_id("ENC-POP-000001-000123")
    assert _OPAQUE_ENC_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 16


def test_resolve_encounter_id_deterministic() -> None:
    key = "ENC-POP-000001-000123"
    assert resolve_encounter_id(key) == resolve_encounter_id(key)


def test_encounter_id_prefix() -> None:
    assert ENCOUNTER_ID_PREFIX == "enc-"


def test_encounter_key_system_uri() -> None:
    assert ENCOUNTER_KEY_SYSTEM == "urn:clinosim:identifier:encounter-key"


def test_distinct_structural_keys_produce_distinct_ids() -> None:
    a = resolve_encounter_id("ENC-POP-000001-000123")
    b = resolve_encounter_id("ENC-POP-000001-000124")
    assert a != b


def test_ed_bridge_key_distinct_from_imp() -> None:
    """The synth-ED bridge encounter's structural key is `{IMP_id}-ED`
    (built at inline_bb.py). Its opaque id must never collide with the
    IMP encounter's — ed_reattribution.py routing depends on distinct
    opaque targets."""
    imp = resolve_encounter_id("ENC-POP-000001-000123")
    bridge = resolve_encounter_id("ENC-POP-000001-000123-ED")
    assert imp != bridge


# === encounter_ref helper ===


def test_encounter_ref_returns_reference_dict() -> None:
    ref = encounter_ref("ENC-POP-000001-000123")
    assert ref == {"reference": f"Encounter/{resolve_encounter_id('ENC-POP-000001-000123')}"}
    assert ref["reference"].startswith("Encounter/enc-")


def test_encounter_ref_deterministic() -> None:
    a = encounter_ref("ENC-POP-000001-000123")
    b = encounter_ref("ENC-POP-000001-000123")
    assert a == b
