"""Antibiotic audit — second per-Module AD-60 plug-in.

Mirrors modules/hai/audit.py but the lift_firing_proof exercises the
real enricher path (enrich_antibiotic) against a synthetic CAUTI
HAIEvent, asserting:
  - extensions["antibiotic"] has exactly 1 regimen
  - regimen.drug_key == "ceftriaxone", duration_days == 7
  - record.orders has 1 MEDICATION order with display_name "Ceftriaxone"
  - record.medication_administrations has 7 MAR entries (q24h × 7d)

PR3b-2 extension: combined proof adds antibiogram_firing_proof checks:
  - Synthetic CLABSI/S. aureus HAIEvent → 6 susceptibility results
  - Vancomycin (LOINC via ANTIBIOTIC_LOINC_LOOKUP) always S ([1.00, 0.00, 0.00])
  - Cefazolin seed=0 deterministic interpretation = S (non-degenerate probe)

This is the load-bearing PR-90 silent-no-op gate for PR3b-1 + PR3b-2.

Registered checks:
- canonical_constants: HAI_TYPES + ANTIBIOTIC_DRUGS cross-validate
  against hai_empirical.yaml at import time (via load_hai_empirical).
  PR3b-3 adds load_narrow_ladder() touch with 4-way validation (forward
  + reverse-coverage + empty-container) at audit module import.
- structural_obs_codes: empty — susceptibility Observations use
  valueCodeableConcept (categorical S/I/R) rather than valueQuantity +
  referenceRange + interpretation; the structural axis numeric-coverage
  check does not apply to categorical observations. See _ABX_LOINCS for
  the full set. PR3b-3 extended the clinical axis with population-level
  R-rate gate against these LOINCs (per-organism filter deferred to
  follow-up; see clinical.py TODO).
- clinical_acceptance: per-HAI-type expected drug set + duration +
  min_mar_per_event + NHSN resistance band metadata (nhsn_r_bands key) +
  PR3b-3 narrow_rate_bands (per-hai_type aggregate) +
  hai_empty_susceptibilities_max_rate. The clinical axis enforces all
  three gates (R-rate + empty-rate + narrow-rate) with n<30 → WARN
  guards.
- lift_firing_proof (_build_combined_proof): merged PR3b-1 + PR3b-2 + PR3b-3.
    PR3b-1 (regimen): CAUTI ceftriaxone — 8 equality_checks.
    PR3b-2 (antibiogram): CLABSI S. aureus susceptibility chain — 3 checks.
    PR3b-3 (narrow): CLABSI MSSA SWITCH → cefazolin — 6 checks.
  All 17 equality_checks run in one silent_no_op axis pass.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS, ANTIBIOTIC_LOINC_LOOKUP
from clinosim.modules.antibiotic.engine import _HAI_EMPIRICAL_YAML
from clinosim.modules.antibiotic.enricher import enrich_antibiotic
from clinosim.modules.hai import HAI_TYPES
from clinosim.types.hai import HAIEvent

# PR3b-2: All antibiotic susceptibility LOINC codes emitted by _append_hai_culture.
# These codes appear as Observation.code.coding[].code in FHIR output for
# susceptibility Observations. Presence is verified by the combined proof
# (clabsi_saureus_susceptibility_count=6 + vancomycin_is_S checks) rather than
# structural_obs_codes because categorical observations have no referenceRange.
_ABX_LOINCS: frozenset[str] = frozenset(ANTIBIOTIC_LOINC_LOOKUP.values())

# PR3b-3 wired active enforcement of these bands in
# clinosim/audit/axes/clinical.py (complete 2026-06-29):
#   - NHSN R-rate gate per-(hai_type, organism, antibiotic) cohort — uses
#     _organism_per_encounter to filter cohort by per-organism culture so
#     bands measure pure per-organism resistance rates.
#   - empty-susceptibilities rate gate per panel-eligible HAI cohort —
#     uses _panel_eligible_organisms to restrict denominator to encounters
#     with at least one organism that has an antibiogram S/I/R panel.
#   - narrow-rate gate (per-hai_type aggregate) — see clinical.py
#     "PR3b-3: narrow-rate gate" block. Cohort key format is per-hai_type
#     only (single string), not per-(hai_type, organism) — adversarial-1
#     C-1 fix corrected the format mismatch.
#
# Cohort string convention (NHSN R-bands): "<hai_type>/<organism_snomed>"
# (exactly 2 components). Parse with: hai_type, org_snomed = band["cohort"]
# .split("/", maxsplit=1). Adding a 3rd dimension (e.g., "clabsi/3092008/icu")
# requires changing to a structured type (dataclass or TypedDict). Do NOT
# use split("/") without maxsplit.
#
# Cohort string convention (narrow rate bands, PR3b-3 adv-1):
# "<hai_type>" only. Single string, no slash. Validated by
# _validate_narrow_rate_bands.
#
# Sources: CDC NHSN "Antimicrobial Resistance Patterns in Acute Care Hospitals" 2018-2020.
_NHSN_RESISTANCE_BANDS: list[dict[str, Any]] = [
    {
        "cohort": "clabsi/3092008",  # S. aureus CLABSI
        "antibiotic": "cefazolin",  # MRSA proxy (cefazolin R ≈ MRSA rate)
        "expected_R_min": 0.40,
        "expected_R_max": 0.55,
        "source": "NHSN AR 2018-2020 Table 2",
    },
    {
        "cohort": "cauti/112283007",  # E. coli CAUTI
        "antibiotic": "ceftriaxone",  # ESBL proxy
        "expected_R_min": 0.12,
        "expected_R_max": 0.22,
        "source": "NHSN AR 2018-2020 Table 4",
    },
    {
        "cohort": "vap/3092008",  # S. aureus VAP
        "antibiotic": "cefazolin",  # MRSA proxy
        "expected_R_min": 0.30,
        "expected_R_max": 0.45,
        "source": "NHSN AR 2018-2020 Table 2",
    },
]

# Empty-susceptibilities rate acceptance bound (PR3b-3 D2 complete, 2026-06-29).
#
# Denominator: PANEL-ELIGIBLE HAI cultures only — those whose organism appears
# in hai_antibiogram.yaml. Excludes no-panel organisms (E.faecalis 78065002,
# C.albicans 53326005) automatically via clinical.py:_panel_eligible_organisms,
# which derives the eligible set from load_hai_antibiogram() keys.
#
# Rationale: CLABSI has ~28% no-panel organism weight (0.15 C.albicans + 0.13
# E.faecalis); CAUTI has ~34%. Computing empty rate over ALL cultures would
# make the gate always-FAIL. The 5% threshold is 10× the measured rate at p=10k
# (0.5%) to give safety margin for small-p Bernoulli noise.
HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE: float = 0.05


def _build_synthetic_proof() -> dict[str, Any]:
    """Drive enrich_antibiotic against a synthetic CAUTI record (PR3b-1 regimen proof).

    Uses the **equality_checks** proof format (silent_no_op axis post-fix
    extension), which the AD-60 framework iterates and asserts hard
    equality on. This format is appropriate for structural verification
    (Order count, MAR count, regimen properties) where the Phase 3a
    Observation-delta format does not fit.

    PR-90 教訓: canonical strings + actual enricher invocation, NOT a
    fixture bypass; AND the proof MUST be consumed by the axis (the
    PR-93 first attempt returned a plain dict that silent_no_op skipped
    without raising — itself a PR-90 class bug in the proof harness).
    """
    ev = HAIEvent(
        hai_id="h-cauti-proof",
        encounter_id="enc-proof",
        hai_type=HAI_TYPES[1],  # "cauti" — canonical, NEVER literal string
        source_device_id="d1",
        icd10_code="T83.511A",
        snomed_code="68566005",
        onset_date="2026-01-10",
        organism_snomed="112283007",
        culture_specimen_id="s1",
    )
    rec = SimpleNamespace(
        patient=SimpleNamespace(patient_id="p-proof"),
        encounters=[],
        orders=[],
        medication_administrations=[],
        microbiology=[],
        extensions={"hai": [ev]},
    )
    cfg = SimpleNamespace(
        country="US",
        snapshot_date=None,
        time_range=("2026-01-01", "2026-12-31"),
    )
    ctx = SimpleNamespace(config=cfg, master_seed=42, records=[rec])
    enrich_antibiotic(ctx)

    abx = rec.extensions.get("antibiotic", []) or []
    med_orders = [o for o in rec.orders if getattr(o.order_type, "value", "") == "medication"]
    mar = rec.medication_administrations

    return {
        # equality_checks format: list[tuple[label, actual, expected]]
        # The silent_no_op axis iterates and asserts hard equality on each.
        "equality_checks": [
            ("ext_antibiotic_count", len(abx), 1),
            ("ext_antibiotic_drug", abx[0].drug_key if abx else None, "ceftriaxone"),
            ("ext_antibiotic_duration_days", abx[0].duration_days if abx else None, 7),
            ("orders_medication_count", len(med_orders), 1),
            ("mar_count", len(mar), 7),
            ("mar_drug", mar[0].drug_name if mar else None, "Ceftriaxone"),
            ("mar_first_dt", mar[0].scheduled_datetime if mar else None, datetime(2026, 1, 10, 8)),
            ("mar_last_dt", mar[-1].scheduled_datetime if mar else None, datetime(2026, 1, 16, 8)),
        ],
    }


def _antibiogram_firing_proof_checks() -> list[tuple[str, Any, Any]]:
    """Synthetic CLABSI/S. aureus → exact susceptibility count + vancomycin = S.

    Exercises the PR3b-2 chain end-to-end:
      load_hai_antibiogram() → _append_hai_culture() → MicrobiologyResult.susceptibilities

    CLABSI/S. aureus (organism_snomed "3092008") has 6 antibiotic entries in
    hai_antibiogram.yaml: vancomycin, cefazolin, ceftriaxone, cefepime,
    ciprofloxacin, trimethoprim_sulfamethoxazole. Vancomycin probability
    [1.00, 0.00, 0.00] → interpretation is always "S" for any rng state.

    PR-90 教訓: uses HAI_TYPES[0] (not literal "clabsi"), uses
    ANTIBIOTIC_LOINC_LOOKUP["vancomycin"] (not hardcoded "18991-2"),
    verifies actual enricher invocation not a fixture shortcut.
    """
    import numpy as np  # local import — numpy is heavy; avoid at audit.py module level

    from clinosim.modules.hai import load_hai_antibiogram  # local: avoids circular import
    from clinosim.modules.hai.enricher import _append_hai_culture  # private API; intentional

    rec: dict[str, Any] = {}
    ev = HAIEvent(
        hai_id="hai-proof",
        encounter_id="enc-proof",
        hai_type=HAI_TYPES[0],  # "clabsi" — canonical constant, NOT literal
        source_device_id="dev-proof",
        icd10_code="T80.211A",
        snomed_code="431193003",  # CLABSI SNOMED (placeholder; proof reads antibiogram)
        onset_date="2024-01-15",
        organism_snomed="3092008",  # S. aureus SNOMED
        culture_specimen_id="spec-proof",
    )
    abg = load_hai_antibiogram()
    rng = np.random.default_rng(0)
    _append_hai_culture(
        rec,
        ev,
        {"specimen": "blood", "specimen_snomed": "119297000", "test_loinc": "600-7"},
        "2024-01-15",
        abg,
        rng,
    )
    susc = rec["microbiology"][0].susceptibilities
    # Use ANTIBIOTIC_LOINC_LOOKUP — not literal "18991-2" — so a LOINC change
    # propagates automatically and the proof catches the drift.
    vanc_loinc = ANTIBIOTIC_LOINC_LOOKUP["vancomycin"]
    vanc_interp: str | None = next(
        (s.interpretation for s in susc if s.antibiotic_loinc == vanc_loinc),
        None,
    )
    cefaz_loinc = ANTIBIOTIC_LOINC_LOOKUP["cefazolin"]
    cefaz_interp: str | None = next(
        (s.interpretation for s in susc if s.antibiotic_loinc == cefaz_loinc),
        None,
    )
    return [
        # CLABSI/S. aureus antibiogram has exactly 6 drugs — count verifies no silent omission.
        ("clabsi_saureus_susceptibility_count", len(susc), 6),
        # Vancomycin [1.00, 0.00, 0.00] is always S; any other value = antibiogram load bug.
        ("clabsi_saureus_vancomycin_is_S", vanc_interp, "S"),
        # PR3b-2 Adv #6 F3: cefazolin probs are [0.53, 0.00, 0.47] — non-degenerate.
        # At rng seed=0: deterministic outcome is "S". If YAML key order shifts,
        # the rng draws a different probability row → different interpretation.
        ("clabsi_saureus_cefazolin_seed0_interp", cefaz_interp, "S"),
    ]


def _pr3b3_narrow_proof_checks() -> list[tuple[str, Any, Any]]:
    """Synthetic CLABSI/MSSA (cefazolin S) → SWITCH outcome verification.

    Drives the full enrich_antibiotic chain (Pass 1 empirical + Pass 2 narrow)
    against a record that has both the HAI event AND a pre-built culture with
    cefazolin S, vancomycin S, piperacillin_tazobactam S. Verifies:
      1. narrow_target chosen = cefazolin
      2. empirical vancomycin discontinuation_datetime is set
      3. empirical pip-tazo discontinuation_datetime is set
      4. new narrowed regimen count == 1
      5. new narrowed regimen drug_key == "cefazolin"
      6. new narrowed regimen intent == "narrowed"
    """
    from datetime import datetime as _dt
    from types import SimpleNamespace

    from clinosim.types.microbiology import MicrobiologyResult, SusceptibilityResult

    onset_date = "2026-01-10"
    reported_dt = _dt(2026, 1, 12)
    ev = HAIEvent(
        hai_id="hai-pr3b3-proof",
        encounter_id="enc-pr3b3",
        hai_type=HAI_TYPES[0],  # clabsi
        source_device_id="dev-proof",
        icd10_code="T80.211A",
        snomed_code="431193003",
        onset_date=onset_date,
        organism_snomed="3092008",  # S.aureus
        culture_specimen_id="spec-proof",
    )
    micro = MicrobiologyResult(
        encounter_id="enc-pr3b3",
        specimen="blood", specimen_snomed="119297000", test_loinc="600-7",
        collected_datetime=_dt.fromisoformat(onset_date),
        reported_datetime=reported_dt,
        growth=True,
        organism_snomed="3092008",
        susceptibilities=[
            SusceptibilityResult(antibiotic_loinc=ANTIBIOTIC_LOINC_LOOKUP["vancomycin"], interpretation="S"),
            SusceptibilityResult(antibiotic_loinc=ANTIBIOTIC_LOINC_LOOKUP["cefazolin"], interpretation="S"),
            SusceptibilityResult(antibiotic_loinc=ANTIBIOTIC_LOINC_LOOKUP["piperacillin_tazobactam"], interpretation="S"),
        ],
        hai_event_id=ev.hai_id,
    )
    rec = SimpleNamespace(
        patient=SimpleNamespace(patient_id="p-pr3b3-proof"),
        encounters=[],
        orders=[],
        medication_administrations=[],
        microbiology=[micro],
        extensions={"hai": [ev]},
    )
    cfg = SimpleNamespace(
        country="US",
        snapshot_date="2026-12-31",
        time_range=("2026-01-01", "2026-12-31"),
    )
    ctx = SimpleNamespace(config=cfg, master_seed=42, records=[rec])
    enrich_antibiotic(ctx)

    regimens = rec.extensions.get("antibiotic", [])
    empirical = [r for r in regimens if r.intent == "empirical"]
    narrowed = [r for r in regimens if r.intent == "narrowed"]
    vanc = next((r for r in empirical if r.drug_key == "vancomycin"), None)
    pip = next((r for r in empirical if r.drug_key == "piperacillin_tazobactam"), None)

    return [
        ("pr3b3_narrow_target_drug",
         narrowed[0].drug_key if narrowed else None, "cefazolin"),
        ("pr3b3_empirical_vancomycin_discontinued_at",
         vanc.discontinuation_datetime if vanc else None, reported_dt),
        ("pr3b3_empirical_pip_tazo_discontinued_at",
         pip.discontinuation_datetime if pip else None, reported_dt),
        ("pr3b3_new_narrowed_regimen_count", len(narrowed), 1),
        ("pr3b3_new_narrowed_regimen_drug",
         narrowed[0].drug_key if narrowed else None, "cefazolin"),
        ("pr3b3_new_narrowed_regimen_intent",
         narrowed[0].intent if narrowed else None, "narrowed"),
    ]


def _build_combined_proof() -> dict[str, Any]:
    """Combined proof: PR3b-1 antibiotic regimen + PR3b-2 antibiogram S/I/R chain
    + PR3b-3 narrow / de-escalation chain.

    Merges equality_checks from sub-proofs so the silent_no_op axis verifies
    the full PR3b-1 + PR3b-2 + PR3b-3 pipeline in a single pass.

    Produces 17 equality_checks total:
      8 from _build_synthetic_proof  — CAUTI ceftriaxone regimen (PR3b-1)
      3 from _antibiogram_firing_proof_checks — CLABSI S. aureus susc (PR3b-2)
      6 from _pr3b3_narrow_proof_checks — CLABSI MSSA SWITCH (PR3b-3)
    """
    regimen_result = _build_synthetic_proof()
    try:
        antibiogram_checks = _antibiogram_firing_proof_checks()
    except Exception as e:
        antibiogram_checks = [
            ("antibiogram_firing_proof_raised", f"{type(e).__name__}: {e}", "no exception"),
        ]
    try:
        narrow_checks = _pr3b3_narrow_proof_checks()
    except Exception as e:
        narrow_checks = [
            ("pr3b3_narrow_proof_raised", f"{type(e).__name__}: {e}", "no exception"),
        ]
    return {
        "equality_checks": (
            list(regimen_result.get("equality_checks") or [])
            + list(antibiogram_checks)
            + list(narrow_checks)
        ),
    }


# PR3b-3 narrow rate bands per hai_type (adversarial-1 C-1 + C-2 fix:
# previously the cohort key was "<hai_type>/<organism_snomed>" but the
# clinical-axis gate parsed and DISCARDED organism, filtering only by hai_type.
# Bands were calibrated as if per-organism but enforced per-hai_type → would
# FAIL at production n≥30 on correct behavior. Realign cohort format to match
# what the gate actually measures: per-hai_type aggregate narrow rate.
#
# Aggregate narrow rate per hai_type (Pass 2 fires when culture has S in ladder
# AND the S drug differs from any existing empirical OR there's a multi-drug
# empirical with an S target = ELIMINATION; vancomycin S → MRSA ELIMINATION
# always fires on multi-drug CLABSI/VAP empirical):
#   - CLABSI: ~75-95% (vancomycin always S → ELIMINATION fires on every
#     CLABSI with multi-drug empirical; cefazolin S adds SWITCH ~25%;
#     gram-neg organisms get SWITCH ~85-92%; E.faecalis/C.albicans no panel
#     = NO_CHANGE; weighted average ~75-90%)
#   - CAUTI: ~60-95% (ceftriaxone single-drug empirical; narrow targets via
#     TMP-SMX / cipro / cefepime / meropenem ladder; only when ladder picks
#     ceftriaxone itself = NO_CHANGE)
#   - VAP: ~75-95% (multi-drug vanc + pip-tazo empirical; vancomycin always S
#     → ELIMINATION on every VAP with S.aureus / S.epidermidis; gram-neg
#     coverage mostly SWITCH)
_NARROW_RATE_BANDS: list[dict[str, Any]] = [
    {
        "cohort": "clabsi",
        "expected_narrow_rate_min": 0.60,
        "expected_narrow_rate_max": 1.00,
        "source": "Aggregate per-hai_type: vancomycin always-S ELIMINATION + "
                  "cefazolin SWITCH + gram-neg SWITCH (NHSN AR 2018-2020 weighted)",
    },
    {
        "cohort": "cauti",
        "expected_narrow_rate_min": 0.50,
        "expected_narrow_rate_max": 1.00,
        "source": "Aggregate per-hai_type: ceftriaxone single-empirical, ladder "
                  "walk picks narrower target ~80-95% of E.coli / K.pneumoniae "
                  "(NHSN AR 2018-2020 weighted)",
    },
    {
        "cohort": "vap",
        "expected_narrow_rate_min": 0.60,
        "expected_narrow_rate_max": 1.00,
        "source": "Aggregate per-hai_type: vancomycin always-S ELIMINATION on "
                  "S.aureus VAP + cefazolin SWITCH (MSSA) + gram-neg ladder SWITCH",
    },
]


# adversarial-1 I-G3 fix: validate _NARROW_RATE_BANDS at import time so a typo
# in cohort string (e.g. "clabis" instead of "clabsi") raises ValueError
# instead of silently no-op'ing the gate (matches _validate_nhsn_resistance_bands
# pattern). Cohort format is per-hai_type only (no slash).
def _validate_narrow_rate_bands() -> None:
    """Cross-check _NARROW_RATE_BANDS cohort + band shape (adversarial-1 I-G3).

    Stage-3 fix (adversarial-2 Agent A1 I-3): also rejects empty
    _NARROW_RATE_BANDS = [] which previously silent-passed the loop and
    combined with `if narrow_bands:` short-circuit in clinical.py would
    silently disable the entire narrow rate gate.

    pr112-adv-3 fix (Agent 2 MEDIUM): also enforce **forward-coverage** —
    every HAI_TYPES entry must have at least one band. If a new HAI_TYPE
    were added without a corresponding _NARROW_RATE_BANDS entry, the
    narrow rate gate would silently no-op for that hai_type. Matches the
    silent-no-op defense layer 4 reverse-coverage pattern adv-1 applied
    to _NHSN_RESISTANCE_BANDS.
    """
    if not _NARROW_RATE_BANDS:
        raise ValueError(
            "_NARROW_RATE_BANDS is empty — narrow rate gate would be silently "
            "disabled (PR-90 class silent no-op)"
        )
    valid_hai_types = set(HAI_TYPES)
    banded_hai_types: set[str] = set()
    for band in _NARROW_RATE_BANDS:
        cohort = band.get("cohort", "")
        if "/" in cohort:
            raise ValueError(
                f"_NARROW_RATE_BANDS cohort {cohort!r} must be <hai_type> only "
                f"(no slash) — adversarial-1 C-1 fix realigned cohort format to "
                f"per-hai_type aggregate"
            )
        if cohort not in valid_hai_types:
            raise ValueError(
                f"_NARROW_RATE_BANDS cohort {cohort!r} not in HAI_TYPES "
                f"{sorted(valid_hai_types)}"
            )
        for required_key in ("expected_narrow_rate_min", "expected_narrow_rate_max", "source"):
            if required_key not in band:
                raise ValueError(
                    f"_NARROW_RATE_BANDS band {cohort!r} missing required key {required_key!r}"
                )
        mn = band["expected_narrow_rate_min"]
        mx = band["expected_narrow_rate_max"]
        if not (0.0 <= mn <= mx <= 1.0):
            raise ValueError(
                f"_NARROW_RATE_BANDS band {cohort!r} invalid range "
                f"[{mn}, {mx}] (must satisfy 0 ≤ min ≤ max ≤ 1)"
            )
        banded_hai_types.add(cohort)

    # pr112-adv-3 forward-coverage: every HAI_TYPE must have a band.
    missing = valid_hai_types - banded_hai_types
    if missing:
        raise ValueError(
            f"_NARROW_RATE_BANDS forward-coverage gap: HAI_TYPES {sorted(missing)!r} "
            f"have no narrow rate band. Adding a new hai_type to HAI_TYPES requires "
            f"a corresponding _NARROW_RATE_BANDS entry — otherwise the narrow rate "
            f"gate silently no-ops for that hai_type (silent-no-op defense layer 4)."
        )


# adversarial-1 I-D3 fix + pr112-adv-2 ordering fix: ALL validators
# (_validate_narrow_rate_bands, _validate_nhsn_resistance_bands,
# _validate_narrow_ladder_at_import) MUST run BEFORE register_audit_module so
# that ANY band-shape / canonical-constants / reverse-coverage failure
# prevents stale spec from registering into the audit registry.
#
# PR3b-3 stage-2 adversarial finding (Agent 1 CRITICAL): the original adv-1
# placed only _validate_narrow_rate_bands before register; the new
# _validate_nhsn_resistance_bands (with I3 reverse-coverage check) and the
# pre-existing _validate_narrow_ladder_at_import were still invoked at the
# bottom of the module → AFTER register_audit_module. A reverse-coverage
# gap would have raised AFTER the stale spec entered the registry. Fixed
# by moving all 3 validators (+ their dependent constants + function
# bodies) ABOVE register_audit_module.

# PR3b-3 stage-1 adversarial finding I3 (2026-06-29): organisms intentionally
# not banded in _NHSN_RESISTANCE_BANDS but present in hai_antibiogram.yaml.
# Each entry MUST include a one-line rationale comment so a future contributor
# understands why the silent-no-op exemption is intentional. SNOMED codes
# verified against hai_antibiogram.yaml current state.
#
# NHSN clinical-accuracy note: each rationale references "NHSN AR 2018-2020
# does not publish a population band" or "covered indirectly by sibling band".
# If a future contributor finds an NHSN-published band for any exempt pair,
# the correct action is to ADD the band (with NHSN Table # citation) and
# REMOVE the exempt entry — NOT to leave the exempt with a stale rationale.
_NHSN_REVERSE_COVERAGE_EXEMPT: frozenset[tuple[str, str]] = frozenset({
    # CoNS (Coagulase-negative Staphylococci) is a frequent CLABSI organism
    # but its empirical R% varies widely by hospital and is contamination-
    # confounded; NHSN AR 2018-2020 does not publish a stable population
    # band for this proxy.
    ("clabsi", "60875001"),
    # E.coli CLABSI is uncommon (line infection by enteric is unusual
    # outside ICU); NHSN does not publish a CLABSI-specific E.coli band.
    # CAUTI band already covers the dominant E.coli rate.
    ("clabsi", "112283007"),
    # K.pneumoniae CLABSI: same rationale as E.coli — NHSN bands focus on
    # CAUTI-side enteric resistance.
    ("clabsi", "56415008"),
    # P.aeruginosa CLABSI: low incidence; resistance varies widely. CAUTI +
    # VAP bands focus on Pseudo where it dominates.
    ("clabsi", "52499004"),
    # K.pneumoniae CAUTI: covered indirectly via ESBL proxy on E.coli
    # ceftriaxone band; K.pneumoniae-specific NHSN band not published at
    # this granularity.
    ("cauti", "56415008"),
    # P.aeruginosa CAUTI: highly variable resistance; NHSN bands focus on
    # VAP Pseudo.
    ("cauti", "52499004"),
    # Proteus mirabilis CAUTI: secondary uropathogen; NHSN does not publish
    # a P.mirabilis-specific resistance band.
    ("cauti", "73457008"),
    # E.coli VAP: rare; not banded.
    ("vap", "112283007"),
    # K.pneumoniae VAP: covered indirectly by VAP MRSA + Pseudo bands as
    # the primary enforcement targets.
    ("vap", "56415008"),
    # P.aeruginosa VAP: high variability per facility; NHSN AR 2018-2020
    # focuses on MRSA proxy for VAP at population scale.
    ("vap", "52499004"),
    # Enterobacter VAP: secondary organism; not banded by NHSN AR
    # 2018-2020 at this granularity.
    ("vap", "14385002"),
    # Acinetobacter baumannii VAP: highly variable resistance pattern, not
    # banded by NHSN at the proxy level used here.
    ("vap", "91288006"),
    # Stenotrophomonas maltophilia VAP: ICU-only, low incidence; NHSN does
    # not publish a population band.
    ("vap", "113697002"),
})


# PR-90 lesson: validate canonical-constants references at import time.
def _validate_nhsn_resistance_bands() -> None:
    """Cross-check _NHSN_RESISTANCE_BANDS entries against canonical constants.

    Adv #7 F3: a typo in band["cohort"] / band["antibiotic"] would silently
    fail to match downstream cohorts at PR3b-3 wiring. Validate at import.

    PR3b-3 stage-1 adversarial finding I3 (2026-06-29): reverse-coverage
    check — every (hai_type, organism) in `hai_antibiogram.yaml` that has
    panel data SHOULD have at least one band covering it, OR be explicitly
    exempted in _NHSN_REVERSE_COVERAGE_EXEMPT below. Otherwise adding a
    new organism to the antibiogram silently grows the panel-eligible set
    + D1 per-organism cohort without any band firing → silent
    under-enforcement.

    PR3b-3 stage-2 adversarial finding (Agent 2 MED): also check exempt
    list freshness — every entry in _NHSN_REVERSE_COVERAGE_EXEMPT must
    correspond to an actual (hai_type, organism) pair in the antibiogram,
    so that dropping an organism from the YAML doesn't leave a stale
    exempt entry that nobody notices. Symmetric coverage with the
    forward-direction reverse-coverage check.
    """
    from clinosim.modules.hai import HAI_TYPES as _HAI_TYPES
    from clinosim.modules.hai import load_hai_antibiogram as _load_hai_antibiogram
    from clinosim.modules.hai import load_hai_organisms as _load_hai_organisms

    valid_hai_types = set(_HAI_TYPES)
    valid_antibiotics = set(ANTIBIOTIC_DRUGS.keys())
    raw = _load_hai_organisms()
    organisms_table = raw.get("hai_organisms", {})

    for band in _NHSN_RESISTANCE_BANDS:
        cohort = band["cohort"]
        if "/" not in cohort:
            raise ValueError(
                f"_NHSN_RESISTANCE_BANDS cohort {cohort!r} must be "
                f"<hai_type>/<organism_snomed>"
            )
        hai_type, organism = cohort.split("/", maxsplit=1)
        if hai_type not in valid_hai_types:
            raise ValueError(
                f"_NHSN_RESISTANCE_BANDS cohort hai_type {hai_type!r} "
                f"not in HAI_TYPES {sorted(valid_hai_types)}"
            )
        valid_organisms = {
            str(entry["snomed"]) for entry in organisms_table.get(hai_type, [])
        }
        if organism not in valid_organisms:
            raise ValueError(
                f"_NHSN_RESISTANCE_BANDS organism {organism!r} not in "
                f"hai_organisms.yaml[{hai_type}]"
            )
        abx_key = band["antibiotic"]
        if abx_key not in valid_antibiotics:
            raise ValueError(
                f"_NHSN_RESISTANCE_BANDS antibiotic {abx_key!r} not in "
                f"ANTIBIOTIC_DRUGS"
            )

    # Reverse-coverage (forward): every panel-bearing (hai_type, organism)
    # pair should have at least one band. Pairs we deliberately don't band
    # must be in the exempt set with a documented rationale.
    abg = _load_hai_antibiogram()
    banded_pairs = {tuple(b["cohort"].split("/", maxsplit=1)) for b in _NHSN_RESISTANCE_BANDS}
    antibiogram_pairs = {(ht, o) for ht, om in abg.items() for o in om.keys()}
    for pair in antibiogram_pairs:
        if pair in banded_pairs:
            continue
        if pair in _NHSN_REVERSE_COVERAGE_EXEMPT:
            continue
        hai_type, organism_snomed = pair
        raise ValueError(
            f"_NHSN_RESISTANCE_BANDS reverse-coverage gap: "
            f"hai_antibiogram.yaml has (hai_type={hai_type!r}, "
            f"organism={organism_snomed!r}) with a panel but no band "
            f"covers it. Either add a band or include in "
            f"_NHSN_REVERSE_COVERAGE_EXEMPT with rationale."
        )

    # Reverse-coverage (staleness, pr112-adv-2 Agent 2 MED): every exempt
    # entry must correspond to a present antibiogram pair, so dropping an
    # organism from the YAML doesn't leave a stale exempt.
    for pair in _NHSN_REVERSE_COVERAGE_EXEMPT:
        if pair not in antibiogram_pairs:
            hai_type, organism_snomed = pair
            raise ValueError(
                f"_NHSN_REVERSE_COVERAGE_EXEMPT contains stale entry "
                f"(hai_type={hai_type!r}, organism={organism_snomed!r}) "
                f"not present in hai_antibiogram.yaml. Remove the exempt "
                f"entry — it would silently mask a future re-introduction."
            )


def _validate_narrow_ladder_at_import() -> None:
    """PR3b-3: touch load_narrow_ladder() at module import to surface any
    3-way validation failure BEFORE audit harness runs. Otherwise an unknown
    hai_type / organism / drug_key would silently no-op the narrow chain
    (PR-90 教訓 / silent-no-op defense triplet)."""
    from clinosim.modules.antibiotic.engine import load_narrow_ladder
    load_narrow_ladder()


# Invoke ALL validators BEFORE register_audit_module so that any failure
# prevents stale spec from registering into _MODULES.
_validate_narrow_rate_bands()
_validate_nhsn_resistance_bands()
_validate_narrow_ladder_at_import()


# --- register module spec (validators above must have passed) ---
register_audit_module(
    ModuleAuditSpec(
        name="antibiotic",
        canonical_constants={
            "hai_type": HAI_TYPES,
            "drug_key": tuple(ANTIBIOTIC_DRUGS.keys()),
        },
        yaml_keys_to_validate={
            str(_HAI_EMPIRICAL_YAML): ("hai_empirical",),
        },
        clinical_acceptance={
            # Top-level metadata: full band list + empty-rate cap surfaced for
            # the clinical axis. R-rate gate + empty-rate gate are wired with
            # per-(hai_type, organism, antibiotic) filter + panel-eligible
            # denominator (PR3b-3 D1+D2 complete, 2026-06-29).
            "hai_resistance_bands": _NHSN_RESISTANCE_BANDS,
            "hai_empty_susceptibilities_max_rate": HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE,
            # PR3b-3: narrow rate per (hai_type, organism) cohort. Consumed by
            # audit clinical axis active enforcement (Task 6).
            "narrow_rate_bands": _NARROW_RATE_BANDS,
            "clabsi": {
                "icd10_code": "T80.211A",
                "expected_drugs": ("vancomycin", "piperacillin_tazobactam"),
                "expected_duration_days": 14,
                "min_mar_per_event": 14 * 2 + 14 * 4,  # Vanc q12h + Pip-Tazo q6h
                # PR3b-2: NHSN resistance-band metadata. R-rate checks wired
                # in clinical axis per-(hai_type, organism, antibiotic) cohort
                # (PR3b-3 D1 complete, 2026-06-29).
                "nhsn_r_bands": [
                    b for b in _NHSN_RESISTANCE_BANDS if b["cohort"].startswith("clabsi/")
                ],
            },
            "cauti": {
                "icd10_code": "T83.511A",
                "expected_drugs": ("ceftriaxone",),
                "expected_duration_days": 7,
                "min_mar_per_event": 7,
                "nhsn_r_bands": [
                    b for b in _NHSN_RESISTANCE_BANDS if b["cohort"].startswith("cauti/")
                ],
            },
            "vap": {
                "icd10_code": "J95.851",
                "expected_drugs": ("vancomycin", "piperacillin_tazobactam"),
                "expected_duration_days": 7,
                "min_mar_per_event": 7 * 2 + 7 * 4,
                "nhsn_r_bands": [
                    b for b in _NHSN_RESISTANCE_BANDS if b["cohort"].startswith("vap/")
                ],
            },
        },
        lift_firing_proof=_build_combined_proof,
    )
)
