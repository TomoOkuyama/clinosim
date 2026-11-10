"""The synth-ED bridge Encounter never carries an empty `hospitalization` (Issue #3179).

The bridge drops the canonical `dischargeDisposition` fallback (the ED->IMP
transition is expressed via `partOf`). When that was the only child,
`hospitalization` was left as `{}`, which FHIR forbids (every element needs a
value or children).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_encounters

pytestmark = pytest.mark.unit


def _ctx(country: str) -> BundleContext:
    enc = {
        "encounter_id": "ENC-IMP-1",
        "encounter_type": "inpatient",
        "status": "completed",
        "admission_datetime": "2026-01-15T10:00:00",
        "discharge_datetime": "2026-01-20T10:00:00",
        "admit_source": "emd",
        "admit_source_encounter_id": "ENC-IMP-1-ED",
        "attending_physician_id": "PRAC-000001",
        "chief_complaint": "Chest pain",
    }
    return BundleContext(
        record={"encounters": [enc], "orders": []},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"chronic_conditions": [], "sex": "M"},
        patient_id="POP-1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id="ENC-IMP-1",
        patient_sex="M",
    )


def _has_empty(value: object) -> bool:
    if isinstance(value, dict):
        return not value or any(_has_empty(v) for v in value.values())
    if isinstance(value, list):
        return not value or any(_has_empty(v) for v in value)
    return False


@pytest.mark.parametrize("country", ["US", "JP"])
def test_ed_bridge_has_no_empty_hospitalization(country: str) -> None:
    resources = _bb_encounters(_ctx(country))
    bridges = [r for r in resources if r["class"]["code"] == "EMER"]
    assert len(bridges) == 1
    bridge = bridges[0]
    assert "dischargeDisposition" not in bridge.get("hospitalization", {})
    if "hospitalization" in bridge:
        assert bridge["hospitalization"], "hospitalization must not be an empty object"
    assert not _has_empty(bridge), "the bridge Encounter carries an empty object/array"
