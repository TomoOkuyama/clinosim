"""Issue #854 Bucket B (PR-composition): Composition opaque id + cross-ref
byte-consistency across the two emit paths.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 →
#878 [lab] → #879 [vs/gcs/news2] → #880 [stand-alones] → #881
[mb-org/sus] → #882 [Specimen] → #883 [Condition] → #884 [DR] → #885
[ImagingStudy] → #886 [DocumentReference]) to `Composition`.

Post-#854 every Composition.id is ``comp-<12hex>`` (17 chars, fixed).

Two Composition emit paths, both funnel through the shared resolver:
- general (`_build_composition_generic` in composition.py): structural
  key = pre-#854 id body (the CIF-doc-id body with `doc-` prefix
  stripped).
- radiology imgrpt (`_build_imaging_report_composition` in
  imaging_report.py): structural key = `{encounter_id}-imgrpt-{seq}`.

Cross-reference site: `DocumentReference.relatesTo[].target.reference`
in the health-checkup DR builder, routed through the shared
`_resolve_composition_id` helper.
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.documents.composition import _resolve_composition_id

pytestmark = pytest.mark.unit


_OPAQUE_COMPOSITION_PATTERN = re.compile(r"^comp-[0-9a-f]{12}$")


# === Resolver contract ===


def test_resolve_composition_id_opaque_shape() -> None:
    """Fixed 17 chars: ``comp-`` (5) + 12 hex."""
    result = _resolve_composition_id("enc1-hp-1")
    assert _OPAQUE_COMPOSITION_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 17


def test_resolve_composition_id_deterministic() -> None:
    key = "enc1-hp-1"
    assert _resolve_composition_id(key) == _resolve_composition_id(key)


def test_general_and_imgrpt_structural_keys_produce_distinct_ids() -> None:
    """A general Composition and a radiology Composition for the same
    encounter must not collide — the imgrpt structural key includes
    the `imgrpt-{seq}` differentiator."""
    a = _resolve_composition_id("enc1-hp-1")
    b = _resolve_composition_id("enc1-imgrpt-1")
    assert a != b


# === Emit path — general (composition.py) ===


def test_build_composition_generic_id_is_opaque() -> None:
    from clinosim.modules.output.fhir_r4.documents.composition import _build_composition

    doc = {
        "document_id": "doc-enc1-hp-1",
        "loinc_code": "34117-2",
        "patient_id": "pt1",
        "encounter_id": "enc1",
        "language": "en",
        "format_type": "composition",
        "authored_datetime": "2026-05-12T14:00:00",
    }
    r = _build_composition(doc, sections={}, lang="en")
    assert _OPAQUE_COMPOSITION_PATTERN.match(r["id"]), f"non-opaque Composition id: {r['id']!r}"
    # Structural key = doc-id body (with `doc-` prefix stripped).
    assert r["id"] == _resolve_composition_id("enc1-hp-1")


def test_build_composition_generic_identifier_value_matches_id() -> None:
    """The pre-existing `Composition.identifier.value` slot carries
    the emitted opaque `.id` so downstream consumers using
    `identifier.value` recover the emitted id verbatim."""
    from clinosim.modules.output.fhir_r4.documents.composition import _build_composition

    doc = {
        "document_id": "doc-enc1-hp-1",
        "loinc_code": "34117-2",
        "patient_id": "pt1",
        "encounter_id": "enc1",
        "language": "en",
        "format_type": "composition",
        "authored_datetime": "2026-05-12T14:00:00",
    }
    r = _build_composition(doc, sections={}, lang="en")
    assert r["identifier"]["value"] == r["id"]


# === Emit path — radiology imgrpt (imaging_report.py) ===


def test_imaging_report_composition_id_is_opaque() -> None:
    """The imgrpt Composition builder derives its id from the
    `{encounter_id}-imgrpt-{seq}` structural key via the shared
    resolver."""
    expected = _resolve_composition_id("enc1-imgrpt-1")
    assert _OPAQUE_COMPOSITION_PATTERN.match(expected)
