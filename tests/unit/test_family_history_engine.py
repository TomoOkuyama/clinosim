import numpy as np
import pytest

from clinosim.modules.family_history.engine import generate_family_history

pytestmark = pytest.mark.unit


def _gen(conditions, seed=1, age=70, country="US"):
    return generate_family_history(age, conditions, country, np.random.default_rng(seed))


def test_always_has_mother_and_father():
    rels = {f.relationship for f in _gen([])}
    assert "MTH" in rels and "FTH" in rels


def test_deterministic():
    a = _gen(["E11"], seed=5)
    b = _gen(["E11"], seed=5)
    key = lambda fams: [(f.relationship, f.sex, f.deceased, f.condition_codes) for f in fams]
    assert key(a) == key(b)


def test_sex_restriction_prostate_male_only():
    for s in range(200):
        for f in _gen(["C61"], seed=s):
            if f.sex == "female":
                assert "C61" not in f.condition_codes


def test_sex_restriction_breast_female_only():
    for s in range(200):
        for f in _gen(["C50"], seed=s):
            if f.sex == "male":
                assert "C50" not in f.condition_codes


def test_heritability_boost_raises_parental_rate():
    def parental_e11_rate(conditions):
        hits = tot = 0
        for s in range(400):
            for f in _gen(conditions, seed=s):
                if f.relationship in ("MTH", "FTH"):
                    tot += 1
                    hits += ("E11" in f.condition_codes)
        return hits / tot
    assert parental_e11_rate(["E11"]) > parental_e11_rate([]) * 1.3


def test_jp_us_differ():
    def prostate_rate(country):
        hits = tot = 0
        for s in range(400):
            for f in generate_family_history(75, [], country, np.random.default_rng(s)):
                if f.sex == "male" and f.relationship == "FTH":
                    tot += 1
                    hits += ("C61" in f.condition_codes)
        return hits / max(tot, 1)
    assert prostate_rate("JP") < prostate_rate("US")
