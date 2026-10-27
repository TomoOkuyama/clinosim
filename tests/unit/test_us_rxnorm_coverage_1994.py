"""Issue #1994: raise US MedicationRequest RxNorm coverage from 98.98 % to 100 %.

Session-aggregate-QA on the US ``s=342 p=10000`` cohort found 4,719 of
462,333 MedicationRequests (1.02 %) emitting without an RxNorm coding —
below the 100 % strict-at-master invariant the locale axis gates.

Root cause (per bucketed analysis of the ``medicationCodeableConcept.text``
on missing rows):

* route-qualified aliases (``"IV normal saline"``, ``"Nebulized salbutamol
  2.5mg"``) that the resolver's prefix+suffix match could not resolve
  against the bare-ingredient map;
* combo-product slash-form names (``"Acetaminophen/codeine"``,
  ``"Calcium/Vitamin D"``) whose combo CUIs already live in
  ``rxnorm.yaml`` but were not keyed under the sim's slash form;
* case variants (``"Amoxicillin/clavulanate"`` vs the registered
  ``"Amoxicillin/Clavulanate"``, lowercase ``"Hypertonic saline"`` vs
  ``"Hypertonic Saline"``);
* brand-only names (``"Buscopan"``) not keyed under their US alias;
* class terms (``"ICS/LABA inhaler"``, ``"Broad spectrum antibiotic"``,
  ``"Crystalloid"``) mapped to a representative drug.

The ``"Packed_RBC"`` entry (1 of 4,719) is a blood product with no RxNorm
drug concept; it stays emitted text-only (CIF-to-FHIR no-drop) and is out
of scope for this mapping closure.

This test pins the specific drug_name → RxCUI mapping for the 1,994
coverage closure. Every RxCUI below reuses an entry already registered
in ``clinosim/codes/data/rxnorm.yaml`` (NLM-verified at registration).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_US_MAPPING = _REPO_ROOT / "clinosim" / "locale" / "us" / "code_mapping_drug.yaml"
_RXNORM_DATA = _REPO_ROOT / "clinosim" / "codes" / "data" / "rxnorm.yaml"


# (sim_display_name → representative RxCUI). The sim display name is
# whatever ``MedicationRequest.medicationCodeableConcept.text`` carried
# on the uncoded rows of the US p=10000 cohort.
_COVERAGE_1994 = {
    # IV normal saline family — RxCUI 313002 (Sodium Chloride 9 MG/ML
    # Injectable Solution, i.e. 0.9 % NS). Same code the ``NS`` alias
    # already uses.
    "IV normal saline": "313002",
    "IV normal saline 500mL": "313002",
    "IV normal saline 1000mL": "313002",
    "IV normal saline 1L": "313002",
    # Nebulized bronchodilator — RxCUI 435 (Albuterol IN; sim uses
    # ``salbutamol`` INN which is the same ingredient as albuterol USAN).
    "Nebulized salbutamol": "435",
    "Nebulized salbutamol 2.5mg": "435",
    "Nebulized Salbutamol": "435",
    # Amoxicillin/clavulanate — lowercase-c and dose-qualified forms used
    # by the animal_bite yaml; the canonical mixed-case entry already
    # resolves ``"Amoxicillin/Clavulanate"`` alone.
    "Amoxicillin/clavulanate": "19711",
    "Amoxicillin/clavulanate 500/125mg": "19711",
    "Amoxicillin/clavulanate 875/125mg": "19711",
    # Buscopan — JP brand name for butylscopolamine; used by the
    # abdominal_pain_nonspecific disease yaml which is shared JP/US.
    "Buscopan": "1851",
    "Buscopan 10mg": "1851",
    "Buscopan 20mg": "1851",
    # Combo products — ingredient-based combo CUIs already in rxnorm.yaml.
    "Acetaminophen/codeine": "817579",
    "Calcium/Vitamin D": "608343",
    # Oxycodone/Acetaminophen — RxNorm's acetaminophen+oxycodone combos
    # are SCDs (dose-specific tablets), not an IN/MIN. Point to the
    # opioid ingredient (7804 Oxycodone) as the clinically distinguishing
    # component — same convention JP's code_mapping_drug.yaml uses for
    # the Acetaminophen/codeine representative (ingredient-only pin).
    "Oxycodone/Acetaminophen": "7804",
    # Hypertonic saline — rxnorm.yaml 2587736 covers Sodium Chloride
    # 23.4 %, which both the 23.4 % and the 3 % sim variants resolve to
    # on the JP side (per that locale's existing pin).
    "Hypertonic Saline": "2587736",
    "Hypertonic Saline 23.4%": "2587736",
    "Hypertonic saline": "2587736",
    "Hypertonic saline 3%": "2587736",
    # Calcium gluconate — ingredient entry already in rxnorm.yaml under 1908.
    "Calcium gluconate": "1908",
    # Class terms mapped to representative drug:
    # - ICS/LABA inhaler → Fluticasone/Salmeterol combo (108761);
    # - Broad spectrum antibiotic → Piperacillin/Tazobactam (74169, the
    #   workhorse empiric broad-spectrum IV antibiotic);
    # - Crystalloid → NS (313002), matching the convention noted in the
    #   JP catalog's existing crystalloid comment.
    "ICS/LABA inhaler": "108761",
    "Broad spectrum antibiotic": "74169",
    "Crystalloid": "313002",
}


def _load_us_mapping() -> dict[str, str]:
    with _US_MAPPING.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_rxnorm_codes() -> dict[str, dict]:
    with _RXNORM_DATA.open(encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("codes", {}) or {}


def test_coverage_1994_mapping_entries_present() -> None:
    """Every missing-coverage display must have a key in
    ``code_mapping_drug.yaml`` so the FHIR resolver's prefix match hits
    it and emits an RxNorm ``coding[]`` block."""
    mapping = _load_us_mapping()
    missing = {name: expected for name, expected in _COVERAGE_1994.items() if name not in mapping}
    assert not missing, f"US drug mapping missing #1994 coverage entries: {missing}"


def test_coverage_1994_mapping_values_match_expected() -> None:
    """Every key must point at the expected RxCUI (fabrication guard)."""
    mapping = _load_us_mapping()
    wrong = {
        name: (mapping.get(name), expected)
        for name, expected in _COVERAGE_1994.items()
        if name in mapping and mapping[name] != expected
    }
    assert not wrong, f"US drug mapping value mismatch for #1994: {wrong}"


def test_coverage_1994_rxcuis_registered_in_rxnorm_yaml() -> None:
    """Every RxCUI used must have a display entry in rxnorm.yaml so the
    FHIR builder can populate ``coding.display``."""
    rxnorm = _load_rxnorm_codes()
    missing = sorted({cui for cui in _COVERAGE_1994.values() if cui not in rxnorm})
    assert not missing, f"rxnorm.yaml missing display entries for #1994 RxCUIs: {missing}"
