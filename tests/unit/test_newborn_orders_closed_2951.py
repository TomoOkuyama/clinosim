"""Issue #2951: every POST_ENCOUNTER enricher that places medication orders
runs before ``supersede_orders``, which closes the orders of a finished stay.

The newborn enricher appends vitamin K / ophthalmic prophylaxis orders to the
newborn's INPATIENT birth stay; when it ran after ``supersede_orders`` those
orders were never closed and stayed ``active`` after discharge.
"""

from __future__ import annotations

import pytest

from clinosim.simulator import enrichers
from clinosim.simulator.enrichers import POST_ENCOUNTER, register_builtin_enrichers

pytestmark = pytest.mark.unit

# POST_ENCOUNTER enrichers that append to ``record.orders``.
_ORDER_PLACING = ("newborn",)


def _post_encounter_sequence() -> list[str]:
    register_builtin_enrichers()
    stage = [e for e in enrichers._ENRICHERS.values() if e.stage == POST_ENCOUNTER]
    return [e.name for e in sorted(stage, key=lambda e: (e.order, e.name))]


@pytest.mark.parametrize("name", _ORDER_PLACING)
def test_order_placing_enricher_runs_before_supersede(name: str) -> None:
    seq = _post_encounter_sequence()
    assert seq.index(name) < seq.index("supersede_orders"), seq
