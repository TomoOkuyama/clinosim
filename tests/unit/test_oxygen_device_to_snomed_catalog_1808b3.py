"""Phase 3.β.3 (#1808 follow-up): oxygen device-mode → SNOMED CT catalog.

Pins the ``clinosim/codes/data/oxygen-device-to-snomed.yaml`` catalog +
``clinosim.codes.oxygen_device_to_snomed`` resolver that replaces the
retired ``_SNOMED_DEVICE_BY_MODE`` module-local dict in
``fhir_r4/procedures/oxygen_therapy.py``.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.codes.oxygen_device_to_snomed import (
    _load_catalog,
    all_device_modes,
    resolve_device_snomed,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("nasal_cannula", "336623009"),
        ("simple_mask", "425574000"),
        ("venturi", "336623009"),
        ("non-rebreather", "425574000"),
        ("HFNC", "336623009"),
        ("BiPAP", "26412008"),
        ("ventilator", "26412008"),
    ],
)
def test_resolve_device_snomed_known(mode: str, expected: str) -> None:
    assert resolve_device_snomed(mode) == expected


def test_resolve_device_snomed_unknown_returns_none() -> None:
    assert resolve_device_snomed("made_up_mode") is None
    assert resolve_device_snomed("") is None


def test_all_device_modes_matches_catalog() -> None:
    assert set(all_device_modes()) == {
        "nasal_cannula",
        "simple_mask",
        "venturi",
        "non-rebreather",
        "HFNC",
        "BiPAP",
        "ventilator",
    }


def test_every_device_code_has_snomed_authority_display_en_ja() -> None:
    """Every catalog SNOMED code must have EN + JA displays in
    snomed-ct.yaml authority — guards against emit-time fabrication."""
    for mode, code in _load_catalog().items():
        en = code_lookup("snomed-ct", code, "en")
        ja = code_lookup("snomed-ct", code, "ja")
        assert en and en != code, f"devices[{mode}] = {code} has no EN display in snomed-ct.yaml authority"
        assert ja and ja != code, f"devices[{mode}] = {code} has no JA display in snomed-ct.yaml authority"


def test_fallback_mode_aliases_resolve_to_shared_concept() -> None:
    """Guard: venturi / HFNC fall back to the nasal-cannula concept
    (336623009), and non-rebreather falls back to the face-mask
    concept (425574000). A future SNOMED refinement that adds a
    dedicated code must update the yaml, not the resolver."""
    assert resolve_device_snomed("venturi") == resolve_device_snomed("nasal_cannula")
    assert resolve_device_snomed("HFNC") == resolve_device_snomed("nasal_cannula")
    assert resolve_device_snomed("non-rebreather") == resolve_device_snomed("simple_mask")
    assert resolve_device_snomed("BiPAP") == resolve_device_snomed("ventilator")


def test_oxygen_therapy_module_no_longer_exports_sot_dict() -> None:
    """Prevent accidental reintroduction of the retired SoT dict."""
    from clinosim.modules.output.fhir_r4.procedures import oxygen_therapy as ox

    assert not hasattr(ox, "_SNOMED_DEVICE_BY_MODE"), (
        "_SNOMED_DEVICE_BY_MODE was retired in Phase 3.β.3 — use "
        "clinosim.codes.oxygen_device_to_snomed.resolve_device_snomed instead"
    )
