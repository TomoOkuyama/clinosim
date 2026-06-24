"""Smoke test: the three device SNOMED codes resolve via codes.lookup (PR-A)."""
from __future__ import annotations

import pytest

from clinosim.codes import lookup


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("code,expected_en", [
    ("52124006", "Central venous catheter"),
    ("23973005", "Indwelling urinary catheter"),
    ("706172005", "Ventilator"),
])
def test_device_snomed_codes_resolve_en(code, expected_en):
    display = lookup("snomed-ct", code, "en")
    assert display == expected_en


@pytest.mark.parametrize("code,expected_ja", [
    ("52124006", "中心静脈カテーテル"),
    ("23973005", "膀胱留置カテーテル"),
    ("706172005", "人工呼吸器"),
])
def test_device_snomed_codes_resolve_ja(code, expected_ja):
    display = lookup("snomed-ct", code, "ja")
    assert display == expected_ja
