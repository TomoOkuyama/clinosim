"""Hash-based draws go through ``clinosim.determinism`` (Issue #2837).

A ``hashlib.sha256(...)`` digest turned into a number with
``int.from_bytes`` is a stream-free draw. The canonical helpers are
``determinism.sha_quantile`` / ``sha_bernoulli`` / ``sha_normal`` /
``sha_weighted_choice`` / ``sha_index`` (draws) and ``clinosim/seeding.py``
(seeds); a copy of the formula elsewhere drifts silently. The remaining
sites are pinned below with the reason each one stays; the list only
shrinks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.determinism import sha_index, sha_quantile

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2] / "clinosim"
_CANONICAL = {"determinism.py", "seeding.py"}
_RATCHET = {
    # Identifiers built from a hash, not draws.
    "modules/imaging/engine.py": "DICOM UID integer",
    "modules/encounter/engine.py": "encounter id suffix",
    # Draws whose formula differs from the canonical helper; switching
    # would change existing output.
    "modules/population/encounter_anthropometry.py": "erfinv normal on (raw + 1) / (2**32 + 1)",
    "modules/document/narrative/_narrative_utils.py": "integer-cutoff Bernoulli",
    "modules/population/_demographics.py": "Rh factor: 2-byte value / 65535",
}


def _sites() -> set[str]:
    found = set()
    for path in _ROOT.rglob("*.py"):
        rel = path.relative_to(_ROOT).as_posix()
        if path.name in _CANONICAL and path.parent == _ROOT:
            continue
        if "int.from_bytes(" in path.read_text(encoding="utf-8"):
            found.add(rel)
    return found


def test_no_new_inline_hash_draw() -> None:
    new = _sites() - set(_RATCHET)
    assert not new, f"use clinosim.determinism / clinosim.seeding instead of an inline hash draw in: {sorted(new)}"


def test_ratchet_has_no_stale_entries() -> None:
    stale = set(_RATCHET) - _sites()
    assert not stale, f"remove these entries from _RATCHET; the inline draw is gone: {sorted(stale)}"


def test_sha_index_matches_the_digest_prefix_modulo() -> None:
    import hashlib

    for salt in ("a", "cc-variant|x|POP-1|ENC-1", "日本語"):
        for n, k in ((3, 4), (7, 8), (1, 8)):
            expected = int.from_bytes(hashlib.sha256(salt.encode()).digest()[:k], "big") % n
            assert sha_index(salt, n, byte_count=k) == expected


def test_sha_index_rejects_an_empty_range() -> None:
    with pytest.raises(ValueError):
        sha_index("a", 0)


def test_sha_quantile_four_byte_slots_match_the_removed_inheritance_helper() -> None:
    import hashlib

    h = hashlib.sha256(b"salt").digest()
    for off in (0, 4, 8, 12):
        expected = int.from_bytes(h[off : off + 4], "big") / (1 << 32)
        assert sha_quantile("salt", byte_offset=off, byte_count=4) == expected
