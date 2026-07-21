"""Issue #350 — JP ICD-10 emissions use the MHLW canonical URI.

JP Core `jp-condition-diagnosis` declares the `Condition.code.coding:icd10`
slice with a **required binding** to
`http://jpfhir.jp/fhir/core/mhlw/ValueSet/ICD10-2013-full`, backed by the
CodeSystem `http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full`
(MHLW 厚労省 ICD-10 2013 registry, 14,877 concepts).

Emitting `http://hl7.org/fhir/sid/icd-10` (WHO) on JP output violates the
required binding regardless of whether the code itself exists on the
terminology server. This test pins that JP ICD-10 emissions carry the
MHLW URI while sharing the underlying code data with the WHO yaml (avoids
duplication).

US path is unaffected — it continues to use `http://hl7.org/fhir/sid/icd-10-cm`.
"""

from __future__ import annotations

import pytest

from clinosim.codes import get_system_uri, lookup, system_key_for
from clinosim.codes.loader import _SYSTEM_DATA_ALIASES

pytestmark = pytest.mark.unit


_MHLW_URI = "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full"
_WHO_URI = "http://hl7.org/fhir/sid/icd-10"
_ICD10_CM_URI = "http://hl7.org/fhir/sid/icd-10-cm"


# === System key selection ===


def test_jp_diagnosis_system_key_is_icd_10_mhlw() -> None:
    """The single source of truth: `system_key_for('diagnosis', 'JP')` returns
    the aliased key, so every downstream emitter picks up the MHLW URI
    automatically without per-site edits."""
    assert system_key_for("diagnosis", "JP") == "icd-10-mhlw"


def test_us_diagnosis_system_key_is_icd_10_cm_unchanged() -> None:
    """US path is not affected by the JP-side URI switch."""
    assert system_key_for("diagnosis", "US") == "icd-10-cm"


# === URI resolution ===


def test_icd_10_mhlw_resolves_to_jp_core_uri() -> None:
    """`get_system_uri('icd-10-mhlw')` returns the JP Core / MHLW canonical
    URI (not the WHO URI)."""
    assert get_system_uri("icd-10-mhlw") == _MHLW_URI


def test_icd_10_still_resolves_to_who_uri() -> None:
    """The WHO `icd-10` key is preserved for callers that explicitly need
    the WHO URI (e.g., US-locale research pipelines). Only the JP mapping
    was changed."""
    assert get_system_uri("icd-10") == _WHO_URI


def test_icd_10_cm_unchanged() -> None:
    assert get_system_uri("icd-10-cm") == _ICD10_CM_URI


# === Data aliasing ===


def test_icd_10_mhlw_aliases_to_icd_10_data() -> None:
    """The alias table declares `icd-10-mhlw` shares yaml data with `icd-10`.
    This avoids duplicating thousands of ICD-10 codes across two files."""
    assert _SYSTEM_DATA_ALIASES["icd-10-mhlw"] == "icd-10"


def test_lookup_via_alias_returns_same_display_as_source() -> None:
    """Display lookups through the alias key resolve to the same text as
    the source key (`icd-10`)."""
    for code in ("R53", "J18.9", "A41.0"):
        via_alias = lookup("icd-10-mhlw", code, "ja")
        via_source = lookup("icd-10", code, "ja")
        assert via_alias == via_source, (
            f"Issue #350: lookup drift between alias and source for {code!r}: "
            f"alias={via_alias!r}, source={via_source!r}"
        )


def test_lookup_via_alias_returns_display_not_code_fallback() -> None:
    """Regression pin: without the alias mechanism, `lookup('icd-10-mhlw', 'R53', 'ja')`
    would fall through to the "return the code as fallback" branch (no yaml
    file at `codes/data/icd-10-mhlw.yaml`), giving the useless `'R53'` back.
    With the alias, the actual display is returned."""
    display = lookup("icd-10-mhlw", "R53", "ja")
    assert display != "R53", (
        "Issue #350 regression: lookup fell through to code-fallback; alias to `icd-10` data is broken."
    )
    assert display  # non-empty


# === FHIR URI reverse map ===


def test_fhir_uri_to_code_system_key_includes_mhlw() -> None:
    """The FHIR-URI-to-clinosim-key reverse map in `fhir_r4_adapter.py`
    must recognize the MHLW URI so display lookups from an inbound coding
    (e.g. `_copy_display_from_sibling_coding`) still work on the JP path."""
    from clinosim.modules.output.fhir_r4_adapter import _FHIR_URI_TO_CODE_SYSTEM_KEY

    assert _MHLW_URI in _FHIR_URI_TO_CODE_SYSTEM_KEY
    assert _FHIR_URI_TO_CODE_SYSTEM_KEY[_MHLW_URI] == "icd-10-mhlw"
