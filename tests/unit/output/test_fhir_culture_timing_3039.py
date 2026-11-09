"""A culture result is timed at the specimen collection; the report time is
``issued`` (Issue #3039)."""

from __future__ import annotations

import pytest

from clinosim.modules.observation.microbiology import specimen_transport_minutes
from clinosim.modules.output.fhir_r4.labs.microbiology import _bb_microbiology
from clinosim.modules.output.fhir_r4.lib.context import BundleContext

pytestmark = pytest.mark.unit

_COLLECTED = "2025-11-19T10:47:00"
_REPORTED = "2025-11-21T09:00:00"


def _resources(country: str = "US") -> list[dict]:
    culture = {
        "encounter_id": "E1",
        "specimen": "blood",
        "test_loinc": "600-7",
        "collected_datetime": _COLLECTED,
        "reported_datetime": _REPORTED,
        "growth": True,
        "organism_snomed": "3092008",
        "susceptibilities": [{"antibiotic_loinc": "19000-9", "interpretation": "S"}],
    }
    ctx = BundleContext(
        record={"orders": [], "microbiology": [culture]},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="P1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="E1",
        patient_sex="M",
    )
    return _bb_microbiology(ctx)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_culture_observations_are_effective_at_collection_and_issued_at_the_report(country: str) -> None:
    observations = [r for r in _resources(country) if r["resourceType"] == "Observation"]
    assert len(observations) == 2  # organism + susceptibility
    for obs in observations:
        assert obs["effectiveDateTime"].startswith(_COLLECTED)
        assert obs["issued"].startswith(_REPORTED)


def test_the_report_is_effective_at_collection_and_issued_at_the_report() -> None:
    (report,) = [r for r in _resources() if r["resourceType"] == "DiagnosticReport"]
    assert report["effectiveDateTime"].startswith(_COLLECTED)
    assert report["issued"].startswith(_REPORTED)


def test_the_specimen_is_received_a_transport_time_after_collection() -> None:
    (specimen,) = [r for r in _resources() if r["resourceType"] == "Specimen"]
    assert specimen["collection"]["collectedDateTime"].startswith(_COLLECTED)
    assert specimen_transport_minutes() == 45
    assert specimen["receivedTime"].startswith("2025-11-19T11:32:00")
