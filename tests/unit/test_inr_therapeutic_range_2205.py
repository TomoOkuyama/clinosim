"""INR is interpreted against the therapeutic range on warfarin (Issue #2205)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.observation.engine import determine_flag, therapeutic_range
from clinosim.modules.output.fhir_r4.lib.common import build_reference_range

pytestmark = pytest.mark.unit

_WARFARIN = [SimpleNamespace(drug_name="Warfarin")]
_NONE: list = []


@pytest.mark.parametrize("country", ["JP", "US"])
def test_therapeutic_inr_on_warfarin_is_not_high(country: str) -> None:
    assert determine_flag("PT_INR", 2.4, sex="M", country=country, medications=_WARFARIN, age=60) is None
    assert determine_flag("PT_INR", 2.4, sex="M", country=country, medications=_NONE, age=60) == "H"


def test_jp_elderly_target_is_lower() -> None:
    # JCS 2020: INR 1.6-2.6 for patients aged 70 or older, 2.0-3.0 otherwise.
    assert therapeutic_range("PT_INR", "JP", medications=_WARFARIN, age=75)[:2] == (1.6, 2.6)
    assert therapeutic_range("PT_INR", "JP", medications=_WARFARIN, age=60)[:2] == (2.0, 3.0)
    assert determine_flag("PT_INR", 2.8, sex="F", country="JP", medications=_WARFARIN, age=75) == "H"


def test_subtherapeutic_inr_on_warfarin_is_low() -> None:
    assert determine_flag("PT_INR", 1.3, sex="M", country="US", medications=_WARFARIN, age=60) == "L"


def test_no_therapeutic_range_without_warfarin_or_for_other_labs() -> None:
    assert therapeutic_range("PT_INR", "US", medications=_NONE, age=60) is None
    assert therapeutic_range("Hb", "US", medications=_WARFARIN, age=60) is None


def test_fhir_reference_range_carries_the_therapeutic_range_on_warfarin() -> None:
    rr = build_reference_range("PT_INR", "M", "US", medications=_WARFARIN, age=60)
    types = [r.get("type", {}).get("coding", [{}])[0].get("code") for r in rr]
    assert "therapeutic" in types
    rr_plain = build_reference_range("PT_INR", "M", "US")
    assert "therapeutic" not in [r.get("type", {}).get("coding", [{}])[0].get("code") for r in rr_plain]
