"""Antibiotic audit — second per-Module AD-60 plug-in.

Mirrors modules/hai/audit.py but the lift_firing_proof exercises the
real enricher path (enrich_antibiotic) against a synthetic CAUTI
HAIEvent, asserting:
  - extensions["antibiotic"] has exactly 1 regimen
  - regimen.drug_key == "Ceftriaxone", duration_days == 7
  - record.orders has 1 MEDICATION order with display_name "Ceftriaxone"
  - record.medication_administrations has 7 MAR entries (q24h × 7d)

This is the load-bearing PR-90 silent-no-op gate for PR3b-1.

Registered checks:
- canonical_constants: HAI_TYPES + ANTIBIOTIC_DRUGS cross-validate
  against hai_empirical.yaml at import time (via load_hai_empirical).
- structural_obs_codes: empty for PR3b-1 (no Observations emitted).
  PR3b-2 will add susceptibility LOINC codes here.
- clinical_acceptance: per-HAI-type expected drug set + duration +
  min_mar_per_event.
- lift_firing_proof: see _build_synthetic_proof below.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS
from clinosim.modules.antibiotic.enricher import enrich_antibiotic
from clinosim.modules.hai import HAI_TYPES
from clinosim.types.hai import HAIEvent

_HAI_EMPIRICAL_YAML = Path(__file__).parent / "reference_data" / "hai_empirical.yaml"


def _build_synthetic_proof():
    """Drive enrich_antibiotic against a synthetic CAUTI record.

    Returns a dict the silent_no_op axis asserts against. PR-90 教訓:
    canonical strings + actual enricher invocation, NOT a fixture
    bypass.
    """
    ev = HAIEvent(
        hai_id="h-cauti-proof",
        encounter_id="enc-proof",
        hai_type=HAI_TYPES[1],   # "cauti" — canonical, NEVER literal string
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
    med_orders = [
        o for o in rec.orders
        if getattr(o.order_type, "value", "") == "medication"
    ]
    mar = rec.medication_administrations
    return {
        "ext_antibiotic_count": len(abx),
        "ext_antibiotic_drug": abx[0].drug_key if abx else None,
        "ext_antibiotic_duration_days": abx[0].duration_days if abx else None,
        "orders_medication_count": len(med_orders),
        "mar_count": len(mar),
        "mar_drug": mar[0].drug_name if mar else None,
        "mar_first_dt": mar[0].scheduled_datetime if mar else None,
        "mar_last_dt": mar[-1].scheduled_datetime if mar else None,
        "expected": {
            "ext_antibiotic_count": 1,
            "ext_antibiotic_drug": "ceftriaxone",  # lowercase snake_case drug_key (PR3b-2 refactor)
            "ext_antibiotic_duration_days": 7,
            "orders_medication_count": 1,
            "mar_count": 7,
            "mar_drug": "Ceftriaxone",  # display name from ANTIBIOTIC_DRUGS["ceftriaxone"]["name"]
            "mar_first_dt": datetime(2026, 1, 10, 8),
            "mar_last_dt": datetime(2026, 1, 16, 8),
        },
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
            "clabsi": {
                "icd10_code": "T80.211A",
                "expected_drugs": ("vancomycin", "piperacillin_tazobactam"),
                "expected_duration_days": 14,
                "min_mar_per_event": 14 * 2 + 14 * 4,  # Vanc q12h + Pip-Tazo q6h
            },
            "cauti": {
                "icd10_code": "T83.511A",
                "expected_drugs": ("ceftriaxone",),
                "expected_duration_days": 7,
                "min_mar_per_event": 7,
            },
            "vap": {
                "icd10_code": "J95.851",
                "expected_drugs": ("vancomycin", "piperacillin_tazobactam"),
                "expected_duration_days": 7,
                "min_mar_per_event": 7 * 2 + 7 * 4,
            },
        },
        lift_firing_proof=_build_synthetic_proof,
    )
)
