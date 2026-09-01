"""Issue #1038 (v2, option 1): populate `CodeableConcept.text` from a
JA lookup when it is missing.

Prior attempt (#1045, closed) populated `.coding.display` with EN and
broke the existing JP integration test that expects `.coding[0].display`
to be JP on OUTPATIENT_SOAP (where LOINC is the only coding).

This version leaves `.coding.display` alone (respecting the strip
walker's English-only CS conformance guard) and instead fills the
CodeableConcept's `.text` field — which is the FHIR-idiomatic slot for
the human-readable label. JP-CLINS-mandated document types already
populate `.text` at emit time; this walker fills the remaining gaps
(the p=10000 audit surfaced LP29684-5 radiology category as the main
one, plus a small number of edge cases).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


LOINC_URI = "http://loinc.org"


def test_populate_cc_text_from_coding_lookup_fills_missing_text() -> None:
    """A CodeableConcept with a LOINC coding but no `.text` gets `.text`
    populated from `code_lookup("loinc", code, "ja")`."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_cc_text_from_coding_lookup,
    )

    cc = {"coding": [{"system": LOINC_URI, "code": "34131-3"}]}
    _populate_cc_text_from_coding_lookup(cc, lang="ja")
    assert cc.get("text") == "外来経過記録（SOAP）"


def test_populate_cc_text_preserves_existing_text() -> None:
    """A CC with `.text` already populated is NOT overwritten."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_cc_text_from_coding_lookup,
    )

    cc = {
        "coding": [{"system": LOINC_URI, "code": "34131-3"}],
        "text": "Custom label",
    }
    _populate_cc_text_from_coding_lookup(cc, lang="ja")
    assert cc["text"] == "Custom label"


def test_populate_cc_text_walks_nested_composition_structure() -> None:
    """Both `Composition.type` and `Composition.section[].code` CCs get
    `.text` populated by the recursive walker."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_cc_text_from_coding_lookup,
    )

    comp = {
        "resourceType": "Composition",
        "type": {"coding": [{"system": LOINC_URI, "code": "34131-3"}]},
        "section": [
            {"code": {"coding": [{"system": LOINC_URI, "code": "10164-2"}]}},
            {"code": {"coding": [{"system": LOINC_URI, "code": "8716-3"}]}},
        ],
    }
    _populate_cc_text_from_coding_lookup(comp, lang="ja")
    assert comp["type"]["text"] == "外来経過記録（SOAP）"
    assert comp["section"][0]["code"]["text"] == "現病歴"
    assert comp["section"][1]["code"]["text"] == "バイタルサイン"


def test_populate_cc_text_does_not_touch_coding_display() -> None:
    """The walker leaves `.coding.display` untouched — that field is
    governed by the strip walker's English-only CS conformance rules."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_cc_text_from_coding_lookup,
    )

    cc = {"coding": [{"system": LOINC_URI, "code": "34131-3"}]}
    _populate_cc_text_from_coding_lookup(cc, lang="ja")
    assert "display" not in cc["coding"][0]


def test_populate_cc_text_lp29684_5_radiology_category() -> None:
    """LP29684-5 (Radiology, LOINC part code) is emitted on the JP-CLINS
    eImagingReport Composition.category with its JA display set at emit
    time. The strip walker removes that JA display; without a `.text`
    fallback, JP consumers see a bare code. Now that LP29684-5 is
    registered in loinc.yaml, `.text` populates with "放射線"."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_cc_text_from_coding_lookup,
    )

    cc = {"coding": [{"system": LOINC_URI, "code": "LP29684-5"}]}
    _populate_cc_text_from_coding_lookup(cc, lang="ja")
    assert cc.get("text") == "放射線"


def test_populate_via_dispatcher_fires_for_composition() -> None:
    """`_populate_condition_ai_mr_ecs_fields` recognises Composition and
    routes it through the recursive CC-text walker."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_condition_ai_mr_ecs_fields,
    )

    comp = {
        "resourceType": "Composition",
        "type": {"coding": [{"system": LOINC_URI, "code": "34131-3"}]},
        "section": [
            {"code": {"coding": [{"system": LOINC_URI, "code": "10164-2"}]}},
        ],
    }
    _populate_condition_ai_mr_ecs_fields(comp, country="JP")
    assert comp["type"]["text"] == "外来経過記録（SOAP）"
    assert comp["section"][0]["code"]["text"] == "現病歴"


def test_populate_walker_is_idempotent() -> None:
    """Running the walker a second time leaves the CC unchanged."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_cc_text_from_coding_lookup,
    )

    cc = {"coding": [{"system": LOINC_URI, "code": "34131-3"}]}
    _populate_cc_text_from_coding_lookup(cc, lang="ja")
    snap = cc["text"]
    _populate_cc_text_from_coding_lookup(cc, lang="ja")
    assert cc["text"] == snap


def test_populate_skips_unknown_system() -> None:
    """A coding with an unknown/non-FHIR system URI (not in
    ``_FHIR_URI_TO_CODE_SYSTEM_KEY``) is left alone — no `.text` populated."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_cc_text_from_coding_lookup,
    )

    cc = {"coding": [{"system": "urn:some-unknown-system", "code": "X-1"}]}
    _populate_cc_text_from_coding_lookup(cc, lang="ja")
    assert "text" not in cc
