"""UCUM canonicalization pin tests for `build_ucum_quantity`.

fhir-jp-validator 2026-07-17 §【最優先 1】(6,203 errors on
MedicationAdministration Quantity.code) surfaced three informal clinical
unit spellings that UCUM does not accept:

- ``IU`` (3,386) → ``[iU]``
- ``mcg`` (2,793) → ``ug``
- ``u/h`` (24) → ``U/h``

Issue: #204. Fix is at ``_fhir_common._to_ucum_code`` — a token-level
map applied by ``build_ucum_quantity`` on ``Quantity.code`` (``Quantity.unit``
stays as-is for human readability). These tests pin the mapping
so a future edit to ``_UCUM_CODE_MAP`` cannot silently reintroduce the
error class.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output._fhir_common import (
    _to_ucum_code,
    build_ucum_quantity,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("clinical_unit", "expected_ucum_code"),
    [
        # Scalar informal spellings.
        ("mcg", "ug"),
        ("IU", "[iU]"),
        ("iu", "[iU]"),
        ("mIU", "m[iU]"),
        ("mEq", "meq"),
        ("u", "U"),
        ("unit", "U"),
        ("units", "U"),
        ("mmHg", "mm[Hg]"),
        # Compound forms (split on `/`, map each factor).
        ("IU/L", "[iU]/L"),
        ("mcg/kg", "ug/kg"),
        ("IU/kg/h", "[iU]/kg/h"),
        ("u/h", "U/h"),
        ("mIU/mL", "m[iU]/mL"),
        # Byte-identical for units that are already UCUM canonical.
        ("mg", "mg"),
        ("mL", "mL"),
        ("g/dL", "g/dL"),
        ("mL/h", "mL/h"),
        ("mmol/L", "mmol/L"),
        ("U/L", "U/L"),
        ("%", "%"),
        # Empty passthrough (belt-and-suspenders — build_ucum_quantity
        # already gates on `if unit`).
        ("", ""),
    ],
)
def test_to_ucum_code_mapping(clinical_unit: str, expected_ucum_code: str) -> None:
    assert _to_ucum_code(clinical_unit) == expected_ucum_code


def test_to_ucum_code_is_idempotent_on_already_canonical() -> None:
    """Passing an already-canonical form returns it unchanged (idempotency)."""
    for canonical in ("[iU]/L", "ug", "meq", "mm[Hg]", "U", "mg/dL"):
        assert _to_ucum_code(canonical) == canonical


def test_build_ucum_quantity_preserves_unit_display_and_canonicalizes_code() -> None:
    """`Quantity.unit` keeps the human display; `Quantity.code` gets the
    UCUM canonical token. Clinicians reading the JSON still see the
    familiar spelling; the profile validation sees a spec-conformant code."""
    q = build_ucum_quantity(500, "mcg")
    assert q["unit"] == "mcg"  # human display preserved
    assert q["code"] == "ug"  # UCUM canonical
    assert q["value"] == 500
    assert q["system"] == "http://unitsofmeasure.org"


def test_build_ucum_quantity_compound_unit_canonicalizes_code_only() -> None:
    """Compound units are canonicalized on the `code` axis only."""
    q = build_ucum_quantity(1000, "IU/h")
    assert q["unit"] == "IU/h"
    assert q["code"] == "[iU]/h"


def test_build_ucum_quantity_no_unit_still_valid_without_code() -> None:
    """When `unit` is empty, neither `unit` nor `code` are emitted;
    the Quantity still carries `value` + `system` (pre-#204 shape)."""
    q = build_ucum_quantity(3.5, "")
    assert "unit" not in q
    assert "code" not in q
    assert q["value"] == 3.5


def test_build_ucum_quantity_passthrough_for_canonical_units() -> None:
    """Byte-identical output for units that were already UCUM canonical
    pre-#204 (mg / mL / g/dL / mL/h / mmol/L / U/L / %)."""
    for unit in ("mg", "mL", "g/dL", "mL/h", "mmol/L", "U/L", "%"):
        q = build_ucum_quantity(1, unit)
        assert q["unit"] == unit
        assert q["code"] == unit
