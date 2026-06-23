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


def panel_specimen_seed(parent_order_id: str) -> int:
    """Per-panel-parent deterministic sub-seed in ``[0, 2**32)``.

    Panel orders model **one specimen per parent order** (e.g. a CBC order produces
    one tube that yields WBC/Hb/Hct/Plt). Specimen-rejection and per-analyte
    hemolysis must therefore draw from a stream **isolated from the patient-scoped
    master RNG** so that adding a panel registry entry does not cascade into
    unrelated patients' cohorts (AD-16). The parent ``order_id`` is itself derived
    deterministically from the master seed by the simulator, so this seed is stable
    across runs and unique per panel-order without needing the master seed itself.

    The salt pins the formula: any change to the salt or the digest length shifts
    every panel-children RNG stream and therefore the panel-children Observations.
    """
    salt = "clinosim:panel-children:v1"
    digest = hashlib.sha256(f"{salt}|{parent_order_id}".encode()).digest()[:6]
    return int.from_bytes(digest, "big") % (2**32)
