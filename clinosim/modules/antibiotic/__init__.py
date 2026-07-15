"""modules/antibiotic — HAI empirical antibiotic regimens (PR3b-1).

Single source of truth for antibiotic drug names. The hai_empirical.yaml
loader validates all drug_key strings against this dict at import time
to surface case-mismatch / typo class of bugs (PR-90 教訓).

ANTIBIOTIC_DRUGS keys are lowercase snake_case (e.g. "vancomycin",
"piperacillin_tazobactam") matching the microbiology.yaml antibiotics
section and the ANTIBIOTIC_LOINC_LOOKUP. The "name" value holds the
display name used for Order.display_name and MedicationAdministration.drug_name.
"""

from clinosim.modules.observation.microbiology import antibiotic_loinc_lookup

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

# antibiotic_key -> LOINC, sourced from the cached + validated microbiology.yaml
# loader in the observation module (single source of truth; avoids re-parsing
# the same YAML with a hardcoded cross-module path).
ANTIBIOTIC_LOINC_LOOKUP: dict[str, str] = antibiotic_loinc_lookup()
