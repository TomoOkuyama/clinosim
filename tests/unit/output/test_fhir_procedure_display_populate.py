"""Issue #1036: JP Procedure emit loses display on SNOMED codings.

The P2 A walker (`_strip_japanese_display_on_english_only_systems`) drops
the Japanese `display` from every SNOMED coding on JP output. For
Condition and AllergyIntolerance a follow-up sibling-copy step
(`_copy_display_from_sibling_coding`) restores an English display via
`code_lookup(system, code, "en")`, but Procedure was outside that
step's scope — so `category` / `bodySite[]` / `performer[].function` /
`outcome` / `complication[]` / `reasonCode[]` all shipped with the
`display` field entirely absent.

This test covers the fix: a new `_populate_resource_coding_displays`
walker that recursively visits every `coding[]` list in a Procedure
resource and applies the same sibling-copy step.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _snomed_uri() -> str:
    return "http://snomed.info/sct"


def _make_procedure_with_stripped_displays() -> dict:
    """Build a Procedure resource shaped like the post-strip state: every
    SNOMED coding has `system` + `code` but no `display` field."""
    sct = _snomed_uri()
    return {
        "resourceType": "Procedure",
        "id": "proc-1036-fixture",
        "status": "completed",
        "category": {"coding": [{"system": sct, "code": "277132007"}]},
        "bodySite": [{"coding": [{"system": sct, "code": "80891009"}]}],
        "performer": [
            {
                "function": {"coding": [{"system": sct, "code": "304292004"}]},
                "actor": {"reference": "Practitioner/dr-1"},
            }
        ],
        "outcome": {"coding": [{"system": sct, "code": "385669000"}]},
        "complication": [{"coding": [{"system": sct, "code": "131148009"}]}],
    }


def test_populate_resource_coding_displays_fills_every_coding() -> None:
    """The recursive walker restores an English display on every SNOMED
    coding inside a Procedure resource, regardless of nesting depth
    (`category`, `bodySite[]`, `performer[].function`, `outcome`,
    `complication[]`)."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_resource_coding_displays,
    )

    proc = _make_procedure_with_stripped_displays()
    _populate_resource_coding_displays(proc, lang="ja")

    assert proc["category"]["coding"][0]["display"] == "Therapeutic procedure"
    assert proc["bodySite"][0]["coding"][0]["display"] == "Heart structure"
    assert proc["performer"][0]["function"]["coding"][0]["display"] == "Surgeon"
    assert proc["outcome"]["coding"][0]["display"] == "Successful"
    assert proc["complication"][0]["coding"][0]["display"] == "Bleeding"


def test_populate_resource_coding_displays_is_idempotent() -> None:
    """Running the walker a second time leaves the displays unchanged."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_resource_coding_displays,
    )

    proc = _make_procedure_with_stripped_displays()
    _populate_resource_coding_displays(proc, lang="ja")
    snapshot = {
        "category": proc["category"]["coding"][0]["display"],
        "bodySite": proc["bodySite"][0]["coding"][0]["display"],
        "outcome": proc["outcome"]["coding"][0]["display"],
    }
    _populate_resource_coding_displays(proc, lang="ja")
    assert proc["category"]["coding"][0]["display"] == snapshot["category"]
    assert proc["bodySite"][0]["coding"][0]["display"] == snapshot["bodySite"]
    assert proc["outcome"]["coding"][0]["display"] == snapshot["outcome"]


def test_populate_resource_coding_displays_preserves_existing_display() -> None:
    """A coding that already has a display is NOT overwritten."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_resource_coding_displays,
    )

    sct = _snomed_uri()
    proc = {
        "resourceType": "Procedure",
        "outcome": {
            "coding": [
                {"system": sct, "code": "385669000", "display": "Custom outcome label"},
            ],
        },
    }
    _populate_resource_coding_displays(proc, lang="ja")
    assert proc["outcome"]["coding"][0]["display"] == "Custom outcome label"


@pytest.mark.parametrize(
    "code,expected_display",
    [
        ("80891009", "Heart structure"),
        ("41801008", "Structure of coronary artery"),
        ("26107004", "Structure of small intestine"),
        ("30315005", "Structure of large intestine"),
    ],
)
def test_snomed_body_site_codes_added_to_yaml_1036(code: str, expected_display: str) -> None:
    """Issue #1036: 4 SNOMED body-site codes emitted from
    ``clinosim/modules/procedure/engine.py`` (ProcedureMeta bodySite)
    lacked a snomed-ct.yaml entry, so the sibling-copy walker's English
    fallback returned nothing. Pin their addition."""
    from clinosim.codes.loader import lookup

    assert lookup("snomed-ct", code, "en") == expected_display


def test_end_to_end_populate_fires_for_procedure_resource_type() -> None:
    """End-to-end: `_populate_condition_ai_mr_ecs_fields` dispatches to
    the Procedure walker when `resourceType == "Procedure"`."""
    from clinosim.modules.output.fhir_r4.post_process.populate import (
        _populate_condition_ai_mr_ecs_fields,
    )

    proc = _make_procedure_with_stripped_displays()
    _populate_condition_ai_mr_ecs_fields(proc, country="JP")

    assert proc["category"]["coding"][0]["display"] == "Therapeutic procedure"
    assert proc["outcome"]["coding"][0]["display"] == "Successful"
