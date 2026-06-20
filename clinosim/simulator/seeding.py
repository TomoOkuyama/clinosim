"""Deterministic sub-seed derivation (AD-16).

Shared helper so every module/enricher derives its own RNG sub-stream from the master
seed the *same* way, without touching the main random stream. Each caller passes a
distinct ``module_offset`` (keep offsets unique across callers — guarded by
``tests/unit/test_seeding.py``) and a per-entity ``key`` (patient_id / encounter_id / ...).

This module has no clinosim imports on purpose: it sits below every module so any of them
can use it without creating a dependency cycle.
"""

from __future__ import annotations

import hashlib


def derive_sub_seed(master_seed: int, module_offset: int, key: str) -> int:
    """Stable per-(module, key) sub-seed in ``[0, 2**32)``.

    Uses hashlib (not ``hash()``) so the result is reproducible regardless of
    ``PYTHONHASHSEED``. The formula is fixed: changing it shifts every derived RNG
    stream and therefore all golden output.
    """
    h = int.from_bytes(hashlib.sha256(key.encode()).digest()[:6], "big")
    return (int(master_seed) + module_offset + h) % (2**32)
