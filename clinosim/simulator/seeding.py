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


def individual_lab_seed(order_id: str) -> int:
    """Per-individual-lab-order deterministic sub-seed in ``[0, 2**32)``.

    A non-panel scalar lab order (e.g. ``{test: "Cl"}`` posted by a disease YAML
    outside a BMP envelope) is conceptually one specimen, so specimen-rejection,
    hemolysis, technician assignment, and noise must draw from an isolated stream
    just like panel children do (AD-16). Pre-2026-06-23 the lab loop drew these
    from the patient-scoped master RNG, which meant any YAML edit that flipped a
    ``{test:"X"}`` order from "engine doesn't produce X" to "engine produces X"
    silently changed the master stream and shuffled unrelated patients' cohorts.
    Routing all individual lab orders through this sub-seed completes what
    ``panel_specimen_seed`` started for panel children.

    Order IDs are themselves derived deterministically from the master seed by
    the simulator, so this sub-seed is stable across runs and unique per order
    without needing the master seed.
    """
    salt = "clinosim:individual-lab:v1"
    digest = hashlib.sha256(f"{salt}|{order_id}".encode()).digest()[:6]
    return int.from_bytes(digest, "big") % (2**32)


# AD-55 Module enricher sub-seed offsets.
#
# Convention (PR1 2026-06-24): new modules MUST use a 16-bit hex ASCII
# offset (2 letters), e.g. 0x4944 = "ID". Identity (540_054) and
# microbiology (770_077) are grandfathered at their legacy decimal values
# to preserve byte-identical output for the 2026-06-24 master. Future
# device + HAI modules will follow the hex-ASCII convention (e.g.,
# device = 0x4456 "DV", hai = 0x4841 "HA").
#
# All values must be unique — duplicates would silently collide two
# modules' RNG streams. The assert below catches accidental clashes at
# import time. See docs/CONTRIBUTING-modules.md for the contributor
# rules and CLAUDE.md "AD-55 enricher patterns" for the architectural
# rule.
ENRICHER_SEED_OFFSETS = {
    "identity":       540_054,    # legacy decimal (grandfathered)
    "microbiology":   770_077,    # legacy decimal (grandfathered)
    "immunization":   0x494D,     # "IM"
    "code_status":    0x4353,     # "CS"
    "family_history": 0x4648,     # "FH"
    "care_level":     0x434C,     # "CL"
    "nursing":        0x4E55,     # "NU"
    "device":         0x4445,     # "DE" (PR-A)
    "hai":            0x4841,     # "HA" (PR-B)
    "antibiotic":     0x4142,     # "AB" (PR3b-1)
    "imaging":        0x4947,     # "IG" (Tier 1 #2 PR1, imaging chain)
    "allergy":        0x414C,     # "AL" (Tier 1 #3 α-min-1 PR1, allergy module)
    "document":       0x444F,     # "DO" (Tier 1 #3 α-min-1 PR1, document module)
    "triage":         0x5452,     # "TR" (Tier 1 #3 α-min-2 PR1, triage module)
    "narrative_template": 0x4E54, # "NT" (AD-65 TemplateNarrativePass)
}

assert len(set(ENRICHER_SEED_OFFSETS.values())) == len(ENRICHER_SEED_OFFSETS), \
    f"ENRICHER_SEED_OFFSETS contains duplicate values: {ENRICHER_SEED_OFFSETS!r}"
