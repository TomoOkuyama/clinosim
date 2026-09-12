"""Unit tests for clinosim.modules.drug_safety.demographic.check_demographic_gate.

Covers the three rules seeded in ``demographic_gates.yaml``:
    - aspirin-pediatric-reyes    (Issue #1328)
    - nitroglycerin-adult-only   (Issue #1328)
    - tamsulosin-adult-male-bph  (Issue #1316)
"""

from __future__ import annotations

import pytest

from clinosim.modules.drug_safety import check_demographic_gate
from clinosim.modules.drug_safety.demographic import DemographicVerdict


class TestAspirinPediatric:
    """Aspirin < age 16 is contraindicated (Reye's syndrome)."""

    def test_pediatric_aspirin_blocked(self) -> None:
        v = check_demographic_gate("Aspirin 325mg", patient_age=8, patient_sex="F", indication_codes=["R07.3"])
        assert v.severity == "contraindicated"
        assert v.rule_id == "aspirin-pediatric-reyes"
        assert v.should_skip is True

    def test_adult_aspirin_allowed(self) -> None:
        v = check_demographic_gate("Aspirin 325mg", patient_age=55, patient_sex="M", indication_codes=["R07.3"])
        assert v.is_allowed is True

    def test_boundary_age_16_allowed(self) -> None:
        v = check_demographic_gate("Aspirin", patient_age=16, patient_sex="F", indication_codes=["R07.3"])
        assert v.is_allowed is True

    def test_kawasaki_pediatric_bypass(self) -> None:
        # M30.3 (Kawasaki) is the classical pediatric aspirin indication.
        v = check_demographic_gate("Aspirin", patient_age=4, patient_sex="M", indication_codes=["M30.3"])
        assert v.is_allowed is True

    def test_rheumatic_fever_pediatric_bypass(self) -> None:
        v = check_demographic_gate("Aspirin", patient_age=8, patient_sex="M", indication_codes=["I01.9"])
        assert v.is_allowed is True

    def test_japanese_alias_matched(self) -> None:
        v = check_demographic_gate("アスピリン", patient_age=8, patient_sex="F", indication_codes=None)
        assert v.rule_id == "aspirin-pediatric-reyes"


class TestNitroglycerinPediatric:
    """NTG has no routine pediatric indication."""

    def test_pediatric_ntg_blocked(self) -> None:
        v = check_demographic_gate(
            "Nitroglycerin 0.4mg SL",
            patient_age=8,
            patient_sex="M",
            indication_codes=["R07.3"],
        )
        assert v.severity == "contraindicated"
        assert v.rule_id == "nitroglycerin-adult-only"

    def test_adult_ntg_allowed(self) -> None:
        v = check_demographic_gate("Nitroglycerin", patient_age=62, patient_sex="M", indication_codes=None)
        assert v.is_allowed is True

    def test_boundary_age_18_allowed(self) -> None:
        v = check_demographic_gate("Nitroglycerin", patient_age=18, patient_sex="F", indication_codes=None)
        assert v.is_allowed is True


class TestTamsulosinMalePediatric:
    """Tamsulosin is BPH-only — adult male."""

    def test_female_blocked(self) -> None:
        v = check_demographic_gate("Tamsulosin 0.4mg", patient_age=72, patient_sex="F", indication_codes=["R33.9"])
        assert v.severity == "contraindicated"
        assert v.rule_id == "tamsulosin-adult-male-bph"

    def test_pediatric_male_blocked(self) -> None:
        v = check_demographic_gate("Tamsulosin", patient_age=6, patient_sex="M", indication_codes=["R33.9"])
        assert v.severity == "contraindicated"

    def test_adult_male_allowed(self) -> None:
        v = check_demographic_gate("Tamsulosin", patient_age=72, patient_sex="M", indication_codes=["R33.9"])
        assert v.is_allowed is True

    def test_boundary_age_50_male_allowed(self) -> None:
        v = check_demographic_gate("Tamsulosin", patient_age=50, patient_sex="male", indication_codes=None)
        assert v.is_allowed is True

    def test_japanese_alias_matched(self) -> None:
        v = check_demographic_gate("ハルナールD 0.2mg", patient_age=6, patient_sex="M", indication_codes=None)
        assert v.rule_id == "tamsulosin-adult-male-bph"


class TestNonMatchingDrugs:
    """Drugs not in the catalog are always allowed by this gate."""

    def test_unrelated_drug_allowed(self) -> None:
        v = check_demographic_gate("Amoxicillin 500mg", patient_age=8, patient_sex="F", indication_codes=["J13"])
        assert v.is_allowed is True


class TestMissingDemographics:
    """Absent age/sex arguments bypass the corresponding gate."""

    def test_age_none_skips_age_gate(self) -> None:
        # No age → aspirin age gate cannot fire even for what would be pediatric.
        v = check_demographic_gate("Aspirin", patient_age=None, patient_sex="F", indication_codes=None)
        assert v.is_allowed is True

    def test_sex_none_skips_sex_gate_but_age_gate_still_fires(self) -> None:
        # Tamsulosin has both age (>=50) and sex (male) rules; without sex,
        # only the age gate matters — a 6yo without sex data still fails.
        v = check_demographic_gate("Tamsulosin", patient_age=6, patient_sex=None, indication_codes=None)
        assert v.severity == "contraindicated"


class TestVerdictShape:
    """DemographicVerdict shape + is_allowed / should_skip semantics."""

    def test_allowed_verdict(self) -> None:
        v = check_demographic_gate("Amoxicillin", patient_age=30, patient_sex="M", indication_codes=None)
        assert isinstance(v, DemographicVerdict)
        assert v.is_allowed is True
        assert v.should_skip is False
        assert v.rule_id is None

    def test_contraindicated_verdict_should_skip(self) -> None:
        v = check_demographic_gate("Aspirin", patient_age=6, patient_sex="F", indication_codes=None)
        assert v.should_skip is True

    def test_frozen(self) -> None:
        v = check_demographic_gate("Aspirin", patient_age=6, patient_sex="F", indication_codes=None)
        with pytest.raises(Exception):
            v.severity = "allowed"  # type: ignore[misc]


class TestYamlLoads:
    def test_all_rules_have_valid_severity(self) -> None:
        from clinosim.modules.drug_safety.demographic import _load_rules
        from clinosim.modules.drug_safety.verdict import SEVERITY_RANK

        rules = _load_rules()
        assert rules, "demographic_gates.yaml must ship with seed rules"
        for r in rules:
            assert r["severity"] in SEVERITY_RANK

    def test_all_seed_rule_ids_present(self) -> None:
        from clinosim.modules.drug_safety.demographic import _load_rules

        ids = {r["id"] for r in _load_rules()}
        assert {"aspirin-pediatric-reyes", "nitroglycerin-adult-only", "tamsulosin-adult-male-bph"} <= ids
