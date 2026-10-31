"""SNOMED severity qualifiers carry the right Japanese display (Issue #2259)."""

from __future__ import annotations

import pytest

from clinosim.codes import lookup

pytestmark = pytest.mark.unit

# Verified on tx.fhir.org $lookup: 24484000 Severe, 6736007 Moderate severity, 255604002 Mild.
_EXPECTED = {"24484000": ("Severe", "重度"), "6736007": ("Moderate severity", "中等度"), "255604002": ("Mild", "軽度")}


@pytest.mark.parametrize("code", sorted(_EXPECTED))
def test_severity_code_displays(code: str) -> None:
    en, ja = _EXPECTED[code]
    assert lookup("snomed-ct", code, "en") == en
    assert lookup("snomed-ct", code, "ja") == ja
