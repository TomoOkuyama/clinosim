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


def _baby(pid, maternal_codes, with_birth=True):
    rec = _rec(pid, 0, [])
    if with_birth:
        rec["extensions"] = {"newborn": {"birth": {"maternal_condition_codes": maternal_codes}}}
    return rec


def _mother_codes(rec):
    return next(f.condition_codes for f in rec["family_history"] if f.relationship == "MTH")


def test_newborn_mother_carries_the_maternal_chronic_conditions():
    # Issue #3689: the baby's own (empty) condition list does not decide the mother's history.
    rec = _baby("P1-BABY", ["I10", "E66.3"])
    enrich_family_history(_Ctx([rec]))
    assert {"I10", "E66"} <= set(_mother_codes(rec))


def test_newborn_maternal_conditions_reach_every_record_of_the_baby():
    birth, later = _baby("P1-BABY", ["I10"]), _baby("P1-BABY", [], with_birth=False)
    enrich_family_history(_Ctx([birth, later]))
    assert "I10" in _mother_codes(birth) and "I10" in _mother_codes(later)


def test_newborn_maternal_conditions_change_nothing_else():
    plain, with_mother = _baby("P1-BABY", [], with_birth=False), _baby("P1-BABY", ["I10"])
    enrich_family_history(_Ctx([plain, with_mother]))

    def other(r):
        return [
            (f.relationship, f.sex, f.deceased, f.condition_codes)
            for f in r["family_history"]
            if f.relationship != "MTH"
        ]

    assert other(plain) == other(with_mother)


def test_newborn_of_a_mother_without_conditions_is_sampled_as_before():
    rec, plain = _baby("P2-BABY", []), _baby("P2-BABY", [], with_birth=False)
    enrich_family_history(_Ctx([rec, plain]))
    assert _mother_codes(rec) == _mother_codes(plain)


def test_adult_family_history_is_unchanged():
    adult = _rec("P3", 40, ["I10"])
    enrich_family_history(_Ctx([adult]))
    reference = _rec("P3", 40, ["I10"])
    enrich_family_history(_Ctx([reference]))
    assert _mother_codes(adult) == _mother_codes(reference)
