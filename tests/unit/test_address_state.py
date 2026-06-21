"""Unit tests for FHIR Address.state encoding.

Guards the country-specific state encoding in _build_address:
  - US: USPS two-letter abbreviation (US Core convention) — NOT a FIPS numeric
    code. A FIPS lookup table (_US_STATE_CODE) was removed as dead data; this
    test pins the abbreviation behaviour so the FIPS path is not reintroduced.
  - JP: JIS X 0401 prefecture numeric code (via _PREFECTURE_CODE).
"""

import pytest

from clinosim.modules.output.fhir_r4_adapter import _build_address


@pytest.mark.unit
class TestAddressState:
    def test_us_state_uses_usps_abbreviation_not_fips(self) -> None:
        addr = _build_address(
            {"state": "MA", "city": "Boston", "line1": "1 Main St", "postal_code": "02115"},
            "US",
        )
        assert addr is not None
        # US Core uses the USPS 2-letter code; the FIPS numeric ("25") must not appear.
        assert addr["state"] == "MA"

    def test_jp_state_uses_jis_prefecture_code(self) -> None:
        addr = _build_address(
            {"state": "東京都", "city": "千代田区", "line1": "1-1", "postal_code": "100-0001"},
            "JP",
        )
        assert addr is not None
        # JP encodes the prefecture as its JIS X 0401 numeric code.
        assert addr["state"] == "13"
