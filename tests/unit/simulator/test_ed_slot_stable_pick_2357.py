"""ED slot patient choice is stable under population changes (Issue #2357)."""

from __future__ import annotations

from collections import Counter

import pytest

from clinosim.seeding import rendezvous_pick

pytestmark = pytest.mark.unit

_IDS = [f"POP-{i:06d}" for i in range(400)]
_KEYS = [f"US|ed-2025-03-{i:05d}" for i in range(300)]


def test_pick_is_deterministic() -> None:
    assert [rendezvous_pick(k, _IDS) for k in _KEYS] == [rendezvous_pick(k, _IDS) for k in _KEYS]


def test_order_of_residents_does_not_matter() -> None:
    picks = [_IDS[rendezvous_pick(k, _IDS)] for k in _KEYS]
    reversed_ids = list(reversed(_IDS))
    assert picks == [reversed_ids[rendezvous_pick(k, reversed_ids)] for k in _KEYS]


def test_removing_one_resident_moves_only_its_slots() -> None:
    before = [_IDS[rendezvous_pick(k, _IDS)] for k in _KEYS]
    gone = Counter(before).most_common(1)[0][0]
    remaining = [p for p in _IDS if p != gone]
    after = [remaining[rendezvous_pick(k, remaining)] for k in _KEYS]
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    assert changed
    assert all(before[i] == gone for i in changed)


def test_pick_is_close_to_uniform() -> None:
    ids = [f"P{i}" for i in range(20)]
    counts = Counter(rendezvous_pick(f"k{i}", ids) for i in range(20_000))
    assert set(counts) == set(range(20))
    assert max(counts.values()) / min(counts.values()) < 1.25
