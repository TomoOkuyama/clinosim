import re

import pytest

from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

REQUIRED_ANTIBIOTICS = {
    "vancomycin",
    "piperacillin_tazobactam",
    "ceftriaxone",
    "cefazolin",
    "cefepime",
    "meropenem",
    "ciprofloxacin",
    "trimethoprim_sulfamethoxazole",
}


@pytest.mark.unit
def test_lookup_covers_pr3b2_panel():
    missing = REQUIRED_ANTIBIOTICS - set(ANTIBIOTIC_LOINC_LOOKUP)
    assert not missing, f"PR3b-2 antibiotic panel missing keys: {missing}"


@pytest.mark.unit
def test_lookup_values_are_loinc_format():
    pattern = re.compile(r"^\d+-\d$")
    for key, loinc in ANTIBIOTIC_LOINC_LOOKUP.items():
        assert pattern.match(loinc), f"Invalid LOINC {loinc!r} for key {key!r}"


@pytest.mark.unit
def test_lookup_keys_are_subset_of_antibiotic_drugs():
    from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS

    # Every LOINC key should be a known drug (drug_key in PR3b-1 ANTIBIOTIC_DRUGS).
    unknown = set(ANTIBIOTIC_LOINC_LOOKUP) - set(ANTIBIOTIC_DRUGS)
    assert not unknown, f"LOINC keys not in ANTIBIOTIC_DRUGS: {unknown}"


@pytest.mark.unit
def test_cipro_loinc_is_18906_8_not_18879_7():
    """Adv #3 F2: Task 2 corrected ciprofloxacin 18879-7 (Cefepime) → 18906-8.
    Pin to prevent silent revert via YAML merge conflict."""
    assert ANTIBIOTIC_LOINC_LOOKUP["ciprofloxacin"] == "18906-8", (
        "ciprofloxacin LOINC reverted to wrong code "
        "(18879-7 = Cefepime [Susceptibility], not Cipro)"
    )


@pytest.mark.unit
def test_cefepime_loinc_is_18879_7():
    """Adv #3 F2: cefepime maps to its own LOINC, not Cipro's."""
    assert ANTIBIOTIC_LOINC_LOOKUP["cefepime"] == "18879-7"
