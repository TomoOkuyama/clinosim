"""DEPRECATED: `clinosim.simulator.seeding` moved to `clinosim.seeding` (Issue #553).

The seeding helpers (``ENRICHER_SEED_OFFSETS`` / ``derive_sub_seed`` /
``derive_phase_rng`` / ``chronic_medication_seed`` / ``discharge_prescription_seed``
/ ``individual_lab_seed`` / ``panel_specimen_seed``) are a foundation used by
15+ ``clinosim/modules/`` subpackages; they never depended on anything else
under ``clinosim/`` and were incorrectly filed under ``simulator/``, which is
supposed to be the layer *above* ``modules/``. Moved to the top-level
``clinosim/seeding.py`` (same layer as ``clinosim/codes/``).

This shim keeps existing ``from clinosim.simulator.seeding import ...``
imports working for one deprecation cycle. New code should import from
``clinosim.seeding`` directly. Remove this file after the cycle.
"""

from __future__ import annotations

import warnings

from clinosim.seeding import *  # noqa: F401, F403
from clinosim.seeding import (  # noqa: F401 — explicit re-exports for name-based imports
    ENRICHER_SEED_OFFSETS,
    chronic_medication_seed,
    derive_phase_rng,
    derive_sub_seed,
    discharge_prescription_seed,
    individual_lab_seed,
    panel_specimen_seed,
)

warnings.warn(
    "`clinosim.simulator.seeding` moved to `clinosim.seeding` (Issue #553). "
    "Update imports; this shim will be removed in a follow-up cycle.",
    DeprecationWarning,
    stacklevel=2,
)
