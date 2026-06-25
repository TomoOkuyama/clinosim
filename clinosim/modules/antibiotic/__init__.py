"""modules/antibiotic — HAI empirical antibiotic regimens (PR3b-1).

Single source of truth for antibiotic drug names. The hai_empirical.yaml
loader validates all drug_key strings against this tuple at import time
to surface case-mismatch / typo class of bugs (PR-90 教訓).
"""
ANTIBIOTIC_DRUGS: tuple[str, ...] = (
    "Vancomycin",
    "Piperacillin/Tazobactam",
    "Ceftriaxone",
)
