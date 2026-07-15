import pytest

from clinosim.modules.output.fhir_r4_adapter import BundleContext, _build_family_history
from clinosim.types.family_history import FamilyMemberHistoryRecord

pytestmark = pytest.mark.integration


def _ctx(country="US"):
    fams = [
        FamilyMemberHistoryRecord("MTH", "female", True, ["E11", "C50"]),
        FamilyMemberHistoryRecord("FTH", "male", False, ["I25"]),
    ]
    return BundleContext(
        record={"family_history": fams},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pat-1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id="enc-1",
        patient_sex="female",
    )


def test_builds_one_resource_per_relative():
    res = _build_family_history(_ctx())
    assert len(res) == 2
    r0 = res[0]
    assert r0["resourceType"] == "FamilyMemberHistory"
    assert r0["status"] == "completed"
    assert r0["patient"] == {"reference": "Patient/pat-1"}
    assert r0["relationship"]["coding"][0]["code"] == "MTH"
    assert r0["deceasedBoolean"] is True
    codes = [c["code"]["coding"][0]["code"] for c in r0["condition"]]
    # E11 (category header) folds to E11.9 (billable CM leaf) in US emission —
    # session 40 fix (FP-FH-CODE-RESOLUTION). Pre-fix output silently used the
    # child-fallback display ("with ketoacidosis without coma") which was
    # clinically wrong for a family-history-of-DM resource.
    assert "E11.9" in codes
    assert "C50" in codes


def test_unique_ids():
    res = _build_family_history(_ctx())
    ids = [r["id"] for r in res]
    assert len(ids) == len(set(ids))


def test_jp_localized_relationship():
    res = _build_family_history(_ctx("JP"))
    assert res[0]["relationship"]["coding"][0]["display"] == "母"
