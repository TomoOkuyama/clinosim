from pathlib import Path

import pytest
import yaml

from clinosim.types.family_history import FamilyMemberHistoryRecord

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[2] / "clinosim"


def test_record_construction():
    r = FamilyMemberHistoryRecord(relationship="MTH", sex="female", deceased=False, condition_codes=["E11"])
    assert r.relationship == "MTH" and r.condition_codes == ["E11"]


def test_reference_data_shape():
    d = yaml.safe_load(open(_ROOT / "modules/family_history/reference_data/family_history.yaml"))
    assert set(d["conditions"]) == {"E11", "I10", "I25", "I63", "I64", "E78", "C50", "C18", "C34", "C61"}
    assert d["relationships"]["MTH"]["en"] == "Mother"
    assert d["conditions"]["C61"]["sex"] == "male"  # prostate
    assert d["conditions"]["C50"]["sex"] == "female"  # breast


@pytest.mark.parametrize("country", ["us", "jp"])
def test_prevalence_data_shape(country):
    d = yaml.safe_load(open(_ROOT / f"locale/{country}/family_history_prevalence.yaml"))
    for code in ["E11", "I10", "C50"]:
        bands = d["prevalence"][code]
        assert "40-59" in bands and "female" in bands["40-59"]
