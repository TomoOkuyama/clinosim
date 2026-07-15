import pytest

from clinosim.modules.family_history.enricher import enrich_family_history

pytestmark = pytest.mark.integration


class _Ctx:
    def __init__(self, records):
        self.config = type("C", (), {"country": "US"})()
        self.master_seed = 42
        self.population = None
        self.records = records


def _rec(pid, age, conditions):
    return {"patient": {"patient_id": pid, "age": age, "chronic_conditions": conditions}}


def test_enricher_populates_family_history():
    rec = _rec("P1", 70, ["E11"])
    enrich_family_history(_Ctx([rec]))
    fh = rec["family_history"]
    assert fh and {f.relationship for f in fh} >= {"MTH", "FTH"}


def test_stable_across_encounters_same_person():
    r1, r2 = _rec("P1", 70, ["E11"]), _rec("P1", 70, ["E11"])
    enrich_family_history(_Ctx([r1, r2]))
    def key(fh):
        return [(f.relationship, f.sex, f.deceased, f.condition_codes) for f in fh]
    assert key(r1["family_history"]) == key(r2["family_history"])
