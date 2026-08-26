"""Issue #854 Bucket B (PR-clinical-impression): CI opaque id +
identifier round-trip.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 →
#878 [lab] → #879 [vs/gcs/news2] → #880 [stand-alones] → #881
[mb-org/sus] → #882 [Specimen] → #883 [Condition] → #884 [DR] → #885
[ImagingStudy] → #886 [DocumentReference] → #887 [Composition]) to
`ClinicalImpression`.

Post-#854 every ClinicalImpression.id is ``ci-<12hex>`` (15 chars,
fixed). Structural key = pre-#854 CIF ``impression.impression_id``
body (with `ci-` prefix stripped) — the resolver is idempotent on the
strip step so both prefixed and un-prefixed CIF ids produce the same
opaque emit output. ClinicalImpression is stand-alone in the FHIR
reference graph on this sample — no cross-ref cascade guard needed.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.conditions.clinical_impression import (
    CLINICAL_IMPRESSION_KEY_SYSTEM,
    _bb_clinical_impressions,
    _resolve_clinical_impression_id,
    clinical_impression_id_for_cif_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_CI_PATTERN = re.compile(r"^ci-[0-9a-f]{12}$")


# === Resolver contract ===


def test_resolve_ci_id_opaque_shape() -> None:
    """Fixed 15 chars: ``ci-`` (3) + 12 hex."""
    result = _resolve_clinical_impression_id("enc1-0")
    assert _OPAQUE_CI_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 15


def test_resolve_ci_id_deterministic() -> None:
    key = "enc1-0"
    assert _resolve_clinical_impression_id(key) == _resolve_clinical_impression_id(key)


def test_ci_key_system_uri() -> None:
    assert CLINICAL_IMPRESSION_KEY_SYSTEM == "urn:clinosim:identifier:clinical-impression-key"


def test_convenience_wrapper_strips_prefix() -> None:
    from_cif = clinical_impression_id_for_cif_id("ci-enc1-0")
    from_stripped = _resolve_clinical_impression_id("enc1-0")
    assert from_cif == from_stripped


def test_convenience_wrapper_idempotent_on_stripped_key() -> None:
    from_cif = clinical_impression_id_for_cif_id("enc1-0")
    from_stripped = _resolve_clinical_impression_id("enc1-0")
    assert from_cif == from_stripped


# === Emit path ===


def _sample_impression_dict() -> dict:
    return {
        "impression_id": "ci-enc1-0",
        "encounter_id": "enc1",
        "date": "2026-07-01",
        "day_index": 0,
        "description": "Day 0: Admitted with pneumonia.",
        "summary": "Patient in stable condition.",
        "investigation_refs": [],
        "finding_refs": [],
        "prognosis": "Favorable with antibiotic therapy.",
        "practitioner_id": "staff-001",
    }


def _make_ctx(impressions: list) -> SimpleNamespace:
    return SimpleNamespace(
        record={"extensions": {"clinical_impressions": impressions}, "patient": {}},
        country="us",
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        patient_sex="",
    )


def test_bb_clinical_impressions_id_is_opaque_with_identifier() -> None:
    ctx = _make_ctx([_sample_impression_dict()])
    resources = _bb_clinical_impressions(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert _OPAQUE_CI_PATTERN.match(r["id"]), f"non-opaque CI id: {r['id']!r}"
    key_idents = [i for i in r.get("identifier", []) if i.get("system") == CLINICAL_IMPRESSION_KEY_SYSTEM]
    assert len(key_idents) == 1
    assert key_idents[0]["value"] == "enc1-0"


def test_bb_clinical_impressions_same_input_reproduces_same_id() -> None:
    ctx = _make_ctx([_sample_impression_dict()])
    a = _bb_clinical_impressions(ctx)
    b = _bb_clinical_impressions(ctx)
    assert a[0]["id"] == b[0]["id"]


def test_prefixed_and_unprefixed_cif_ids_produce_same_opaque_output() -> None:
    """Idempotent on the `ci-` prefix strip step — both pre-#854 and
    post-#854 CIF impression_id shapes hash to the same opaque emit."""
    d_prefixed = _sample_impression_dict()  # impression_id = "ci-enc1-0"
    d_unprefixed = _sample_impression_dict()
    d_unprefixed["impression_id"] = "enc1-0"
    r_prefixed = _bb_clinical_impressions(_make_ctx([d_prefixed]))[0]
    r_unprefixed = _bb_clinical_impressions(_make_ctx([d_unprefixed]))[0]
    assert r_prefixed["id"] == r_unprefixed["id"]


def test_bb_clinical_impressions_multiple_produce_distinct_ids() -> None:
    d1 = _sample_impression_dict()
    d2 = _sample_impression_dict()
    d2["impression_id"] = "ci-enc1-1"
    d2["day_index"] = 1
    resources = _bb_clinical_impressions(_make_ctx([d1, d2]))
    assert len(resources) == 2
    ids = [r["id"] for r in resources]
    assert len(set(ids)) == 2
    for rid in ids:
        assert _OPAQUE_CI_PATTERN.match(rid), f"non-opaque CI id leaked: {rid!r}"
