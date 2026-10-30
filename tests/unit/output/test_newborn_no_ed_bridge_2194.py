"""A newborn's link to the mother's delivery encounter is not an ED bridge (Issue #2194)."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.common import BundleContext
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_encounters

pytestmark = pytest.mark.unit

_MOTHER_ENC = "ENC-MOTHER-1"


def _ctx(admit_source: str, link: str) -> BundleContext:
    enc = {
        "encounter_id": "ENC-BABY-1",
        "encounter_type": "inpatient",
        "status": "completed",
        "admission_datetime": "2026-01-15T10:00:00",
        "discharge_datetime": "2026-01-17T10:00:00",
        "admit_source": admit_source,
        "admit_source_encounter_id": link,
        "attending_physician_id": "PRAC-000001",
        "chief_complaint": "Newborn",
    }
    return BundleContext(
        record={"encounters": [enc], "orders": []},
        country="US",
        roster_map={},
        hospital_config={},
        patient_data={"chronic_conditions": []},
        patient_id="POP-1-BABY",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id="ENC-BABY-1",
        patient_sex="F",
    )


def _classes(resources: list[dict]) -> list[str]:
    return [r["class"]["code"] for r in resources]


def test_newborn_birth_encounter_emits_no_ed_bridge() -> None:
    resources = _bb_encounters(_ctx("born", _MOTHER_ENC))
    assert _classes(resources) == ["IMP"]
    assert resources[0].get("partOf"), "the newborn encounter still links to the mother's delivery encounter"


def test_ed_admission_still_emits_its_bridge() -> None:
    resources = _bb_encounters(_ctx("emd", "ENC-BABY-1-ED"))
    assert sorted(_classes(resources)) == ["EMER", "IMP"]
