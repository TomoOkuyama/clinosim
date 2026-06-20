"""Integration tests for _build_immunizations FHIR builder (Task 6).

Verifies that CIF immunization records produce valid FHIR Immunization resources,
that US output contains no Japanese characters, and that CVX-coded resources
satisfy the display != code invariant.
"""

from __future__ import annotations

import json
import re

import pytest

pytestmark = pytest.mark.integration

_JAPANESE_RE = re.compile(r"[぀-ヿ一-鿿]")


def _record(
    vaccine_cvx: str = "150",
    occurrence_date: str = "2025-10-01",
    status: str = "completed",
    primary_source: bool = True,
) -> dict:
    """Return a minimal CIF record dict containing one immunization."""
    return {
        "patient_id": "p1",
        "immunizations": [
            {
                "vaccine_cvx": vaccine_cvx,
                "occurrence_date": occurrence_date,
                "status": status,
                "primary_source": primary_source,
                "dose_number": None,
            }
        ],
    }


def _record_multi() -> dict:
    """Return a CIF record dict with multiple immunizations."""
    return {
        "patient_id": "p1",
        "immunizations": [
            {
                "vaccine_cvx": "150",
                "occurrence_date": "2025-10-01",
                "status": "completed",
                "primary_source": True,
                "dose_number": None,
            },
            {
                "vaccine_cvx": "115",
                "occurrence_date": "2024-05-15",
                "status": "completed",
                "primary_source": True,
                "dose_number": None,
            },
            {
                "vaccine_cvx": "309",
                "occurrence_date": "2023-09-20",
                "status": "completed",
                "primary_source": False,
                "dose_number": None,
            },
        ],
    }


def _make_ctx(record: dict, country: str, patient_id: str = "p1", primary_enc_id: str = "enc1"):
    """Construct a minimal BundleContext for testing, mirroring test_fhir_nursing.py."""
    from clinosim.modules.output.fhir_r4_adapter import BundleContext

    return BundleContext(
        record=record,
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": patient_id},
        patient_id=patient_id,
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id=primary_enc_id,
        patient_sex="",
    )


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------


def test_resource_types_are_immunization():
    """Every resource must have resourceType == Immunization."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    ctx = _make_ctx(_record_multi(), country="US")
    resources = _build_immunizations(ctx)

    assert resources, "no Immunization resources built"
    assert all(r["resourceType"] == "Immunization" for r in resources)


def test_status_is_completed():
    """status field must equal 'completed' for standard records."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    ctx = _make_ctx(_record(), country="US")
    resources = _build_immunizations(ctx)

    assert resources
    assert all(r["status"] == "completed" for r in resources)


def test_ids_unique():
    """All Immunization ids within the output must be unique."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    ctx = _make_ctx(_record_multi(), country="US", patient_id="p1")
    resources = _build_immunizations(ctx)

    ids = [r["id"] for r in resources]
    assert len(ids) == len(set(ids)), f"Duplicate Immunization ids: {ids}"


def test_patient_reference():
    """patient.reference must point to the Patient resource."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    patient_id = "pat-xyz"
    ctx = _make_ctx(_record(), country="US", patient_id=patient_id)
    resources = _build_immunizations(ctx)

    assert resources
    for r in resources:
        ref = r.get("patient", {}).get("reference", "")
        assert ref == f"Patient/{patient_id}", f"Bad patient ref: {ref!r}"


def test_occurrence_date_present():
    """occurrenceDateTime must be set and match the CIF occurrence_date."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    ctx = _make_ctx(_record(occurrence_date="2025-10-01"), country="US")
    resources = _build_immunizations(ctx)

    assert resources
    assert resources[0]["occurrenceDateTime"] == "2025-10-01"


def test_primary_source_preserved():
    """primarySource must reflect the CIF record value."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    ctx_true = _make_ctx(_record(primary_source=True), country="US")
    ctx_false = _make_ctx(_record(primary_source=False), country="US")

    assert _build_immunizations(ctx_true)[0]["primarySource"] is True
    assert _build_immunizations(ctx_false)[0]["primarySource"] is False


# ---------------------------------------------------------------------------
# CVX coding
# ---------------------------------------------------------------------------


def test_vaccine_code_has_cvx_system():
    """vaccineCode.coding[0].system must be the canonical CVX URI."""
    from clinosim.codes import get_system_uri
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    cvx_uri = get_system_uri("cvx")
    ctx = _make_ctx(_record(vaccine_cvx="150"), country="US")
    resources = _build_immunizations(ctx)

    assert resources
    coding = resources[0]["vaccineCode"]["coding"][0]
    assert coding["system"] == cvx_uri, f"Expected CVX URI {cvx_uri!r}, got {coding['system']!r}"


def test_vaccine_code_value():
    """vaccineCode.coding[0].code must equal the CVX code from CIF."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    ctx = _make_ctx(_record(vaccine_cvx="115"), country="US")
    resources = _build_immunizations(ctx)

    assert resources
    coding = resources[0]["vaccineCode"]["coding"][0]
    assert coding["code"] == "115"


def test_display_not_equal_to_code():
    """vaccineCode.coding[0].display must not equal the raw CVX code."""
    from clinosim.codes import get_system_uri
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    cvx_uri = get_system_uri("cvx")
    for country in ("US", "JP"):
        ctx = _make_ctx(_record_multi(), country=country)
        resources = _build_immunizations(ctx)
        for r in resources:
            for coding in r["vaccineCode"].get("coding", []):
                if coding.get("system") == cvx_uri and "display" in coding:
                    assert coding["display"] != coding["code"], (
                        f"display == code ({coding['code']!r}) for country={country}"
                    )


# ---------------------------------------------------------------------------
# Localisation / character set
# ---------------------------------------------------------------------------


def test_us_output_no_japanese():
    """US output must contain no Japanese characters in any field."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    ctx = _make_ctx(_record_multi(), country="US")
    resources = _build_immunizations(ctx)

    assert resources, "no Immunization resources built"
    assert not _JAPANESE_RE.search(json.dumps(resources)), (
        "Japanese characters found in US Immunization output"
    )


def test_jp_output_may_have_japanese():
    """JP output should include Japanese display text from CVX lookup."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    ctx = _make_ctx(_record_multi(), country="JP")
    resources = _build_immunizations(ctx)

    dumped = json.dumps(resources, ensure_ascii=False)
    assert _JAPANESE_RE.search(dumped), (
        "Expected Japanese characters in JP Immunization output"
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_immunizations_returns_empty():
    """No immunizations in record → empty list returned."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    ctx = _make_ctx({"patient_id": "p1", "immunizations": []}, country="US")
    assert _build_immunizations(ctx) == []


def test_missing_immunizations_key_returns_empty():
    """Missing immunizations key in record → empty list returned."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    ctx = _make_ctx({"patient_id": "p1"}, country="US")
    assert _build_immunizations(ctx) == []


def test_multiple_immunizations_count():
    """Three immunization records should produce three FHIR Immunization resources."""
    from clinosim.modules.output.fhir_r4_adapter import _build_immunizations

    ctx = _make_ctx(_record_multi(), country="US")
    resources = _build_immunizations(ctx)

    assert len(resources) == 3
