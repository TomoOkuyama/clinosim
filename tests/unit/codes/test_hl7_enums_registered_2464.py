"""The HL7 encounter enums name registered codes only (Issue #2464)."""

from __future__ import annotations

import pytest

from clinosim.codes import code_exists, display
from clinosim.codes.hl7_encounter import _REGISTRIES, AdmitSource

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("enum", list(_REGISTRIES), ids=lambda e: e.__name__)
def test_every_member_is_registered(enum) -> None:
    system_key = _REGISTRIES[enum]
    assert [m.value for m in enum if not code_exists(system_key, m.value, exact=True)] == []


def test_born_has_a_display() -> None:
    assert display("hl7-admit-source", AdmitSource.BORN.value, "en") == "Born in hospital"
    assert display("hl7-admit-source", AdmitSource.BORN.value, "ja")
