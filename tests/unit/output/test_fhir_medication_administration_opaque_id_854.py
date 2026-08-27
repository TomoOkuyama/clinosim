"""Issue #854 remainder (PR-medication-administration): MA opaque id +
identifier round-trip.

MedicationAdministration was overlooked in the original Issue #854
sweep — post-close p=500 review found it still emitted a compound
`mar-{encounter_id or patient_id}-{index:05d}` id with no structural-
key round-trip. This PR closes that gap.

Post-fix every `MedicationAdministration.id` is ``mar-<12hex>`` (16
chars, fixed). MA is a leaf in the FHIR reference graph — no other
resource type references MA by id — so this is a stand-alone-tail
migration with no downstream cascade. The pre-#854 compound key is
preserved on `MedicationAdministration.identifier[]` under
``MEDICATION_ADMINISTRATION_KEY_SYSTEM`` for round-trip, appended to
any JP-specific `rpNumber` / `orderInRp` identifier entries.
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import (
    MEDICATION_ADMINISTRATION_ID_PREFIX,
    MEDICATION_ADMINISTRATION_KEY_SYSTEM,
    _resolve_ma_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_MA_PATTERN = re.compile(r"^mar-[0-9a-f]{12}$")


def test_resolve_ma_id_opaque_shape() -> None:
    """Fixed 16 chars: ``mar-`` (4) + 12 hex."""
    result = _resolve_ma_id("ENC-POP-000029-433896976934-00000")
    assert _OPAQUE_MA_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 16


def test_resolve_ma_id_deterministic() -> None:
    key = "ENC-POP-000029-433896976934-00000"
    assert _resolve_ma_id(key) == _resolve_ma_id(key)


def test_ma_id_prefix() -> None:
    assert MEDICATION_ADMINISTRATION_ID_PREFIX == "mar-"


def test_ma_key_system_uri() -> None:
    assert MEDICATION_ADMINISTRATION_KEY_SYSTEM == "urn:clinosim:identifier:medication-administration-key"


def test_distinct_indices_produce_distinct_ids() -> None:
    a = _resolve_ma_id("ENC-1-00000")
    b = _resolve_ma_id("ENC-1-00001")
    assert a != b
