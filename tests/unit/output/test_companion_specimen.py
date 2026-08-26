"""Unit tests for companion-Specimen emission for lab Observations.

JP-CLINS `JP_Observation_LabResult_eCS` declares `Observation.specimen`
with `min=1`. clinosim lab Observations (id prefix `lab-`) get a paired
Specimen resource so the min=1 constraint is satisfied for both JP and US
output without touching each lab builder.

Feedback fix (2026-07-16, PR-E).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.post_process import (
    _build_companion_specimen,
    _lab_observation_needs_specimen,
    _pick_specimen_type_for_lab,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Detection: which Observations need a companion Specimen
# ---------------------------------------------------------------------------


def test_lab_observation_needs_specimen_when_id_starts_lab():
    r = {"resourceType": "Observation", "id": "lab-enc-1-0000"}
    assert _lab_observation_needs_specimen(r) is True


def test_lab_observation_skipped_when_id_not_lab_prefix():
    """vital-signs / social-history / imaging IDs do NOT trigger emission."""
    for prefix in ("vs-enc-1", "smoking-POP-1", "img-enc-1", "mb-org-1", "alcohol-POP-1"):
        r = {"resourceType": "Observation", "id": f"{prefix}-0000"}
        assert _lab_observation_needs_specimen(r) is False


def test_lab_observation_skipped_when_specimen_already_set():
    """Microbiology Observations set specimen; walker must not overwrite."""
    r = {"resourceType": "Observation", "id": "lab-enc-1-0000", "specimen": {"reference": "Specimen/preset"}}
    assert _lab_observation_needs_specimen(r) is False


def test_lab_observation_skipped_when_not_observation():
    r = {"resourceType": "Patient", "id": "lab-enc-1-0000"}
    assert _lab_observation_needs_specimen(r) is False


# ---------------------------------------------------------------------------
# Specimen type: blood by default, urine for Urinalysis
# ---------------------------------------------------------------------------


def test_pick_specimen_type_defaults_to_blood():
    r = {"code": {"text": "White blood cell count", "coding": [{"display": "WBC count"}]}}
    entry = _pick_specimen_type_for_lab(r)
    assert entry["code"] == "119297000"


def test_pick_specimen_type_urine_for_urinalysis():
    r = {"code": {"text": "Urinalysis", "coding": []}}
    entry = _pick_specimen_type_for_lab(r)
    assert entry["code"] == "122575003"


def test_pick_specimen_type_urine_from_coding_display():
    r = {"code": {"text": "", "coding": [{"display": "Urine glucose"}]}}
    entry = _pick_specimen_type_for_lab(r)
    assert entry["code"] == "122575003"


# ---------------------------------------------------------------------------
# Build shape (id, subject, type, collection, identifier)
# ---------------------------------------------------------------------------


def test_build_companion_specimen_id_derived_from_observation_id():
    """Issue #854 Bucket B (PR-specimen): id is opaque ``spec-<12hex>`` derived
    from the parent Observation.id via the shared resolver."""
    from clinosim.modules.output.fhir_r4.post_process.specimen import _resolve_specimen_id

    r = {"resourceType": "Observation", "id": "lab-enc-1-0000", "subject": {"reference": "Patient/pt1"}}
    s = _build_companion_specimen(r, country="US")
    assert s["id"] == _resolve_specimen_id("lab-enc-1-0000")


def test_build_companion_specimen_copies_subject():
    r = {"resourceType": "Observation", "id": "lab-enc-1-0000", "subject": {"reference": "Patient/pt42"}}
    s = _build_companion_specimen(r, country="US")
    assert s["subject"] == {"reference": "Patient/pt42"}


def test_build_companion_specimen_blood_type_us():
    r = {"resourceType": "Observation", "id": "lab-enc-1-0000", "subject": {"reference": "Patient/pt1"}}
    s = _build_companion_specimen(r, country="US")
    coding = s["type"]["coding"][0]
    assert coding["code"] == "119297000"
    assert coding["system"] == "http://snomed.info/sct"
    assert coding["display"] == "Blood specimen"
    assert s["type"]["text"] == "Blood specimen"


def test_build_companion_specimen_blood_type_jp_localized():
    r = {"resourceType": "Observation", "id": "lab-enc-1-0000", "subject": {"reference": "Patient/pt1"}}
    s = _build_companion_specimen(r, country="JP")
    coding = s["type"]["coding"][0]
    assert coding["code"] == "119297000"
    assert coding["display"] == "血液検体"
    assert s["type"]["text"] == "血液検体"


def test_build_companion_specimen_urine_type():
    r = {
        "resourceType": "Observation",
        "id": "lab-enc-1-9999",
        "subject": {"reference": "Patient/pt1"},
        "code": {"text": "Urinalysis"},
    }
    s = _build_companion_specimen(r, country="US")
    assert s["type"]["coding"][0]["code"] == "122575003"


def test_build_companion_specimen_collection_datetime():
    r = {
        "resourceType": "Observation",
        "id": "lab-enc-1-0000",
        "subject": {"reference": "Patient/pt1"},
        "effectiveDateTime": "2026-03-15T12:31:00+09:00",
    }
    s = _build_companion_specimen(r, country="JP")
    assert s["collection"]["collectedDateTime"] == "2026-03-15T12:31:00+09:00"


def test_build_companion_specimen_no_datetime_no_collection():
    r = {"resourceType": "Observation", "id": "lab-enc-1-0000", "subject": {"reference": "Patient/pt1"}}
    s = _build_companion_specimen(r, country="US")
    assert "collection" not in s


def test_build_companion_specimen_status_available():
    r = {"resourceType": "Observation", "id": "lab-enc-1-0000", "subject": {"reference": "Patient/pt1"}}
    s = _build_companion_specimen(r, country="US")
    assert s["status"] == "available"


def test_build_companion_specimen_has_identifier():
    """Issue #854 Bucket B (PR-specimen): identifier[] carries both the
    pre-#854 clinosim namespace (``urn:clinosim:specimen-id``, value = the
    opaque id — pre-existing consumers keep working) AND the new
    ``SPECIMEN_KEY_SYSTEM`` structural-key round-trip."""
    from clinosim.modules.output.fhir_r4.post_process.specimen import (
        SPECIMEN_KEY_SYSTEM,
        _resolve_specimen_id,
    )

    r = {"resourceType": "Observation", "id": "lab-enc-1-0000", "subject": {"reference": "Patient/pt1"}}
    s = _build_companion_specimen(r, country="US")
    expected_id = _resolve_specimen_id("lab-enc-1-0000")
    assert s["identifier"] == [
        {"system": "urn:clinosim:specimen-id", "value": expected_id},
        {"system": SPECIMEN_KEY_SYSTEM, "value": "lab-enc-1-0000"},
    ]
