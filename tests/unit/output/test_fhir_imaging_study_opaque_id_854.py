"""Issue #854 Bucket B (PR-imaging-study): ImagingStudy opaque id +
identifier round-trip + DR.imagingStudy[] byte-consistency.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 →
#878 [lab] → #879 [vs/gcs/news2] → #880 [stand-alones] → #881 [mb-org/sus]
→ #882 [Specimen] → #883 [Condition] → #884 [DR]) to `ImagingStudy`.

Post-#854 every ImagingStudy.id is ``imgst-<12hex>`` (18 chars, fixed).

Structural key = CIF-side ``study.study_id`` (`imgst-{enc}-{idx}`) with
the `imgst-` prefix stripped, preserved on ``identifier[]`` under
``IMAGING_STUDY_KEY_SYSTEM``. Every cross-reference (`DR.imagingStudy[]`,
`DR.media[].link`) funnels through the shared
``imaging_study_id_for_cif_study_id`` helper so byte-consistency is
preserved by construction.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.imaging_study import (
    DICOM_UID_SYSTEM,
    IMAGING_STUDY_ID_PREFIX,
    IMAGING_STUDY_KEY_SYSTEM,
    _bb_imaging_studies,
    _resolve_imaging_study_id,
    imaging_study_id_for_cif_study_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_IMAGING_STUDY_PATTERN = re.compile(r"^imgst-[0-9a-f]{12}$")


# === Resolver contract ===


def test_resolve_imaging_study_id_opaque_shape() -> None:
    """Fixed 18 chars: ``imgst-`` (6) + 12 hex."""
    result = _resolve_imaging_study_id("enc1-1")
    assert _OPAQUE_IMAGING_STUDY_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 18


def test_resolve_imaging_study_id_deterministic() -> None:
    key = "enc1-1"
    assert _resolve_imaging_study_id(key) == _resolve_imaging_study_id(key)


def test_imaging_study_id_prefix_constant() -> None:
    assert IMAGING_STUDY_ID_PREFIX == "imgst-"


def test_imaging_study_key_system_uri() -> None:
    assert IMAGING_STUDY_KEY_SYSTEM == "urn:clinosim:identifier:imaging-study-key"


def test_imaging_study_id_for_cif_study_id_strips_prefix() -> None:
    """Convenience wrapper accepts the CIF study_id verbatim
    (which carries the `imgst-` prefix) and returns the opaque FHIR id."""
    from_cif = imaging_study_id_for_cif_study_id("imgst-enc1-1")
    from_stripped = _resolve_imaging_study_id("enc1-1")
    assert from_cif == from_stripped


def test_imaging_study_id_for_cif_study_id_handles_missing_prefix() -> None:
    """Defensive: an already-stripped key produces the same id (idempotent
    on the prefix-strip step)."""
    from_cif = imaging_study_id_for_cif_study_id("enc1-1")
    from_stripped = _resolve_imaging_study_id("enc1-1")
    assert from_cif == from_stripped


# === Emit path — _bb_imaging_studies ===


def _study_dict(*, study_id: str = "imgst-enc1-1", encounter_id: str = "enc1") -> dict:
    return {
        "study_id": study_id,
        "study_instance_uid": "1.2.840.113619.2.5.1.4.99.99.101.1",
        "encounter_id": encounter_id,
        "patient_id": "POP-1",
        "order_id": "ord1",
        "status": "available",
        "started_datetime": "2026-05-12T14:28:00",
        "modality_code": "CT",
        "series": [],
    }


def _make_ctx(studies: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        record={
            "patient": {"patient_id": "POP-1"},
            "encounters": [],
            "extensions": {"imaging": studies},
        },
        country="US",
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": "POP-1"},
        patient_id="POP-1",
        primary_enc_id="enc1",
    )


def test_bb_imaging_studies_id_is_opaque() -> None:
    ctx = _make_ctx([_study_dict()])
    resources = _bb_imaging_studies(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert _OPAQUE_IMAGING_STUDY_PATTERN.match(r["id"]), f"non-opaque ImagingStudy id: {r['id']!r}"


def test_bb_imaging_studies_identifier_carries_structural_key_and_dicom_uid() -> None:
    ctx = _make_ctx([_study_dict()])
    r = _bb_imaging_studies(ctx)[0]
    idents = r.get("identifier") or []
    systems = {i["system"] for i in idents}
    assert DICOM_UID_SYSTEM in systems, f"DICOM UID identifier missing, got {systems!r}"
    assert IMAGING_STUDY_KEY_SYSTEM in systems, f"structural-key identifier missing, got {systems!r}"
    key_idents = [i for i in idents if i["system"] == IMAGING_STUDY_KEY_SYSTEM]
    assert key_idents[0]["value"] == "enc1-1"


def test_bb_imaging_studies_same_input_reproduces_same_id() -> None:
    ctx = _make_ctx([_study_dict()])
    a = _bb_imaging_studies(ctx)
    b = _bb_imaging_studies(ctx)
    assert a[0]["id"] == b[0]["id"]


def test_bb_imaging_studies_multiple_produce_distinct_opaque_ids() -> None:
    ctx = _make_ctx([_study_dict(study_id="imgst-enc1-1"), _study_dict(study_id="imgst-enc1-2")])
    resources = _bb_imaging_studies(ctx)
    ids = [r["id"] for r in resources]
    assert len(ids) == 2 and len(set(ids)) == 2
    for rid in ids:
        assert _OPAQUE_IMAGING_STUDY_PATTERN.match(rid)


# === Cross-reference byte-consistency guard ===


def test_dr_imaging_study_reference_matches_writer() -> None:
    """DR.imagingStudy[] / DR.media[].link references MUST resolve via
    the same helper the ImagingStudy writer uses. A drift here would
    detach every radiology DR from its ImagingStudy without any FHIR
    schema error (same silent-no-op class the lab PR #878 guarded)."""
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _bb_diagnostic_reports

    # Emit the ImagingStudy first, then the radiology DR from the same
    # CIF `study` record and assert the DR's imagingStudy reference lands
    # on the writer's id.
    study = _study_dict()
    study["report"] = {
        "report_id": "imgrpt-enc1-1",
        "findings_text": "Right lower lobe consolidation.",
        "impression_text": "Pneumonia.",
        "impression_text_ja": "肺炎。",
        "findings_codes": [],
    }
    ctx = _make_ctx([study])
    is_resources = _bb_imaging_studies(ctx)
    assert len(is_resources) == 1
    writer_id = is_resources[0]["id"]

    dr_resources = _bb_diagnostic_reports(ctx)
    rad_drs = [r for r in dr_resources if r.get("id", "").startswith("imgrpt-")]
    assert rad_drs, "expected 1 radiology DR"
    dr = rad_drs[0]
    assert dr["imagingStudy"][0]["reference"] == f"ImagingStudy/{writer_id}"
    assert dr["media"][0]["link"]["reference"] == f"ImagingStudy/{writer_id}"


# === Coverage guard ===


def test_all_imaging_study_ids_from_in_process_emit_are_opaque() -> None:
    """Drive multiple studies through the emitter and assert every
    ImagingStudy.id is opaque."""
    ctx = _make_ctx(
        [
            _study_dict(study_id="imgst-enc1-1"),
            _study_dict(study_id="imgst-enc1-2"),
            _study_dict(study_id="imgst-enc2-1", encounter_id="enc2"),
        ]
    )
    resources = _bb_imaging_studies(ctx)
    ids = [r["id"] for r in resources]
    assert ids
    for rid in ids:
        assert _OPAQUE_IMAGING_STUDY_PATTERN.match(rid), f"non-opaque ImagingStudy id leaked: {rid!r}"
