"""Unit tests for _fhir_endpoint builder (Tier 1 #2 PR1)."""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.output._fhir_endpoint import (
    DICOM_WADO_RS_CONNECTION_TYPE,
    ENDPOINT_ID_PREFIX,
    _bb_endpoints,
    _resolve_wado_base_url,
)
from clinosim.types.imaging import ImagingStudyRecord


def _make_ctx(studies, hospital_config=None):
    return SimpleNamespace(
        record={"extensions": {"imaging": studies}},
        country="us",
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={}, hospital_config=hospital_config or {},
        patient_data={}, is_readmission=False, prior_encounter_id=None,
        primary_dx_code="", admit_dx_code="",
    )


def _sample_study():
    return ImagingStudyRecord(
        study_id="enc1-1", study_instance_uid="2.25.42",
        encounter_id="enc1", patient_id="pt1", order_id="ord1",
        endpoint_id="endpoint-2.25.42",
    )


def test_empty_imaging_emits_zero_endpoints():
    assert _bb_endpoints(_make_ctx([])) == []


def test_emits_one_endpoint_per_study():
    ctx = _make_ctx([_sample_study()])
    r = _bb_endpoints(ctx)
    assert len(r) == 1
    e = r[0]
    assert e["resourceType"] == "Endpoint"
    assert e["id"] == "endpoint-2.25.42"
    assert e["id"].startswith(ENDPOINT_ID_PREFIX)
    assert e["status"] == "active"
    assert e["connectionType"]["code"] == DICOM_WADO_RS_CONNECTION_TYPE
    assert e["payloadMimeType"] == ["application/dicom"]


def test_address_uses_wado_base_url_from_hospital_config():
    ctx = _make_ctx([_sample_study()],
                    hospital_config={"imaging": {"wado_base_url": "https://pacs.test/dicomweb"}})
    e = _bb_endpoints(ctx)[0]
    assert e["address"] == "https://pacs.test/dicomweb/studies/2.25.42"


def test_address_falls_back_to_default_placeholder_when_unset():
    ctx = _make_ctx([_sample_study()], hospital_config={})
    e = _bb_endpoints(ctx)[0]
    assert e["address"].startswith("https://wado.clinosim.example")


def test_resolve_wado_base_url_returns_default_on_empty():
    assert _resolve_wado_base_url({}).startswith("https://wado.clinosim.example")


def test_resolve_wado_base_url_returns_configured():
    url = _resolve_wado_base_url({"imaging": {"wado_base_url": "https://my.pacs/wado"}})
    assert url == "https://my.pacs/wado"


def test_emits_endpoint_from_dict_path():
    """Production CIF is json.load() -> dict; verify _o() dict-access path."""
    study_dict = {
        "study_id": "enc1-1", "study_instance_uid": "2.25.42",
        "encounter_id": "enc1", "patient_id": "pt1", "order_id": "ord1",
        "endpoint_id": "endpoint-2.25.42",
    }
    ctx = _make_ctx([study_dict])
    resources = _bb_endpoints(ctx)
    assert len(resources) == 1
    e = resources[0]
    assert e["id"] == "endpoint-2.25.42"
    assert e["address"].endswith("/studies/2.25.42")
