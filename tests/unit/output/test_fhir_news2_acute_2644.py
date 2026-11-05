"""Issue #2644: NEWS2 is recorded in acute care and coded in SNOMED CT."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

pytestmark = pytest.mark.unit


def _news2(encounter_type: str, country: str = "US") -> list[dict]:
    ctx = SimpleNamespace(
        record={
            "encounters": [{"encounter_id": "ENC-001", "encounter_type": encounter_type}],
            "vital_signs": [{"timestamp": "2026-05-12T10:00:00", "news2_score": 3}],
        },
        country=country,
        patient_id="POP-000001",
        primary_enc_id="ENC-001",
    )
    return [o for o in _bb_nursing_observations(ctx) if o["id"].startswith("news2-")]


@pytest.mark.parametrize("encounter_type", ["inpatient", "emergency"])
@pytest.mark.parametrize("country", ["US", "JP"])
def test_acute_care_records_news2_with_its_snomed_concept(encounter_type: str, country: str) -> None:
    [obs] = _news2(encounter_type, country)
    assert {"system": "http://snomed.info/sct", "code": "1287358002"} in [
        {k: c[k] for k in ("system", "code")} for c in obs["code"]["coding"]
    ]


def test_an_outpatient_visit_records_no_news2() -> None:
    assert _news2("outpatient") == []
