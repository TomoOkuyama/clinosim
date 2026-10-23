"""Issue #1752: K70/K74 chronic promotion to PersonRecord on discharge.

Pre-fix the discharge→chronic promotion filter in
``simulator/helpers.py`` restricted the K-prefix allowlist to just
``K21`` (GERD). This silently dropped every discharge with a K70
(alcoholic liver disease) or K74 (fibrosis / cirrhosis of liver,
non-alcoholic) primary dx, so the Markov Child-Pugh stage attribute
(``fibrosis_liver_stage_k74`` / ``alcoholic_liver_stage_k70``) never
entered scope on the longitudinal engine's next-year pass. Cohort
scan showed 100 % of US K74 patients (42/42) carrying empty
``stage=""`` on their chronic_conditions row.

Fix: add ``K70`` + ``K74`` to the ``chronic_prefixes`` tuple. The
longitudinal engine's `_attribute_in_scope` + the stage-writeback
path then dispatch the initial Child-Pugh draw on the next
``advance_one_year`` call.
"""

from __future__ import annotations

import inspect

import pytest

from clinosim.simulator import helpers as _helpers

pytestmark = pytest.mark.unit


def _extract_chronic_prefixes() -> tuple[str, ...]:
    """Pull the ``chronic_prefixes`` literal out of the function source
    so the test does not require constructing a full PersonRecord +
    hospitalization record fixture to probe the behaviour."""
    src = inspect.getsource(_helpers._deactivate_to_layer1)
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("chronic_prefixes = (") and s.endswith(")"):
            tuple_src = s[len("chronic_prefixes = ") :]
            return tuple(eval(tuple_src))  # noqa: S307 — hard-coded literal from this repo's src
    raise AssertionError("chronic_prefixes literal not found in _deactivate_to_layer1")


# ----------------------------------------------------------------------------
# K70 + K74 now in the chronic-propagation allowlist
# ----------------------------------------------------------------------------


def test_k74_in_chronic_prefixes() -> None:
    """K74 primary dx must now propagate — fix for #1752."""
    assert "K74" in _extract_chronic_prefixes()


def test_k70_in_chronic_prefixes() -> None:
    """K70 (alcoholic liver disease) gets the same treatment —
    sibling attribute alcoholic_liver_stage_k70 depends on the
    same propagation path."""
    assert "K70" in _extract_chronic_prefixes()


# ----------------------------------------------------------------------------
# Pre-existing K21 propagation stays — the fix is strictly additive
# ----------------------------------------------------------------------------


def test_k21_still_in_chronic_prefixes() -> None:
    """K21 (GERD) was the only K-prefix allowed pre-fix. Keep it so
    GERD cohort stays byte-identical."""
    assert "K21" in _extract_chronic_prefixes()


# ----------------------------------------------------------------------------
# Downstream contract: with K74 in person.chronic_conditions, the
# longitudinal engine's scope check passes for fibrosis_liver_stage_k74.
# ----------------------------------------------------------------------------


def test_scope_check_passes_once_k74_is_on_person() -> None:
    """Simulate the post-propagation state: a PersonRecord with
    ``chronic_conditions = ["K74"]`` passes the K74 Markov attribute's
    scope gate. This is the invariant the fix unblocks — the engine
    then dispatches the initial Child-Pugh A/B/C draw on next
    ``advance_one_year``."""
    from datetime import date

    from clinosim.modules.longitudinal.engine import _attribute_in_scope
    from clinosim.modules.longitudinal.loader import load_attribute_specs
    from clinosim.types.population import PersonRecord

    specs = load_attribute_specs()
    spec = specs["fibrosis_liver_stage_k74"]
    person = PersonRecord(
        person_id="POP-k74-pin",
        household_id="HH-1",
        age=55,
        sex="M",
        date_of_birth=date(1969, 1, 1),
        chronic_conditions=["K74"],
    )
    assert _attribute_in_scope(spec, person, 2024)
