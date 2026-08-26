"""Issue #854 Bucket B (PR-specimen): Specimen opaque id + identifier
round-trip + cross-ref byte-consistency across both Specimen producers.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 →
#878 [lab] → #879 [vs/gcs/news2] → #880 [stand-alones] → #881 [mb-org/sus])
to ``Specimen`` — the first per-type PR of Bucket B.

Two distinct emit sites both funnel through the SAME
``_resolve_specimen_id`` shared helper:

- ``labs/microbiology.py::_bb_microbiology`` — culture Specimen
  (structural key = ``{enc or patient_id}-{i}`` where i is the 0-based
  culture index). Cross-refs: ``mb-org.specimen`` + ``mb-sus.specimen`` +
  ``mb-DR.specimen[]``.
- ``post_process/specimen.py::_build_companion_specimen`` — synthetic
  per-lab-Observation Specimen (structural key = parent lab Observation.id,
  which is itself an opaque ``lab-<12hex>`` post-#878). Cross-ref:
  ``Observation.specimen`` on every lab Observation that lacked a
  builder-set specimen.

Post-#854 every Specimen.id is ``spec-<12hex>`` (17 chars, fixed).

Reference-integrity guard: both cross-ref sites (``Observation.specimen``,
``DR.specimen[]``) receive ``spec_id`` via variable propagation from the
emit site, so byte-consistency is preserved by construction — the same
resolver call feeds both the id emit and every cross-ref that references
it. A drift here would detach every Specimen from its Observations /
DR without any FHIR-schema error.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.microbiology import _bb_microbiology
from clinosim.modules.output.fhir_r4.post_process.specimen import (
    SPECIMEN_ID_PREFIX,
    SPECIMEN_KEY_SYSTEM,
    _build_companion_specimen,
    _resolve_specimen_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_SPECIMEN_PATTERN = re.compile(r"^spec-[0-9a-f]{12}$")


# === Resolver contract ===


def test_resolve_specimen_id_opaque_shape() -> None:
    """Fixed 17 chars: ``spec-`` (5) + 12 hex."""
    result = _resolve_specimen_id("ENC-POP-000012-abc-0")
    assert _OPAQUE_SPECIMEN_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 17


def test_resolve_specimen_id_deterministic() -> None:
    key = "ENC-POP-000012-abc-0"
    assert _resolve_specimen_id(key) == _resolve_specimen_id(key)


def test_resolve_specimen_id_distinguishes_different_keys() -> None:
    assert _resolve_specimen_id("ENC-001-0") != _resolve_specimen_id("ENC-001-1")
    assert _resolve_specimen_id("ENC-001-0") != _resolve_specimen_id("ENC-002-0")


def test_specimen_key_system_uri() -> None:
    assert SPECIMEN_KEY_SYSTEM == "urn:clinosim:identifier:specimen-key"


def test_specimen_id_prefix_constant() -> None:
    assert SPECIMEN_ID_PREFIX == "spec-"


# === Companion Specimen (post_process/specimen.py) ===


def test_companion_specimen_id_is_opaque_with_identifier() -> None:
    """Companion Specimen id resolves from the parent Observation.id."""
    obs = {"resourceType": "Observation", "id": "lab-a1b2c3d4e5f6", "subject": {"reference": "Patient/pt1"}}
    s = _build_companion_specimen(obs, country="US")
    assert _OPAQUE_SPECIMEN_PATTERN.match(s["id"]), f"non-opaque companion Specimen id: {s['id']!r}"
    # Both identifiers present: internal namespace (value = opaque id) +
    # structural-key round-trip.
    idents = s["identifier"]
    systems = {i["system"] for i in idents}
    assert "urn:clinosim:specimen-id" in systems
    assert SPECIMEN_KEY_SYSTEM in systems
    key_idents = [i for i in idents if i["system"] == SPECIMEN_KEY_SYSTEM]
    assert key_idents[0]["value"] == "lab-a1b2c3d4e5f6"


def test_companion_specimen_same_observation_reproduces_same_id() -> None:
    obs = {"resourceType": "Observation", "id": "lab-abc123", "subject": {"reference": "Patient/pt1"}}
    a = _build_companion_specimen(obs, country="JP")
    b = _build_companion_specimen(obs, country="JP")
    assert a["id"] == b["id"]


# === Microbiology Specimen ===


def _mb_ctx(cultures: list, *, encounter_id: str = "ENC-001", country: str = "US") -> SimpleNamespace:
    return SimpleNamespace(
        record={
            "patient": {"patient_id": "POP-000002"},
            "microbiology": cultures,
            "encounters": [{"encounter_id": encounter_id, "attending_physician_id": "STAFF-001"}],
        },
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": "POP-000002"},
        patient_id="POP-000002",
        primary_enc_id=encounter_id,
    )


def _sample_culture() -> dict:
    return {
        "specimen": "blood",
        "test_loinc": "600-7",
        "specimen_snomed": "119297000",
        "collected_datetime": "2026-05-12T14:28:38",
        "reported_datetime": "2026-05-13T09:00:00",
        "growth": True,
        "organism_snomed": "3092008",
        "susceptibilities": [{"antibiotic_loinc": "18866-6", "interpretation": "S"}],
    }


def test_microbiology_specimen_id_is_opaque_with_identifier() -> None:
    ctx = _mb_ctx([_sample_culture()])
    resources = _bb_microbiology(ctx)
    specs = [r for r in resources if r["resourceType"] == "Specimen"]
    assert len(specs) == 1
    s = specs[0]
    assert _OPAQUE_SPECIMEN_PATTERN.match(s["id"]), f"non-opaque mb Specimen id: {s['id']!r}"
    key_idents = [i for i in s.get("identifier", []) if i.get("system") == SPECIMEN_KEY_SYSTEM]
    assert len(key_idents) == 1
    assert key_idents[0]["value"] == "ENC-001-0"


def test_microbiology_hai_identifier_preserved_alongside_structural_key() -> None:
    culture = _sample_culture()
    culture["hai_event_id"] = "HAI-EVENT-99"
    ctx = _mb_ctx([culture])
    resources = _bb_microbiology(ctx)
    specs = [r for r in resources if r["resourceType"] == "Specimen"]
    assert len(specs) == 1
    idents = specs[0]["identifier"]
    systems = {i["system"] for i in idents}
    assert "urn:clinosim:identifier:hai-event-id" in systems, f"HAI missing from {idents!r}"
    assert SPECIMEN_KEY_SYSTEM in systems, f"structural key missing from {idents!r}"


def test_microbiology_cross_refs_use_opaque_specimen_ids() -> None:
    """The critical byte-consistency invariant: every ``Observation.specimen``
    and ``DR.specimen[]`` reference resolves to a Specimen in the emit set."""
    ctx = _mb_ctx([_sample_culture()])
    resources = _bb_microbiology(ctx)
    specimen_ids = {r["id"] for r in resources if r["resourceType"] == "Specimen"}
    obs_specimen_refs: list[str] = []
    dr_specimen_refs: list[str] = []
    for r in resources:
        if r["resourceType"] == "Observation":
            ref = r.get("specimen", {}).get("reference", "")
            if ref:
                obs_specimen_refs.append(ref)
        elif r["resourceType"] == "DiagnosticReport":
            for entry in r.get("specimen", []):
                dr_specimen_refs.append(entry.get("reference", ""))
    assert obs_specimen_refs, "expected mb-org / mb-sus Observations to reference their Specimen"
    assert dr_specimen_refs, "expected mb DR to reference its Specimen"

    all_refs = obs_specimen_refs + dr_specimen_refs
    dangling = [ref for ref in all_refs if ref.removeprefix("Specimen/") not in specimen_ids]
    assert not dangling, f"Specimen cross-references detached from Specimen set: {dangling}"

    # Every ref must land on the opaque shape.
    for ref in all_refs:
        rid = ref.removeprefix("Specimen/")
        assert _OPAQUE_SPECIMEN_PATTERN.match(rid), f"non-opaque cross-ref: {ref!r}"


def test_microbiology_multiple_cultures_produce_distinct_specimen_ids() -> None:
    ctx = _mb_ctx([_sample_culture(), _sample_culture()])
    resources = _bb_microbiology(ctx)
    spec_ids = [r["id"] for r in resources if r["resourceType"] == "Specimen"]
    assert len(spec_ids) == 2 and len(set(spec_ids)) == 2


# === Coverage guard ===


def test_all_specimen_ids_from_in_process_emit_are_opaque() -> None:
    """Drive both Specimen producers end-to-end and assert every emitted
    ``spec-*`` id matches the opaque pattern."""
    # Microbiology emit.
    ctx = _mb_ctx([_sample_culture(), _sample_culture()])
    mb_resources = _bb_microbiology(ctx)
    mb_spec_ids = [r["id"] for r in mb_resources if r["resourceType"] == "Specimen"]

    # Companion emit — fabricate two lab Observations with distinct ids.
    companion_a = _build_companion_specimen(
        {"resourceType": "Observation", "id": "lab-aaa000000000", "subject": {"reference": "Patient/pt1"}},
        country="JP",
    )
    companion_b = _build_companion_specimen(
        {"resourceType": "Observation", "id": "lab-bbb000000000", "subject": {"reference": "Patient/pt1"}},
        country="JP",
    )
    companion_ids = [companion_a["id"], companion_b["id"]]

    all_ids = mb_spec_ids + companion_ids
    assert all_ids, "fixture should emit at least one Specimen"
    non_opaque = [rid for rid in all_ids if not _OPAQUE_SPECIMEN_PATTERN.match(rid)]
    assert not non_opaque, f"non-opaque Specimen id leaked: {non_opaque[:3]}"
