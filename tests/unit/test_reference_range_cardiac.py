"""Reference-range resolution for cardiac markers (Troponin_I, CK_MB).

Regression for FHIR conformance: numerical Observations must carry a
referenceRange so the adapter can recompute a consistent interpretation.
The locale reference-range keys must match the canonical analyte names
(Troponin_I / CK_MB) emitted by the observation engine and used in
code_mapping_lab.yaml — not the legacy "Troponin" label.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4_adapter import _build_reference_range

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("country", ["US", "JP"])
def test_troponin_i_has_reference_range(country: str) -> None:
    rr = _build_reference_range("Troponin_I", "M", country)
    assert rr, f"Troponin_I must resolve a reference range for {country}"
    assert rr[0]["high"]["value"] == pytest.approx(0.04)
    assert rr[0]["high"]["unit"] == "ng/mL"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_ck_mb_has_reference_range(country: str) -> None:
    rr = _build_reference_range("CK_MB", "F", country)
    assert rr, f"CK_MB must resolve a reference range for {country}"
    assert rr[0]["high"]["value"] == pytest.approx(5.0)
    assert rr[0]["high"]["unit"] == "ng/mL"
