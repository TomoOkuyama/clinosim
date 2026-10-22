"""Phase 3.β.2 (#1808 follow-up): blood-group key → SNOMED CT catalog.

Pins the ``clinosim/codes/data/blood-group-to-snomed.yaml`` catalog +
``clinosim.codes.blood_group_to_snomed`` resolver that replaces the
retired ``_SNOMED_ABO_BY_TYPE`` / ``_SNOMED_RH_BY_FACTOR`` module-local
dicts in ``fhir_r4/labs/blood_type.py``.

Design mirrors Phase 3.β.6 ``clinosim-stage-to-snomed.yaml``: the
clinosim-internal ABO letter / Rh glyph is the key, the SNOMED CT
concept id is the value, and the display is resolved through the
authority yaml via ``code_lookup("snomed-ct", code, lang)`` — so a
catalog edit never drifts the SNOMED display pair.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.codes.blood_group_to_snomed import (
    _load_catalog,
    all_abo_keys,
    all_rh_keys,
    resolve_abo_snomed,
    resolve_rh_snomed,
)

pytestmark = pytest.mark.unit


# ----------------------------------------------------------------------------
# ABO resolver
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "abo,expected",
    [
        ("A", "112144000"),
        ("B", "165743006"),
        ("O", "165744000"),
        ("AB", "165742001"),
    ],
)
def test_resolve_abo_snomed_known(abo: str, expected: str) -> None:
    assert resolve_abo_snomed(abo) == expected


def test_resolve_abo_snomed_unknown_returns_none() -> None:
    assert resolve_abo_snomed("Z") is None
    assert resolve_abo_snomed("") is None


def test_all_abo_keys_matches_catalog() -> None:
    assert all_abo_keys() == ("A", "AB", "B", "O")


# ----------------------------------------------------------------------------
# Rh resolver
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rh,expected",
    [
        ("+", "165747007"),
        ("-", "165748002"),
        ("positive", "165747007"),
        ("negative", "165748002"),
    ],
)
def test_resolve_rh_snomed_known(rh: str, expected: str) -> None:
    assert resolve_rh_snomed(rh) == expected


def test_resolve_rh_snomed_unknown_returns_none() -> None:
    assert resolve_rh_snomed("unknown") is None
    assert resolve_rh_snomed("") is None


def test_all_rh_keys_matches_catalog() -> None:
    assert all_rh_keys() == ("+", "-", "negative", "positive")


# ----------------------------------------------------------------------------
# Mirror invariant — catalog values must resolve against snomed-ct.yaml
# authority (both EN + JA displays must be present, no fabrication).
# ----------------------------------------------------------------------------


def test_every_abo_code_has_snomed_authority_display_en_ja() -> None:
    for abo, code in _load_catalog()["abo"].items():
        en = code_lookup("snomed-ct", code, "en")
        ja = code_lookup("snomed-ct", code, "ja")
        assert en and en != code, f"abo[{abo}] = {code} has no EN display in snomed-ct.yaml authority"
        assert ja and ja != code, f"abo[{abo}] = {code} has no JA display in snomed-ct.yaml authority"


def test_every_rh_code_has_snomed_authority_display_en_ja() -> None:
    for rh, code in _load_catalog()["rh"].items():
        en = code_lookup("snomed-ct", code, "en")
        ja = code_lookup("snomed-ct", code, "ja")
        assert en and en != code, f"rh[{rh}] = {code} has no EN display in snomed-ct.yaml authority"
        assert ja and ja != code, f"rh[{rh}] = {code} has no JA display in snomed-ct.yaml authority"


def test_rh_plus_glyph_and_positive_word_resolve_to_same_code() -> None:
    """Guard: the ``+`` / ``positive`` and ``-`` / ``negative`` pairs are
    glyph aliases of the same SNOMED concept — never let them drift."""
    assert resolve_rh_snomed("+") == resolve_rh_snomed("positive") == "165747007"
    assert resolve_rh_snomed("-") == resolve_rh_snomed("negative") == "165748002"


# ----------------------------------------------------------------------------
# Retirement guard — the old module-local dicts must stay removed
# ----------------------------------------------------------------------------


def test_blood_type_module_no_longer_exports_sot_dicts() -> None:
    """Prevent accidental reintroduction of the retired SoT dicts
    inside ``fhir_r4/labs/blood_type.py``."""
    from clinosim.modules.output.fhir_r4.labs import blood_type as bt

    assert not hasattr(bt, "_SNOMED_ABO_BY_TYPE"), (
        "_SNOMED_ABO_BY_TYPE was retired in Phase 3.β.2 — use "
        "clinosim.codes.blood_group_to_snomed.resolve_abo_snomed instead"
    )
    assert not hasattr(bt, "_SNOMED_RH_BY_FACTOR"), (
        "_SNOMED_RH_BY_FACTOR was retired in Phase 3.β.2 — use "
        "clinosim.codes.blood_group_to_snomed.resolve_rh_snomed instead"
    )
