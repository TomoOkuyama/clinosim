"""Issue #854 Bucket B (PR-document-reference): DocumentReference opaque
id + identifier round-trip + relatesTo + Composition.entry cross-ref
byte-consistency.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 →
#878 [lab] → #879 [vs/gcs/news2] → #880 [stand-alones] → #881
[mb-org/sus] → #882 [Specimen] → #883 [Condition] → #884 [DR] → #885
[ImagingStudy]) to `DocumentReference`.

Post-#854 every DocumentReference.id is ``doc-<12hex>`` (16 chars,
fixed). Structural key = pre-#854 CIF-doc-id body (with `doc-` prefix
stripped) or the fallback ``{enc}-{task}`` shape when CIF doc_id is
empty; preserved on ``identifier[]`` under
``DOCUMENT_REFERENCE_KEY_SYSTEM``.

Cross-reference sites:
- ``DocumentReference.relatesTo[].target.reference`` — sibling DR
  reference for the `appends` chain; routed through
  `document_reference_id_for_cif_doc_id`.
- ``Composition.section[].entry`` — via `_bb_compositions`' precomputed
  `enc_to_free_text` map, now populated with opaque ids.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.documents.documents import (
    DOCUMENT_REFERENCE_KEY_SYSTEM,
    _bb_document_references,
    _resolve_document_reference_id,
    document_reference_id_for_cif_doc_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_DR_PATTERN = re.compile(r"^doc-[0-9a-f]{12}$")


# === Resolver contract ===


def test_resolve_document_reference_id_opaque_shape() -> None:
    """Fixed 16 chars: ``doc-`` (4) + 12 hex."""
    result = _resolve_document_reference_id("ENC-001-progressnote-01")
    assert _OPAQUE_DR_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 16


def test_resolve_document_reference_id_deterministic() -> None:
    key = "ENC-001-progressnote-01"
    assert _resolve_document_reference_id(key) == _resolve_document_reference_id(key)


def test_document_reference_key_system_uri() -> None:
    assert DOCUMENT_REFERENCE_KEY_SYSTEM == "urn:clinosim:identifier:document-reference-key"


def test_document_reference_id_for_cif_doc_id_strips_prefix() -> None:
    from_cif = document_reference_id_for_cif_doc_id("doc-ENC-001-progressnote-01")
    from_stripped = _resolve_document_reference_id("ENC-001-progressnote-01")
    assert from_cif == from_stripped


def test_document_reference_id_for_cif_doc_id_handles_missing_prefix() -> None:
    """Idempotent on the prefix-strip step."""
    from_cif = document_reference_id_for_cif_doc_id("ENC-001-progressnote-01")
    from_stripped = _resolve_document_reference_id("ENC-001-progressnote-01")
    assert from_cif == from_stripped


# === Emit path ===


def _minimal_doc(*, document_id: str = "doc-ENC-001-progressnote-01") -> dict:
    return {
        "document_id": document_id,
        "format_type": "free_text",
        "encounter_id": "ENC-001",
        "task_type": "progressnote",
        "loinc_code": "11506-3",
        "authored_datetime": "2026-05-12T14:28:38",
        "language": "en",
        "narrative": {"text": "Progress note content here."},
    }


def _make_ctx(docs: list[dict], country: str = "US") -> SimpleNamespace:
    return SimpleNamespace(
        record={
            "patient": {"patient_id": "POP-1"},
            "documents": docs,
        },
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": "POP-1"},
        patient_id="POP-1",
        primary_enc_id="ENC-001",
    )


def test_bb_document_references_id_is_opaque_with_identifier() -> None:
    ctx = _make_ctx([_minimal_doc()])
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert _OPAQUE_DR_PATTERN.match(r["id"]), f"non-opaque DR id: {r['id']!r}"
    key_idents = [i for i in r.get("identifier", []) if i.get("system") == DOCUMENT_REFERENCE_KEY_SYSTEM]
    assert len(key_idents) == 1
    assert key_idents[0]["value"] == "ENC-001-progressnote-01"


def test_bb_document_references_masterIdentifier_uses_opaque_id() -> None:
    ctx = _make_ctx([_minimal_doc()])
    r = _bb_document_references(ctx)[0]
    assert r["masterIdentifier"]["value"] == r["id"]


def test_bb_document_references_internal_namespace_identifier_preserved() -> None:
    """The pre-existing `urn:clinosim:documentreference-id` identifier
    stays alongside the new structural-key identifier; consumers keyed
    on either system keep working."""
    ctx = _make_ctx([_minimal_doc()])
    r = _bb_document_references(ctx)[0]
    systems = {i["system"] for i in r["identifier"]}
    assert "urn:clinosim:documentreference-id" in systems
    assert DOCUMENT_REFERENCE_KEY_SYSTEM in systems


def test_bb_document_references_same_input_reproduces_same_id() -> None:
    ctx = _make_ctx([_minimal_doc()])
    a = _bb_document_references(ctx)
    b = _bb_document_references(ctx)
    assert a[0]["id"] == b[0]["id"]


def test_bb_document_references_fallback_key_when_document_id_empty() -> None:
    """When CIF doc.document_id is empty, structural key = `{enc}-{task}`."""
    doc = _minimal_doc(document_id="")
    ctx = _make_ctx([doc])
    r = _bb_document_references(ctx)[0]
    assert _OPAQUE_DR_PATTERN.match(r["id"])
    key_idents = [i for i in r.get("identifier", []) if i.get("system") == DOCUMENT_REFERENCE_KEY_SYSTEM]
    assert key_idents[0]["value"] == "ENC-001-progressnote"


# === relatesTo cross-ref byte-consistency ===


def test_relates_to_reference_routes_through_shared_resolver() -> None:
    """Two progress notes on the same (encounter, loinc) form an
    `appends` chain: the second's `relatesTo.target.reference` MUST
    equal the first's opaque `.id` (which the writer emitted via the
    shared resolver)."""
    doc1 = _minimal_doc(document_id="doc-ENC-001-progressnote-01")
    doc1["authored_datetime"] = "2026-05-12T09:00:00"
    doc2 = _minimal_doc(document_id="doc-ENC-001-progressnote-02")
    doc2["authored_datetime"] = "2026-05-12T15:00:00"
    ctx = _make_ctx([doc1, doc2])
    resources = _bb_document_references(ctx)
    assert len(resources) == 2

    # Locate first / second by structural-key identifier value.
    def _by_key(value: str) -> dict:
        for r in resources:
            for i in r.get("identifier", []):
                if i.get("system") == DOCUMENT_REFERENCE_KEY_SYSTEM and i.get("value") == value:
                    return r
        raise AssertionError(f"no DR with structural key {value!r}")

    first = _by_key("ENC-001-progressnote-01")
    second = _by_key("ENC-001-progressnote-02")

    # First has no relatesTo (nothing prior).
    assert "relatesTo" not in first, f"first DR must not have relatesTo, got {first.get('relatesTo')!r}"
    # Second appends first, and the reference is the OPAQUE id of first.
    rt = second.get("relatesTo", [])
    assert len(rt) == 1
    assert rt[0]["code"] == "appends"
    assert rt[0]["target"]["reference"] == f"DocumentReference/{first['id']}"


# === Coverage guard ===


def test_all_dr_ids_from_in_process_emit_are_opaque() -> None:
    """Emit multiple DRs and assert every id matches the opaque pattern."""
    docs = [_minimal_doc(document_id=f"doc-ENC-001-progressnote-{i:02d}") for i in range(1, 4)]
    for i, d in enumerate(docs):
        d["authored_datetime"] = f"2026-05-12T{9 + i:02d}:00:00"
    ctx = _make_ctx(docs)
    resources = _bb_document_references(ctx)
    ids = [r["id"] for r in resources]
    assert len(ids) == 3
    for rid in ids:
        assert _OPAQUE_DR_PATTERN.match(rid), f"non-opaque DR id leaked: {rid!r}"
