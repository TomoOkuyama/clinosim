"""Chemo drug catalog expansion for #1280 sub-C.

Registers Gemcitabine / Irinotecan / Nab-paclitaxel / Temozolomide /
BCG so the follow-up regimen-wiring PRs (C22 hepatocellular /
C25 pancreatic / C67 bladder / C71 glioma) can dispatch to real
`chemo_regimens.yaml::by_cancer` entries without emitting text-only
`MedicationRequest.medicationCodeableConcept`.

All RXCUIs verified 2026-09-12 via `tx.fhir.org` `$lookup` against
`http://www.nlm.nih.gov/research/umls/rxnorm`.

JP codes are full YJ products from the drug catalog, listed in the MHLW YJ
master (Issue #2347).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.codes import lookup
from clinosim.codes.drugs import jp_drug_code
from clinosim.locale.loader import load_code_mapping

_MHLW = json.loads(
    (Path(__file__).resolve().parents[2] / "clinosim/codes/authoritative/yj_mhlw_snapshot.json").read_text(
        encoding="utf-8"
    )
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "drug, rxcui, display_substr",
    [
        ("Gemcitabine", "12574", "gemcitabine"),
        ("Irinotecan", "51499", "irinotecan"),
        # RxNorm publishes as "paclitaxel protein-bound"; the internal
        # sim name is "Nab-paclitaxel" (clinical alias).
        ("Nab-paclitaxel", "486610", "paclitaxel"),
        ("Temozolomide", "37776", "temozolomide"),
        ("BCG", "221050", "BCG"),  # Issue #2150: 1344 is not current
    ],
)
def test_us_chemo_rxnorm_registration_1280(drug, rxcui, display_substr):
    us_map = load_code_mapping("drug", "US")
    assert us_map.get(drug) == rxcui, f"US drug map missing {drug} → {rxcui}"
    en = lookup("rxnorm", rxcui, "en")
    assert display_substr.lower() in en.lower(), (
        f"RxNorm {rxcui} display {en!r} missing expected substring {display_substr!r}"
    )


@pytest.mark.parametrize(
    "drug, route, yj_code, ingredient",
    [
        ("Gemcitabine", "IV", "4224403A2022", "ゲムシタビン"),
        ("Irinotecan", "IV", "4240404A1091", "イリノテカン"),
        ("Nab-paclitaxel", "IV", "4240409D1023", "パクリタキセル"),
        ("Temozolomide", "PO", "4219004M1024", "テモゾロミド"),
        ("BCG", "intravesical", "6391700X4026", "ＢＣＧ"),
    ],
)
def test_jp_chemo_yj_registration_1280(drug, route, yj_code, ingredient):
    # Issue #2347: a full YJ product code per route, whose MHLW ingredient is
    # the drug (the former 7-digit values were not listed codes).
    assert jp_drug_code(drug, route) == yj_code
    assert ingredient in _MHLW["codes"][yj_code]["ingredient"]


def test_bcg_is_registered_as_immunotherapy_shape():
    """BCG lands under RxNorm CUI 221050 (BCG, live, Tice strain — the US
    intravesical bladder immunotherapy product). Issue #2150: the former
    1344 (BCG Vaccine) is not current in RxNorm."""
    us_map = load_code_mapping("drug", "US")
    assert us_map.get("BCG") == "221050"
    en = lookup("rxnorm", "221050", "en")
    assert "BCG" in en
