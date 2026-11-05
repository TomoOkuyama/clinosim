"""Issue #2649: a resuscitation status names who set it and is a resuscitation value."""

from __future__ import annotations

import pytest

from clinosim.modules.code_status.engine import load_reference
from clinosim.modules.output.fhir_r4.conditions.code_status import _bb_code_status
from clinosim.modules.output.fhir_r4.lib.context import BundleContext

pytestmark = pytest.mark.unit


def _ctx(code: str) -> BundleContext:
    return BundleContext(
        record={
            "code_status": code,
            "encounters": [
                {
                    "encounter_id": "E1",
                    "admission_datetime": "2025-03-01T09:00:00",
                    "attending_physician_id": "DR-IM-003",
                }
            ],
        },
        country="US",
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
        patient_sex="",
    )


def test_every_tier_is_a_resuscitation_status_value() -> None:
    assert {t["snomed"] for t in load_reference()["tiers"]} <= {"304252001", "304253006"}


def test_the_attending_set_the_status() -> None:
    [obs] = _bb_code_status(_ctx("304253006"))
    assert obs["performer"] == [{"reference": "Practitioner/DR-IM-003"}]
