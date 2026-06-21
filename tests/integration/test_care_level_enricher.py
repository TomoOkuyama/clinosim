import pytest

from clinosim.modules.care_level.enricher import enrich_care_level

pytestmark = pytest.mark.integration


class _Ctx:
    def __init__(self, records, country="JP"):
        self.config = type("C", (), {"country": country})()
        self.master_seed = 42
        self.population = None
        self.records = records


def _rec(pid, age):
    return {"patient": {"patient_id": pid, "age": age}}


def test_jp_sets_field_present():
    r = _rec("P1", 88)
    enrich_care_level(_Ctx([r]))
    assert "care_level" in r


def test_stable_per_person():
    r1, r2 = _rec("P1", 88), _rec("P1", 88)
    enrich_care_level(_Ctx([r1, r2]))
    assert r1["care_level"] == r2["care_level"]


def test_us_empty():
    r = _rec("P1", 88)
    enrich_care_level(_Ctx([r], country="US"))
    assert r["care_level"] == ""
