"""Deterministic sub-seed derivation (AD-16).

Shared helper so every module/enricher derives its own RNG sub-stream from the master
seed the *same* way, without touching the main random stream. Each caller passes a
distinct ``module_offset`` (keep offsets unique across callers — guarded by
``tests/unit/test_seeding.py``) and a per-entity ``key`` (patient_id / encounter_id / ...).

This module sits below every domain module so any of them can use it without
creating a dependency cycle. The single ``from clinosim import determinism``
import wires ``derive_phase_rng`` into the bit-reproducible RNG proxy — the
``determinism`` module itself has no ``clinosim.*`` imports, so no cycle.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

from clinosim import determinism


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


def chronic_medication_seed(patient_id: str) -> int:
    """Per-patient deterministic sub-seed for chronic-medication selection (Issue #439).

    `_derive_home_medications` (activator.py) samples a patient's chronic drug
    regimen via `select_with_exclusive_classes` — an `exclusive_classes`
    categorical draw followed by independent Bernoulli picks over the remaining
    drugs. Pre-Issue-439 that sampling drew from the patient-scoped master RNG,
    so YAML edits to `chronic_medications.yaml` (e.g. adding a new drug,
    tweaking a probability, extending an `exclusive_classes` set) silently
    shifted every downstream draw for that patient AND cascaded across the
    whole cohort because the master stream is shared across patients.

    Sibling of ``panel_specimen_seed`` / ``individual_lab_seed`` — the same
    AD-16 pattern applied to the drug-selection layer. See CLAUDE.md
    "Per-order lab RNG isolation" (AD-59) for precedent; this helper extends
    the pattern to chronic-medication sampling per Issue #439 P1.

    Patient IDs are themselves derived deterministically from the master seed
    by population activation, so this sub-seed is stable across runs and
    unique per patient without needing the master seed itself.
    """
    salt = "clinosim:chronic-medication:v1"
    digest = hashlib.sha256(f"{salt}|{patient_id}".encode()).digest()[:6]
    return int.from_bytes(digest, "big") % (2**32)


def discharge_prescription_seed(patient_id: str, encounter_id: str) -> int:
    """Per-(patient, encounter) deterministic sub-seed for discharge Rx (Issue #439).

    `_build_discharge_rx` (inpatient.py) samples the discharge-oral block via
    `select_with_exclusive_classes` (categorical + Bernoulli) plus a
    `continue_at_discharge` loop. Pre-Issue-439 that sampling drew from the
    patient-scoped master RNG, so YAML edits to `drugs.discharge_oral` or
    `drugs.<category>` cascaded across unrelated patients' cohorts.

    Sibling of ``chronic_medication_seed`` — same AD-16 rationale, keyed on
    the encounter (not just the patient) because discharge sampling is
    per-admission (multiple admissions per patient must draw independently).

    Both patient_id and encounter_id are derived deterministically from the
    master seed by the simulator, so this sub-seed is stable across runs.
    """
    salt = "clinosim:discharge-prescription:v1"
    digest = hashlib.sha256(f"{salt}|{patient_id}|{encounter_id}".encode()).digest()[:6]
    return int.from_bytes(digest, "big") % (2**32)


def ambulatory_visit_length_seed(encounter_id: str) -> int:
    """Per-encounter deterministic sub-seed in ``[0, 2**32)`` for the
    outpatient (AMB) encounter length draw (Issue #927).

    Isolating the length draw from the master patient-scoped ``opd_rng``
    means the switch from a single ``rng.integers(15, 45)`` to a
    per-visit-type triangular draw does NOT shift any downstream RNG
    consumer (vitals derivation, lab-tech assignment, prescription
    sampling all keep their pre-fix byte-shape). The only cascade is
    the length column itself, which is the intended behavior change.

    Sibling of ``individual_lab_seed`` — same AD-16 rationale, keyed on
    ``encounter_id`` which is itself derived deterministically from the
    master seed by the simulator (``create_inpatient_encounter``), so
    this sub-seed is stable across runs and unique per outpatient
    encounter without needing the master seed.
    """
    salt = "clinosim:ambulatory-visit-length:v1"
    digest = hashlib.sha256(f"{salt}|{encounter_id}".encode()).digest()[:6]
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
#
# NOTE: narrative_pass seeds are caller-supplied (--seed CLI arg →
# TemplateNarrativePass(rng_seed=...)), NOT enricher offsets.
# TemplateNarrativePass is a Stage 2 post-simulation pass, not a
# POST_ENCOUNTER / POST_RECORDS enricher. β-JP-1 LLMNarrativePass will
# derive its own sub-seed here if it needs one (LLM randomness lives
# server-side; the pass RNG is only for local sampling like fact-order
# permutation, currently unused). Adding an aspirational scaffold
# offset that no code path calls is a PR-90 class "green tripwire"
# risk (see PR #131 adv-1 F-5 for the removal rationale).
ENRICHER_SEED_OFFSETS = {
    "identity": 540_054,  # legacy decimal (grandfathered)
    "microbiology": 770_077,  # legacy decimal (grandfathered)
    "immunization": 0x494D,  # "IM"
    "code_status": 0x4353,  # "CS"
    "family_history": 0x4648,  # "FH"
    "care_level": 0x434C,  # "CL"
    "nursing": 0x4E55,  # "NU"
    "device": 0x4445,  # "DE" (PR-A)
    "hai": 0x4841,  # "HA" (PR-B)
    "antibiotic": 0x4142,  # "AB" (PR3b-1)
    "imaging": 0x4947,  # "IG" (Tier 1 #2 PR1, imaging chain)
    "allergy": 0x414C,  # "AL" (Tier 1 #3 α-min-1 PR1, allergy module)
    "document": 0x444F,  # "DO" (Tier 1 #3 α-min-1 PR1, document module)
    "triage": 0x5452,  # "TR" (Tier 1 #3 α-min-2 PR1, triage module)
    "health_checkup": 0x4843,  # "HC" (per-patient checkup lab sampling)
    "medication_monitoring": 0x4D4D,  # "MM" (#757 chronic-med → monitoring lab pairs)
}

assert len(set(ENRICHER_SEED_OFFSETS.values())) == len(ENRICHER_SEED_OFFSETS), (
    f"ENRICHER_SEED_OFFSETS contains duplicate values: {ENRICHER_SEED_OFFSETS!r}"
)


# ------------------------------------------------------------------
# Phase-scoped sub-seed offsets (F1 cross-cursor determinism).
#
# The four run_beta phases (life-event generation / hospital main loop
# / readmission / outpatient calendar / ED) currently consume the
# master RNG serially. If a cursor advance (snapshot_date change)
# changes the event count in phase P1, the master RNG state at the
# start of phase P2 differs — so the same patient X ends up with a
# different result under the new cursor, and "the shared interval
# between the output at cursor A and the output at cursor B is
# bytewise identical" is not guaranteed.
#
# Separating a phase salt here and switching to per-key sub-seeds
# inside each phase bypasses the master RNG entirely, so a cursor
# advance no longer propagates across phases.
#
# Convention: 32-bit values whose four bytes are ASCII uppercase
# letters, using the 0x504xxxxx range to avoid collisions with the
# existing ENRICHER_SEED_OFFSETS values.
PHASE_LIFE_EVENT = 0x504C4556  # "PLEV"
PHASE_INPATIENT_SIM = 0x50494E50  # "PINP"
PHASE_READMISSION = 0x50524541  # "PREA"
PHASE_OUTPATIENT_CAL = 0x504F5054  # "POPT"
PHASE_ED_VISIT = 0x50454456  # "PEDV"

_PHASE_OFFSETS = {
    "life_event": PHASE_LIFE_EVENT,
    "inpatient_sim": PHASE_INPATIENT_SIM,
    "readmission": PHASE_READMISSION,
    "outpatient_calendar": PHASE_OUTPATIENT_CAL,
    "ed_visit": PHASE_ED_VISIT,
}

assert len(set(_PHASE_OFFSETS.values())) == len(_PHASE_OFFSETS), f"phase offset collision: {_PHASE_OFFSETS!r}"


def derive_phase_rng(master_seed: int, phase_salt: int, key: str) -> np.random.Generator:
    """Return an independent RNG stream per ``(phase, key)`` inside ``run_beta`` (AD-16).

    Cursor A and cursor B asking for the same ``(phase, key)`` receive
    the same stream, which guarantees cross-cursor byte-identity. The
    ``key`` argument must be an entity identifier that is unique within
    the phase — for example ``event.person_id + timestamp +
    disease_id``.
    """

    return determinism.default_rng(derive_sub_seed(master_seed, phase_salt, key))
