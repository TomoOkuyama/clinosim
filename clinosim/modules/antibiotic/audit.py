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
- structural_obs_codes: empty — susceptibility Observations use
  valueCodeableConcept (categorical S/I/R) rather than valueQuantity +
  referenceRange + interpretation; the structural axis numeric-coverage
  check does not apply to categorical observations. LOINC presence is
  verified end-to-end by the combined proof (silent_no_op axis). See
  _ABX_LOINCS for the full set. PR3b-3 will extend the clinical axis to
  run population-level R-rate checks against these LOINCs.
- clinical_acceptance: per-HAI-type expected drug set + duration +
  min_mar_per_event + NHSN resistance band metadata (nhsn_r_bands key).
  The clinical axis reads WBC_delta_p50 / CRP_delta_p50 keys only;
  resistance-band population-level checks deferred to PR3b-3.
- lift_firing_proof (_build_combined_proof): merged PR3b-1 + PR3b-2.
    PR3b-1 (regimen): CAUTI ceftriaxone — 8 equality_checks.
    PR3b-2 (antibiogram): CLABSI S. aureus susceptibility chain — 3 checks.
  All 11 equality_checks run in one silent_no_op axis pass.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS, ANTIBIOTIC_LOINC_LOOKUP
from clinosim.modules.antibiotic.enricher import enrich_antibiotic
from clinosim.modules.hai import HAI_TYPES
from clinosim.types.hai import HAIEvent

_HAI_EMPIRICAL_YAML = Path(__file__).parent / "reference_data" / "hai_empirical.yaml"

# PR3b-2: All antibiotic susceptibility LOINC codes emitted by _append_hai_culture.
# These codes appear as Observation.code.coding[].code in FHIR output for
# susceptibility Observations. Presence is verified by the combined proof
# (clabsi_saureus_susceptibility_count=6 + vancomycin_is_S checks) rather than
# structural_obs_codes because categorical observations have no referenceRange.
_ABX_LOINCS: frozenset[str] = frozenset(ANTIBIOTIC_LOINC_LOOKUP.values())

# TODO(PR3b-3): _NHSN_RESISTANCE_BANDS and HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE
# are surfaced in clinical_acceptance metadata for the audit clinical axis,
# but not actively enforced. PR3b-3 (narrow / de-escalation) will:
#   - extend clinical.py to compute observed R-rate per (hai_type, organism,
#     antibiotic) cohort and compare against expected_R_min/expected_R_max.
#   - extend clinical.py to compute empty-susceptibilities rate per HAI cohort
#     and compare against hai_empty_susceptibilities_max_rate.
# For now (PR3b-2), the bands are reported but not gating. The
# antibiogram_firing_proof in silent_no_op axis remains the load-bearing
# PR-90-class silent-no-op gate.
# Cohort string convention: "<hai_type>/<organism_snomed>" (exactly 2 components).
# Parse with: hai_type, org_snomed = band["cohort"].split("/", maxsplit=1)
# Adding a 3rd dimension (e.g., "clabsi/3092008/icu") requires changing to a
# structured type (dataclass or TypedDict). Do NOT use split("/") without maxsplit.
#
# PR3b-2: NHSN Antimicrobial Resistance Report 2018-2020 acceptance bands.
# Sources: CDC NHSN "Antimicrobial Resistance Patterns in Acute Care Hospitals" 2018-2020.
# Stored as top-level clinical_acceptance["hai_resistance_bands"] AND as per-HAI-type
# clinical_acceptance["*"]["nhsn_r_bands"] for convenience. The clinical axis
# reads WBC/CRP delta keys only; population-level R-rate checks deferred to PR3b-3
# (requires walking Observation.ndjson for susceptibility LOINCs).
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

# Empty-susceptibilities rate acceptance bound.
#
# Denominator: PANEL-ELIGIBLE HAI cultures only — those whose organism appears
# in hai_antibiogram.yaml. Excludes no-panel organisms:
#   - 78065002 (E. faecalis)  — different antibiotic panel (Phase 3c)
#   - 53326005 (C. albicans)  — fungal, separate antifungal panel
#
# Rationale: CLABSI has ~28% no-panel organism weight (0.15 C.albicans + 0.13
# E.faecalis); CAUTI has ~34%. Computing empty rate over ALL cultures would
# make the gate always-FAIL. The 5% threshold is 10× the measured rate at p=10k
# (0.5%) to give safety margin for small-p Bernoulli noise.
#
# TODO(PR3b-3): wire this in clinical.py with the panel-eligible filter.
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


# TODO(PR3b-3): Replace single lift_firing_proof with lift_firing_proofs: list[Callable]
# in ModuleAuditSpec so each sub-proof runs independently. Currently the combined
# proof's try/except below isolates exceptions but conflates results in a single
# equality_checks list (per-finding failures already independent at the
# silent_no_op._check_proof level — only factory-level exceptions need isolation).
def _build_combined_proof() -> dict[str, Any]:
    """Combined proof: PR3b-1 antibiotic regimen + PR3b-2 antibiogram S/I/R chain.

    Merges equality_checks from both sub-proofs so the silent_no_op axis
    verifies the full PR3b-1 + PR3b-2 pipeline in a single pass.

    Produces 11 equality_checks total:
      8 from _build_synthetic_proof  — CAUTI ceftriaxone regimen
      3 from _antibiogram_firing_proof_checks — CLABSI S. aureus susceptibility
    """
    regimen_result = _build_synthetic_proof()
    try:
        antibiogram_checks = _antibiogram_firing_proof_checks()
    except Exception as e:
        antibiogram_checks = [
            ("antibiogram_firing_proof_raised", f"{type(e).__name__}: {e}", "no exception"),
        ]
    return {
        "equality_checks": (
            list(regimen_result.get("equality_checks") or [])
            + list(antibiogram_checks)
        ),
    }


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
            # the clinical axis. PR3b-3 will add active enforcement (R-rate gate
            # + empty-rate gate). Keys verified by audit registry assertions.
            "hai_resistance_bands": _NHSN_RESISTANCE_BANDS,
            "hai_empty_susceptibilities_max_rate": HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE,
            "clabsi": {
                "icd10_code": "T80.211A",
                "expected_drugs": ("vancomycin", "piperacillin_tazobactam"),
                "expected_duration_days": 14,
                "min_mar_per_event": 14 * 2 + 14 * 4,  # Vanc q12h + Pip-Tazo q6h
                # PR3b-2: NHSN resistance-band metadata (clinical axis reads
                # WBC/CRP only; R-rate checks deferred to PR3b-3).
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


# PR-90 lesson: validate canonical-constants references at import time.
def _validate_nhsn_resistance_bands() -> None:
    """Cross-check _NHSN_RESISTANCE_BANDS entries against canonical constants.

    Adv #7 F3: a typo in band["cohort"] / band["antibiotic"] would silently
    fail to match downstream cohorts at PR3b-3 wiring. Validate at import.
    """
    from clinosim.modules.hai import HAI_TYPES as _HAI_TYPES
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


_validate_nhsn_resistance_bands()
