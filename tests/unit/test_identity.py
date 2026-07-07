"""Unit tests for the resident identifier & insurance numbering module (AD-54)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.locale.loader import load_identity_config
from clinosim.modules.identity import assign_identities, get_provider
from clinosim.modules.identity import generators as gen
from clinosim.modules.population.engine import Household, PersonRecord, PopulationRegistry


@pytest.fixture
def rng():
    return np.random.default_rng(42)


def _person(pid: str, hh: str, age: int, sex: str = "M", occupation: str = "other") -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id=hh,
        age=age,
        sex=sex,
        date_of_birth=date(2026 - age, 1, 1),
        occupation=occupation,
    )


@pytest.mark.unit
class TestGenerators:
    def test_my_number_length_and_digits(self, rng):
        n = gen.my_number(rng)
        assert len(n) == 12
        assert n.isdigit()

    def test_my_number_check_digit_recomputes(self, rng):
        n = gen.my_number(rng)
        base = [int(c) for c in n[:11]]
        assert gen.my_number_check_digit(base) == int(n[11])

    def test_my_number_check_digit_known_vectors(self):
        # All zeros → remainder 0 → check digit 0.
        assert gen.my_number_check_digit([0] * 11) == 0
        # Leftmost digit 1: P_11=1, Q_11=6 → total 6 → 11-6 = 5.
        assert gen.my_number_check_digit([1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]) == 5

    def test_mod10_check_digit_is_single_digit(self):
        for body in ["0113000", "1310", "39130008"]:
            cd = gen.mod10_check_digit(body)
            assert 0 <= cd <= 9

    def test_insurer_number_widths(self):
        # Employee: 法別(2)+都道府県(2)+保険者別(3)+検証(1) = 8
        assert len(gen.insurer_number("01", "13", "001", national=False)) == 8
        # National: 都道府県(2)+保険者別(3)+検証(1) = 6
        assert len(gen.insurer_number("", "13", "016", national=True)) == 6

    def test_branch_number_format(self):
        assert gen.branch_number(1) == "01"
        assert gen.branch_number(12) == "12"


@pytest.mark.unit
class TestJPHouseholdAssignment:
    def test_non_elderly_share_record_elderly_individual(self, rng):
        config = load_identity_config("JP")
        provider = get_provider("JP")
        members = [
            _person("P1", "HH1", 45),
            _person("P2", "HH1", 42, "F"),
            _person("P3", "HH1", 10),
            _person("P4", "HH1", 78, "F"),
        ]
        enr = provider.assign_household(members, rng, config)

        non_elderly = [enr["P1"], enr["P2"], enr["P3"]]
        # Shared insurer / 記号 / 被保険者番号 within the household record.
        assert len({e.insurer_number for e in non_elderly}) == 1
        assert len({e.group_symbol for e in non_elderly}) == 1
        assert len({e.member_id for e in non_elderly}) == 1
        # Distinct 枝番 per individual.
        assert len({e.branch_number for e in non_elderly}) == 3

        # 75+ is per-individual: own insurer, own member id, no 記号.
        elderly = enr["P4"]
        assert elderly.category == "late_elderly"
        assert elderly.group_symbol is None
        assert elderly.insurer_number != non_elderly[0].insurer_number

    def test_late_elderly_insurer_is_eight_digits(self, rng):
        config = load_identity_config("JP")
        provider = get_provider("JP")
        enr = provider.assign_household([_person("E1", "HH9", 80)], rng, config)
        assert len(enr["E1"].insurer_number) == 8

    def test_unsupported_country_raises(self):
        with pytest.raises(ValueError):
            get_provider("XX")

    @pytest.mark.parametrize("country", ["JP", "jp"])
    def test_get_provider_jp_case_insensitive(self, country):
        from clinosim.modules.identity.providers import JPIdentityProvider

        assert isinstance(get_provider(country), JPIdentityProvider)

    @pytest.mark.parametrize("country", ["US", "us"])
    def test_get_provider_us_case_insensitive(self, country):
        from clinosim.modules.identity.providers import USIdentityProvider

        assert isinstance(get_provider(country), USIdentityProvider)


@pytest.mark.unit
class TestSchemeByOccupation:
    def test_unemployed_household_is_national(self):
        """A household with only non-employed working-age members → 国保."""
        config = load_identity_config("JP")
        provider = get_provider("JP")
        rng = np.random.default_rng(1)
        for _ in range(50):
            members = [_person("P1", "H", 50, occupation="unemployed"),
                       _person("P2", "H", 48, "F", occupation="retired")]
            enr = provider.assign_household(members, rng, config)
            assert all(e.category == "national" for e in enr.values())

    def test_office_worker_household_mostly_employee(self):
        """A household with an office worker should usually be 被用者保険."""
        config = load_identity_config("JP")
        provider = get_provider("JP")
        rng = np.random.default_rng(2)
        employee = 0
        n = 300
        for i in range(n):
            members = [_person(f"P{i}a", f"H{i}", 40, occupation="office"),
                       _person(f"P{i}b", f"H{i}", 38, "F", occupation="homemaker")]
            enr = provider.assign_household(members, rng, config)
            if enr[f"P{i}a"].category == "employee":
                employee += 1
                # the homemaker spouse becomes a 被扶養者
                assert enr[f"P{i}b"].category == "dependent"
        assert employee / n > 0.85  # office P(employee)=0.92


@pytest.mark.unit
class TestCardHoldingMarginal:
    def test_copula_preserves_marginal_rate(self):
        """Gaussian-copula card model must preserve the configured age-banded rate."""
        config = load_identity_config("JP")
        provider = get_provider("JP")
        rng = np.random.default_rng(7)
        member = _person("M", "H", 65)  # card_holding_rate "60-69" = 0.90
        n = 4000
        held = 0
        for _ in range(n):
            u_house = float(rng.standard_normal())  # fresh household latent each draw
            ident = provider.assign_personal(member, u_house, rng, config)
            held += int(ident.has_id_card)
        rate = held / n
        assert abs(rate - 0.90) < 0.025

    def test_linked_requires_card(self):
        config = load_identity_config("JP")
        provider = get_provider("JP")
        rng = np.random.default_rng(3)
        member = _person("M", "H", 65)
        for _ in range(500):
            ident = provider.assign_personal(member, float(rng.standard_normal()), rng, config)
            if ident.id_card_linked_to_insurance:
                assert ident.has_id_card


@pytest.mark.unit
class TestAssignIdentitiesPass:
    def _registry(self) -> PopulationRegistry:
        reg = PopulationRegistry()
        members = [_person("P1", "HH1", 50), _person("P2", "HH1", 47, "F")]
        reg.households = [Household(household_id="HH1", members=members)]
        reg.persons = {m.person_id: m for m in members}
        return reg

    def test_attaches_timeline_with_enrollment(self):
        reg = self._registry()
        assign_identities(reg, "JP", master_seed=42)
        for p in reg.persons.values():
            assert p.identity is not None
            assert p.identity.current_enrollment() is not None
            assert p.identity.national.country == "JP"
            assert p.identity.national.national_id is not None

    def test_deterministic_with_seed(self):
        r1, r2 = self._registry(), self._registry()
        assign_identities(r1, "JP", master_seed=42)
        assign_identities(r2, "JP", master_seed=42)
        ids1 = [p.identity.current_enrollment().member_id for p in r1.persons.values()]
        ids2 = [p.identity.current_enrollment().member_id for p in r2.persons.values()]
        assert ids1 == ids2

    def test_us_is_noop(self):
        reg = self._registry()
        assign_identities(reg, "US", master_seed=42)
        # US has no identity.yaml in Phase 1 → pass is a no-op.
        assert all(p.identity is None for p in reg.persons.values())
