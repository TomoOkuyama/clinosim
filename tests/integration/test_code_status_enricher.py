import pytest

from clinosim.modules.code_status.enricher import enrich_code_status

pytestmark = pytest.mark.integration


class _Ctx:
    def __init__(self, records, country="US"):
        self.config = type("C", (), {"country": country})()
        self.master_seed = 42
        self.population = None
        self.records = records


def _rec(eid, etype, age, deceased=False, icu=False):
    return {
        "patient": {"patient_id": "P", "age": age},
        "encounters": [{"encounter_id": eid, "encounter_type": etype}],
        "deceased": deceased,
        "icu_transferred": icu,
    }


def test_inpatient_always_assigned():
    r = _rec("E1", "inpatient", 70)
    enrich_code_status(_Ctx([r]))
    assert r["code_status"]


def test_outpatient_never_assigned():
    r = _rec("E2", "outpatient", 70)
    enrich_code_status(_Ctx([r]))
    assert r["code_status"] == ""


def test_ed_routine_not_assigned():
    r = _rec("E3", "emergency", 70)
    enrich_code_status(_Ctx([r]))
    assert r["code_status"] == ""


def test_ed_terminal_assigned():
    r = _rec("E4", "emergency", 70, deceased=True)
    enrich_code_status(_Ctx([r]))
    assert r["code_status"]


def test_stable_for_encounter():
    r1, r2 = _rec("E5", "inpatient", 80), _rec("E5", "inpatient", 80)
    enrich_code_status(_Ctx([r1, r2]))
    assert r1["code_status"] == r2["code_status"]
