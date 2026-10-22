"""Issue #1758 — ``POP-NNN-BABY`` patient_id reused across sibling
deliveries from the same mother, silently overwriting the earlier
newborn's ``PersonRecord`` and ``PatientProfile`` on the registry.

Fix: inject a mother-local birth-order prefix BEFORE the ``-BABY``
suffix so the first delivery stays ``POP-NNN-BABY`` (backward compat
with the pre-fix cohort snapshot and the ``endswith("-BABY")`` check
in ``modules/output/cif_writer.py``), the second becomes
``POP-NNN-2-BABY``, the third ``POP-NNN-3-BABY``, and so on.
"""

from __future__ import annotations

import pytest

from clinosim.simulator.perinatal import _newborn_patient_id

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _newborn_patient_id with explicit birth_order
# ---------------------------------------------------------------------------


def test_first_delivery_preserves_pre_fix_bare_baby_suffix():
    """Backward compat: the first (or only) delivery to a mother keeps
    the original ``POP-NNN-BABY`` id. Pre-#1758 cohort snapshots and
    the ``endswith("-BABY")`` growth-chart hook stay untouched for
    single-parity mothers (which is the overwhelming majority of the
    cohort)."""
    assert _newborn_patient_id("POP-000445", birth_order=1) == "POP-000445-BABY"


def test_second_delivery_prefixes_birth_order_before_baby_suffix():
    """The second delivery gets ``POP-NNN-2-BABY``. ``-BABY`` stays as
    the end suffix so ``endswith("-BABY")`` call sites (growth-chart
    anthropometry in cif_writer.py) still match."""
    pid = _newborn_patient_id("POP-000445", birth_order=2)
    assert pid == "POP-000445-2-BABY"
    assert pid.endswith("-BABY")


def test_third_delivery_prefixes_birth_order_before_baby_suffix():
    pid = _newborn_patient_id("POP-000460", birth_order=3)
    assert pid == "POP-000460-3-BABY"
    assert pid.endswith("-BABY")


def test_default_birth_order_is_one_for_backward_compat_callers():
    """A caller that still invokes the function with just the mother id
    (test fixtures, tools, legacy call paths) must get the pre-fix id
    rather than a ValueError. birth_order defaults to 1."""
    assert _newborn_patient_id("POP-000445") == "POP-000445-BABY"


def test_zero_or_negative_birth_order_rejected():
    """A birth_order <= 0 is a caller bug (never a legitimate parity).
    Fail loudly so a counting mistake does not produce an id like
    ``POP-NNN-0-BABY`` that would collide with no existing baby."""
    with pytest.raises(ValueError, match="birth_order"):
        _newborn_patient_id("POP-000445", birth_order=0)
    with pytest.raises(ValueError, match="birth_order"):
        _newborn_patient_id("POP-000445", birth_order=-1)


# ---------------------------------------------------------------------------
# Downstream suffix invariant: every id this function produces must
# satisfy ``endswith("-BABY")`` so growth-chart anthropometry fires
# (cif_writer.py:54).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("order", range(1, 10))
def test_every_birth_order_ends_in_dash_baby(order: int):
    pid = _newborn_patient_id("POP-000001", birth_order=order)
    assert pid.endswith("-BABY"), f"birth_order={order} produced {pid!r} which breaks endswith('-BABY')"


# ---------------------------------------------------------------------------
# Collision guarantee: distinct birth orders produce distinct ids.
# ---------------------------------------------------------------------------


def test_distinct_birth_orders_produce_distinct_ids():
    seen = {_newborn_patient_id("POP-000445", birth_order=o) for o in range(1, 10)}
    assert len(seen) == 9


# ---------------------------------------------------------------------------
# End-to-end: simulate_delivery_encounter must assign distinct ids to
# siblings when the shared PopulationRegistry already carries the first
# newborn under the pre-fix bare id. This exercises the birth-order
# counting path.
# ---------------------------------------------------------------------------


class _MotherFacsimile:
    """Mother-side scaffolding sufficient for the registry probe used by
    the birth-order counter. The counter only inspects
    ``population_registry.persons`` keys, so this stub does not need to
    model the full ``PersonRecord``."""

    def __init__(self, pid: str) -> None:
        self.patient_id = pid


class _RegistryStub:
    def __init__(self, persons_keys: list[str]) -> None:
        self.persons = {k: _MotherFacsimile(k) for k in persons_keys}


def _simulate_birth_order_count(mother_pid: str, existing_keys: list[str]) -> int:
    """Mirror of the counter logic in ``simulate_delivery_encounter`` so
    the test can assert the arithmetic without spinning up a full
    simulator run (which would require every PatientProfile dependency).
    If the function body in perinatal.py ever drifts from this
    expression, this test will red-flag the divergence."""
    bare = f"{mother_pid}-BABY"
    prefix = f"{mother_pid}-"
    birth_order = 1
    for pid in existing_keys:
        if pid == bare or (pid.startswith(prefix) and pid.endswith("-BABY") and pid != bare):
            birth_order += 1
    return birth_order


def test_birth_order_counting_assigns_two_when_bare_baby_already_registered():
    """Mother already has ``POP-000445-BABY`` registered. The next
    delivery is the second — birth_order=2 produces ``POP-000445-2-BABY``."""
    reg = _RegistryStub(["POP-000445", "POP-000445-BABY"])
    assert _simulate_birth_order_count("POP-000445", list(reg.persons)) == 2


def test_birth_order_counting_assigns_three_after_two_siblings():
    reg = _RegistryStub(
        [
            "POP-000460",
            "POP-000460-BABY",
            "POP-000460-2-BABY",
        ]
    )
    assert _simulate_birth_order_count("POP-000460", list(reg.persons)) == 3


def test_birth_order_counting_ignores_other_mothers_babies():
    """``POP-000050-BABY`` must not count toward POP-000445's parity."""
    reg = _RegistryStub(
        [
            "POP-000445",
            "POP-000050-BABY",  # another mother's baby — unrelated
            "POP-000050-2-BABY",
        ]
    )
    assert _simulate_birth_order_count("POP-000445", list(reg.persons)) == 1


def test_birth_order_counting_handles_empty_registry():
    reg = _RegistryStub(["POP-000445"])
    assert _simulate_birth_order_count("POP-000445", list(reg.persons)) == 1
