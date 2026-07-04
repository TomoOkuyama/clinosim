"""Unit tests for _fhir_imaging_study builder (Tier 1 #2 PR1)."""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.output._fhir_imaging_study import (
    DICOM_UID_SYSTEM,
    ENDPOINT_ID_PREFIX,
    IMAGING_STUDY_ID_PREFIX,
    _bb_imaging_studies,
)
from clinosim.types.imaging import ImagingSeries, ImagingStudyRecord, RadiologyReport


def _make_ctx(studies, country="us", hospital_config=None):
    return SimpleNamespace(
        record={"extensions": {"imaging": studies}},
        country=country,
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={},
        hospital_config=hospital_config or {},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
    )


def _sample_study():
    from datetime import datetime
    return ImagingStudyRecord(
        study_id="enc1-1",
        study_instance_uid="2.25.42",
        encounter_id="enc1", patient_id="pt1", order_id="ord1",
        status="available",
        started_datetime=datetime(2026, 6, 30, 10, 0),
        modality_code="CR", body_site_snomed="51185008",
        series=[
            ImagingSeries(series_uid="2.25.43", series_number=1, modality_code="CR",
                          body_site_snomed="51185008",
                          description="PA view", instance_count=1),
            ImagingSeries(series_uid="2.25.44", series_number=2, modality_code="CR",
                          body_site_snomed="51185008",
                          description="Lateral view", instance_count=1),
        ],
        endpoint_id="endpoint-2.25.42",
        report=RadiologyReport(report_id="enc1-1", status="final",
                               findings_text="Lungs clear.",
                               impression_text="No acute findings."),
    )


def test_empty_imaging_extension_emits_zero():
    ctx = _make_ctx([])
    assert _bb_imaging_studies(ctx) == []


def test_emits_one_imaging_study():
    ctx = _make_ctx([_sample_study()])
    resources = _bb_imaging_studies(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "ImagingStudy"
    assert r["id"].startswith(IMAGING_STUDY_ID_PREFIX)
    assert r["identifier"][0]["system"] == DICOM_UID_SYSTEM
    assert r["identifier"][0]["value"] == "urn:oid:2.25.42"
    assert r["status"] == "available"


def test_basedon_and_endpoint_refs():
    ctx = _make_ctx([_sample_study()])
    r = _bb_imaging_studies(ctx)[0]
    assert r["basedOn"] == [{"reference": "ServiceRequest/sr-ord1"}]
    assert r["endpoint"] == [{"reference": "Endpoint/endpoint-2.25.42"}]
    assert r["endpoint"][0]["reference"].removeprefix("Endpoint/").startswith(
        ENDPOINT_ID_PREFIX
    )


def test_number_of_series_and_instances():
    ctx = _make_ctx([_sample_study()])
    r = _bb_imaging_studies(ctx)[0]
    assert r["numberOfSeries"] == 2
    assert r["numberOfInstances"] == 2   # 1 + 1


def test_series_emit_full_payload():
    ctx = _make_ctx([_sample_study()])
    r = _bb_imaging_studies(ctx)[0]
    series = r["series"]
    assert len(series) == 2
    assert series[0]["uid"] == "2.25.43"
    assert series[0]["number"] == 1
    assert series[0]["modality"]["code"] == "CR"
    assert series[0]["bodySite"]["code"] == "51185008"
    assert series[0]["description"] == "PA view"
    assert series[0]["numberOfInstances"] == 1


def test_jp_locale_resolves_modality_and_body_site_ja():
    ctx = _make_ctx([_sample_study()], country="jp")
    r = _bb_imaging_studies(ctx)[0]
    # CR display_ja = "単純X線撮影", chest SNOMED display_ja = "胸部"
    assert "単純X線撮影" in r["modality"][0]["display"]
    # bodySite display via series — chest SNOMED resolved
    assert "胸部" in r["series"][0]["bodySite"]["display"]


def test_emits_imaging_study_from_dict_path():
    """Production CIF is json.load() -> dict; verify _o() dict-access path."""
    study_dict = {
        "study_id": "enc1-1", "study_instance_uid": "2.25.42",
        "encounter_id": "enc1", "patient_id": "pt1", "order_id": "ord1",
        "status": "available", "started_datetime": "2026-06-30T10:00:00",
        "modality_code": "CR", "body_site_snomed": "51185008",
        "series": [{
            "series_uid": "2.25.43", "series_number": 1,
            "modality_code": "CR", "body_site_snomed": "51185008",
            "description": "PA view", "instance_count": 1,
        }],
        "endpoint_id": "endpoint-2.25.42",
    }
    ctx = _make_ctx([study_dict])
    resources = _bb_imaging_studies(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["id"] == "imgst-enc1-1"
    assert r["identifier"][0]["value"] == "urn:oid:2.25.42"
    assert r["series"][0]["uid"] == "2.25.43"
    assert r["series"][0]["description"] == "PA view"
    assert r["basedOn"] == [{"reference": "ServiceRequest/sr-ord1"}]
    assert r["endpoint"] == [{"reference": "Endpoint/endpoint-2.25.42"}]
