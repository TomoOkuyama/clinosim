"""Regression test for Observation.referenceRange extension URL.

JP Core Observation_Common profile defines the `referenceRangeSource` extension
for citing the range's issuing body (e.g. JCCLS 共用基準範囲 2022). The extension
URL must match the JP Core spec's fixedUri exactly (session 50 adv-1 rule:
spec → constant → test pin), not a guessed fragment-based URL.

This test pins the extension URL to prevent silent-no-op from URL mismatches.
"""

import pytest

from clinosim.modules.output._fhir_common import _build_reference_range
from clinosim.modules.output._fhir_reference_data import (
    _JP_OBSERVATION_REFERENCE_RANGE_SOURCE_URL,
)

pytestmark = pytest.mark.unit


def test_reference_range_extension_url_is_correct_constant():
    """Extension URL must use the canonical constant, not a fragment-based URL."""
    # Build a reference range for a JP patient with a source URL
    result = _build_reference_range(
        lab_name="WBC",
        patient_sex="M",
        country_code="JP",
    )

    # The result should have an extension with the correct URL
    assert result is not None
    assert len(result) > 0
    assert "extension" in result[0]
    assert len(result[0]["extension"]) > 0
    extension = result[0]["extension"][0]

    # The extension URL must be the correct constant (no fragment)
    assert extension["url"] == _JP_OBSERVATION_REFERENCE_RANGE_SOURCE_URL
    # Verify it's not the old fragment-based URL
    assert "#" not in extension["url"]
    # Verify the extension URL is a proper FHIR extension URL
    assert extension["url"].startswith("http://jpfhir.jp/fhir/core/StructureDefinition/")


def test_reference_range_extension_url_constant_has_no_fragment():
    """The canonical extension URL must not contain a fragment identifier."""
    assert "#" not in _JP_OBSERVATION_REFERENCE_RANGE_SOURCE_URL
    # Verify it's a valid extension URL format
    assert _JP_OBSERVATION_REFERENCE_RANGE_SOURCE_URL.startswith(
        "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation"
    )


def test_reference_range_extension_us_output_omits_extension():
    """US output must not include the JP Core extension (multi-locale isolation)."""
    result = _build_reference_range(
        lab_name="WBC",
        patient_sex="M",
        country_code="US",
    )

    # US output should not have the JP Core extension at all
    if result is not None and len(result) > 0:
        assert "extension" not in result[0] or not result[0].get("extension")
