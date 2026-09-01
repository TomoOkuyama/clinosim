"""Issue #1038: JP Composition loses LOINC display on interop coding.

The P2 A walker (`_strip_japanese_display_on_english_only_systems`)
drops the Japanese `display` from every LOINC coding on JP output. For
Condition/AllergyIntolerance a sibling-copy step restores an English
display via `code_lookup(system, code, "en")`; #1036 extended the same
step to Procedure. #1038 extends it to Composition: JP `Composition.type`
and `Composition.section.code` interop-secondary LOINC codings (~2,190+
sites in the p=10000 seed=100 cohort) previously shipped without any
`display` field.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


LOINC_URI = "http://loinc.org"
JP_DOC_TYPECODE_URI = "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/doc-typecodes"


def _make_composition_with_stripped_loinc_displays() -> dict:
    """Post-strip Composition: JP-native coding carries its JP display,
    LOINC secondary coding has `system` + `code` but no `display`."""
    return {
        "resourceType": "Composition",
        "id": "comp-1038-fixture",
        "status": "final",
        "type": {
            "coding": [
                {"system": JP_DOC_TYPECODE_URI, "code": "18842-5", "display": "退院時サマリー"},
                {"system": LOINC_URI, "code": "34131-3"},
            ],
        },
        "section": [
            {
                "title": "現病歴",
                "code": {"coding": [{"system": LOINC_URI, "code": "10164-2"}]},
            },
            {
                "title": "バイタルサイン",
                "code": {"coding": [{"system": LOINC_URI, "code": "8716-3"}]},
            },
            {
                "title": "評価",
                "code": {"coding": [{"system": LOINC_URI, "code": "51848-0"}]},
            },
            {
                "title": "入院診療計画書",
                "code": {"coding": [{"system": LOINC_URI, "code": "18776-5"}]},
            },
        ],
    }


def test_populate_fills_composition_type_loinc_display() -> None:
    """`Composition.type` LOINC secondary coding gets an English display
    via `code_lookup("loinc", code, "en")`."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_resource_coding_displays,
    )

    comp = _make_composition_with_stripped_loinc_displays()
    _populate_resource_coding_displays(comp, lang="ja")

    codings = comp["type"]["coding"]
    loinc = next(c for c in codings if c.get("system") == LOINC_URI)
    assert loinc.get("display") == "Outpatient Progress note"

    # JP-native coding is untouched
    jp = next(c for c in codings if c.get("system") == JP_DOC_TYPECODE_URI)
    assert jp["display"] == "退院時サマリー"


def test_populate_fills_composition_section_code_loinc_display() -> None:
    """Every `Composition.section[].code.coding[]` LOINC entry gets an
    English display."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_resource_coding_displays,
    )

    comp = _make_composition_with_stripped_loinc_displays()
    _populate_resource_coding_displays(comp, lang="ja")

    section_displays = [s["code"]["coding"][0]["display"] for s in comp["section"]]
    assert section_displays == [
        "History of Present illness Narrative",
        "Vital signs",
        "Evaluation note",
        "Plan of care note",
    ]


def test_populate_via_dispatcher_fires_for_composition() -> None:
    """`_populate_condition_ai_mr_ecs_fields` recognises Composition and
    routes it through the recursive walker."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_condition_ai_mr_ecs_fields,
    )

    comp = _make_composition_with_stripped_loinc_displays()
    _populate_condition_ai_mr_ecs_fields(comp, country="JP")

    loinc = next(c for c in comp["type"]["coding"] if c.get("system") == LOINC_URI)
    assert loinc.get("display") == "Outpatient Progress note"


def test_populate_is_idempotent_on_composition() -> None:
    """Running the walker twice on a Composition is a no-op the second time."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_resource_coding_displays,
    )

    comp = _make_composition_with_stripped_loinc_displays()
    _populate_resource_coding_displays(comp, lang="ja")
    snapshot = comp["section"][0]["code"]["coding"][0]["display"]
    _populate_resource_coding_displays(comp, lang="ja")
    assert comp["section"][0]["code"]["coding"][0]["display"] == snapshot


def test_populate_preserves_existing_display_on_composition() -> None:
    """A coding that already has a display is NOT overwritten."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_resource_coding_displays,
    )

    comp = {
        "resourceType": "Composition",
        "type": {
            "coding": [
                {"system": LOINC_URI, "code": "34131-3", "display": "Custom LOINC display"},
            ],
        },
    }
    _populate_resource_coding_displays(comp, lang="ja")
    assert comp["type"]["coding"][0]["display"] == "Custom LOINC display"
