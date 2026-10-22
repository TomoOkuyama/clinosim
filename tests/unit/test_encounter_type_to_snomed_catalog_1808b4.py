"""Phase 3.β.4 (#1808 follow-up): encounter-type → SNOMED CT catalog.

Pins the ``clinosim/codes/data/encounter-type-to-snomed.yaml`` catalog +
``clinosim.codes.encounter_type_to_snomed`` resolver that replaces the
retired ``_ENCOUNTER_TYPE_SNOMED_CODE`` module-local dict in
``fhir_r4/lib/reference_data.py``.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.codes.encounter_type_to_snomed import (
    _load_catalog,
    all_encounter_types,
    resolve_encounter_type_snomed,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "enc_type,expected",
    [
        ("inpatient", "32485007"),
        ("emergency", "50849002"),
        ("outpatient", "270427003"),
        ("icu", "183452005"),
    ],
)
def test_resolve_encounter_type_snomed_known(enc_type: str, expected: str) -> None:
    assert resolve_encounter_type_snomed(enc_type) == expected


def test_resolve_encounter_type_snomed_unknown_returns_none() -> None:
    assert resolve_encounter_type_snomed("made_up_type") is None
    assert resolve_encounter_type_snomed("") is None


def test_all_encounter_types_matches_catalog() -> None:
    assert all_encounter_types() == ("emergency", "icu", "inpatient", "outpatient")


def test_every_encounter_type_code_has_snomed_authority_display_en_ja() -> None:
    """Every catalog SNOMED code must have EN + JA displays in
    snomed-ct.yaml authority — guards against emit-time fabrication."""
    for enc_type, code in _load_catalog().items():
        en = code_lookup("snomed-ct", code, "en")
        ja = code_lookup("snomed-ct", code, "ja")
        assert en and en != code, f"encounter_types[{enc_type}] = {code} has no EN display in snomed-ct.yaml authority"
        assert ja and ja != code, f"encounter_types[{enc_type}] = {code} has no JA display in snomed-ct.yaml authority"


def test_reference_data_no_longer_exports_sot_dict() -> None:
    """Prevent accidental reintroduction of the retired SoT dict."""
    from clinosim.modules.output.fhir_r4.lib import reference_data as rd

    assert not hasattr(rd, "_ENCOUNTER_TYPE_SNOMED_CODE"), (
        "_ENCOUNTER_TYPE_SNOMED_CODE was retired in Phase 3.β.4 — use "
        "clinosim.codes.encounter_type_to_snomed.resolve_encounter_type_snomed instead"
    )
