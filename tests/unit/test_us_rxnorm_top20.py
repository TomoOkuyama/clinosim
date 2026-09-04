"""C2 / Issue #1088: US MedicationRequest/Administration text-only fix.

Session-100 review measured 10.98 % of US MAs emitted with
``medicationCodeableConcept.text`` only (no ``coding[]``) — 7,062 out of
64,317 on a p=10k s=1000 cohort. The top-frequency missing drugs are
core hospital medications: Regular insulin (1,333), NS (1,331),
Prednisolone (1,045), KCl (574), Insulin glargine (479), Dobutamine
(324), etc.

Root cause: ``code_mapping_drug.yaml`` had no entries for these drug
names. This test pins the mapping for the top-19 (Crystalloid is
excluded because it is a generic term with no single canonical RxCUI).
"""

from __future__ import annotations

from pathlib import Path

import yaml

_LOCALE = Path(__file__).resolve().parents[2] / "clinosim" / "locale"
_DATA = Path(__file__).resolve().parents[2] / "clinosim" / "codes" / "data"


# (sim-string → RxCUI) — every RxCUI here was verified against the NLM
# RxNav API (rxnav.nlm.nih.gov/REST/rxcui/<cui>/property.json?propName=RxNorm%20Name)
# at PR-authoring time. If the name mismatches on that endpoint the
# mapping is a fabrication and must be replaced, not "explained".
_TOP20_EXPECTED = {
    "Regular insulin": "253182",
    "NS": "313002",
    "Prednisolone": "8638",
    "KCl": "8591",
    "Insulin glargine": "274783",
    "Dobutamine": "3616",
    "Trastuzumab": "224905",
    "Capecitabine": "194000",
    "Oxaliplatin": "32592",
    "Ticagrelor": "1116632",
    "Leucovorin": "6313",
    "5-FU": "4492",
    "Omeprazole": "7646",
    "Cefmetazole": "2182",
    "Leuprorelin": "42375",
    "Mannitol": "6628",
    "Lactated Ringer": "847630",
    "Fentanyl": "4337",
    "Osimertinib": "1721560",
}


def test_top19_drugs_present_in_us_code_mapping_drug() -> None:
    """Every drug in the top-frequency missing set must resolve to a code."""
    us = yaml.safe_load((_LOCALE / "us" / "code_mapping_drug.yaml").read_text(encoding="utf-8"))
    missing = {name: expected for name, expected in _TOP20_EXPECTED.items() if name not in us}
    assert not missing, f"US drug mapping missing top-frequency entries: {missing}"


def test_top19_drugs_map_to_verified_rxcui() -> None:
    """Values must match the NLM-verified RxCUIs, not fabrications."""
    us = yaml.safe_load((_LOCALE / "us" / "code_mapping_drug.yaml").read_text(encoding="utf-8"))
    wrong = {
        name: (us.get(name), expected)
        for name, expected in _TOP20_EXPECTED.items()
        if name in us and us[name] != expected
    }
    assert not wrong, f"US drug mapping value differs from NLM-verified RxCUI: {wrong}"


def test_top19_rxcuis_present_in_rxnorm_yaml() -> None:
    """Every RxCUI added by this issue must have a display entry so the
    FHIR emit path can produce a human-readable ``coding.display``."""
    rxnorm = yaml.safe_load((_DATA / "rxnorm.yaml").read_text(encoding="utf-8"))["codes"]
    missing = [cui for cui in _TOP20_EXPECTED.values() if cui not in rxnorm]
    assert not missing, f"rxnorm.yaml missing display entries for RxCUIs: {missing}"


def test_fentanyl_display_is_fentanyl_not_ceftriaxone() -> None:
    """rxnorm.yaml pre-C2 mislabeled 4337 as "Ceftriaxone" but 4337 is the
    NLM-authoritative RxCUI for **fentanyl** — Ceftriaxone is 2193 (which
    ``code_mapping_drug.yaml`` correctly uses). The mislabel was invisible
    only because nothing mapped to 4337 before C2 added Fentanyl.
    """
    rxnorm = yaml.safe_load((_DATA / "rxnorm.yaml").read_text(encoding="utf-8"))["codes"]
    entry_4337 = rxnorm.get("4337", {})
    en = (entry_4337.get("en") or "").lower()
    assert "fentanyl" in en, f"rxnorm.yaml['4337'].en should be Fentanyl (NLM-verified); got {en!r}"
    assert "ceftriaxone" not in en, "rxnorm.yaml['4337'] must not carry the pre-C2 Ceftriaxone mislabel"
