"""Issue #2998: the synthesised ED Encounter of a via-ED admission carries the
chief complaint and takes place in the ED; the ED-to-inpatient transition is
its ``partOf`` link, not a discharge disposition."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.encounters.encounter import ENCOUNTER_KEY_SYSTEM
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_encounters

pytestmark = pytest.mark.unit

_IMP = "ENC-000001"


def _ctx(country: str) -> BundleContext:
    enc = {
        "encounter_id": _IMP,
        "encounter_type": "inpatient",
        "status": "completed",
        "department_id": "internal_medicine",
        "ward_id": "4W",
        "bed_number": "4W-06",
        "admission_datetime": "2026-01-15T10:00:00",
        "discharge_datetime": "2026-01-20T14:00:00",
        "admit_source": "emd",
        "admit_source_encounter_id": f"{_IMP}-ED",
        "attending_physician_id": "PRAC-000001",
        "chief_complaint": "Chest pain",
        "chief_complaint_ja": "胸痛",
    }
    return BundleContext(
        record={"encounters": [enc], "orders": []},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"chronic_conditions": []},
        patient_id="POP-000001",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id=_IMP,
        patient_sex="M",
    )


def _by_key(resources: list[dict], key: str) -> dict:
    for r in resources:
        if any(i.get("system") == ENCOUNTER_KEY_SYSTEM and i.get("value") == key for i in r.get("identifier", [])):
            return r
    raise AssertionError(key)


@pytest.mark.parametrize(("country", "text"), [("US", "Chest pain"), ("JP", "胸痛")])
def test_synth_ed_encounter_carries_the_chief_complaint(country: str, text: str) -> None:
    ed = _by_key(_bb_encounters(_ctx(country)), f"{_IMP}-ED")
    assert ed["class"]["code"] == "EMER"
    assert ed["reasonCode"][0]["text"] == text


@pytest.mark.parametrize("country", ["US", "JP"])
def test_synth_ed_encounter_is_at_the_ed(country: str) -> None:
    ed = _by_key(_bb_encounters(_ctx(country)), f"{_IMP}-ED")
    assert [loc["location"]["reference"] for loc in ed["location"]] == ["Location/loc-ward-ER"]
    assert ed["serviceProvider"]["reference"] == "Organization/dept-emergency-medicine"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_admission_links_to_the_synth_ed_encounter_without_a_disposition(country: str) -> None:
    resources = _bb_encounters(_ctx(country))
    ed = _by_key(resources, f"{_IMP}-ED")
    imp = _by_key(resources, _IMP)
    assert imp["partOf"]["reference"] == f"Encounter/{ed['id']}"
    assert imp["hospitalization"]["admitSource"]["coding"][0]["code"] == "emd"
    # HL7 discharge-disposition has no "admitted" concept ("hosp" is hospice).
    assert "dischargeDisposition" not in (ed.get("hospitalization") or {})
    # The admission keeps its own ward and bed.
    assert imp["location"][0]["location"]["reference"] == "Location/loc-bed-4W-06"
