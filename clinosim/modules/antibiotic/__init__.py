"""modules/antibiotic — HAI empirical antibiotic regimens (PR3b-1).

Single source of truth for antibiotic drug names. The hai_empirical.yaml
loader validates all drug_key strings against this dict at import time
to surface case-mismatch / typo class of bugs (PR-90 教訓).

ANTIBIOTIC_DRUGS keys are lowercase snake_case (e.g. "vancomycin",
"piperacillin_tazobactam") matching the microbiology.yaml antibiotics
section and the ANTIBIOTIC_LOINC_LOOKUP. The "name" value holds the
display name used for Order.display_name and MedicationAdministration.drug_name.
"""
from functools import lru_cache
from pathlib import Path

import yaml

ANTIBIOTIC_DRUGS: dict[str, dict[str, str]] = {
    "vancomycin": {"name": "Vancomycin"},
    "piperacillin_tazobactam": {"name": "Piperacillin/Tazobactam"},
    "ceftriaxone": {"name": "Ceftriaxone"},
    "ampicillin": {"name": "Ampicillin"},
    "cefazolin": {"name": "Cefazolin"},
    "gentamicin": {"name": "Gentamicin"},
    "meropenem": {"name": "Meropenem"},
    "ciprofloxacin": {"name": "Ciprofloxacin"},
    "trimethoprim_sulfamethoxazole": {"name": "Trimethoprim/Sulfamethoxazole"},
    "cefepime": {"name": "Cefepime"},
}

_MICRO_REF = (
    Path(__file__).parent.parent
    / "observation"
    / "reference_data"
    / "microbiology.yaml"
)


@lru_cache(maxsize=1)
def _load_antibiotic_loinc_lookup() -> dict[str, str]:
    """Load antibiotic_key -> LOINC from microbiology.yaml (single source of truth)."""
    with open(_MICRO_REF) as f:
        data = yaml.safe_load(f) or {}
    table = data.get("antibiotics") or {}
    return {str(k): str(v) for k, v in table.items()}


ANTIBIOTIC_LOINC_LOOKUP: dict[str, str] = _load_antibiotic_loinc_lookup()
