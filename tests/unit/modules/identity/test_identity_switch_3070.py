"""Issue #3070: ``--no-jp-insurance`` gives no one an insurance enrollment —
the newborns registered during the run included (they used to get one
through the per-person identity entry, which ignored the switch)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from clinosim.modules.identity.assign import identity_enabled
from clinosim.modules.population.person_init import _init_newborn_identity
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _baby() -> PersonRecord:
    return PersonRecord(person_id="P1-BABY", household_id="H1", age=0, sex="F", date_of_birth=date(2026, 3, 1))


def _registry() -> SimpleNamespace:
    return SimpleNamespace(households=[SimpleNamespace(household_id="H1", identity_latent=0.0)])


@pytest.mark.parametrize(
    ("country", "switch", "enabled"),
    [("JP", True, True), ("JP", False, False), ("US", False, True), ("US", True, True)],
)
def test_identity_switch(country: str, switch: bool, enabled: bool) -> None:
    assert identity_enabled(SimpleNamespace(country=country, jp_insurance_numbers=switch)) is enabled


def test_no_jp_insurance_newborn_gets_no_identity() -> None:
    baby = _baby()
    _init_newborn_identity(baby, SimpleNamespace(country="JP", random_seed=7, jp_insurance_numbers=False), _registry())
    assert baby.identity is None


def test_jp_newborn_gets_identity_when_numbering_is_on() -> None:
    baby = _baby()
    _init_newborn_identity(baby, SimpleNamespace(country="JP", random_seed=7, jp_insurance_numbers=True), _registry())
    assert baby.identity is not None
