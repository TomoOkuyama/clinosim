"""Chemo drug catalog expansion for #1280 sub-C.

Registers Gemcitabine / Irinotecan / Nab-paclitaxel / Temozolomide /
BCG so the follow-up regimen-wiring PRs (C22 hepatocellular /
C25 pancreatic / C67 bladder / C71 glioma) can dispatch to real
`chemo_regimens.yaml::by_cancer` entries without emitting text-only
`MedicationRequest.medicationCodeableConcept`.

All RXCUIs verified 2026-09-12 via `tx.fhir.org` `$lookup` against
`http://www.nlm.nih.gov/research/umls/rxnorm`.

JP YJ 7-digit class-representative codes per MHLW 薬効分類:
- 4224 代謝拮抗剤        (Gemcitabine)
- 4240 その他の抗悪性腫瘍剤 (Irinotecan)
- 4291 抗悪性腫瘍剤       (Nab-paclitaxel, Temozolomide)
- 6323 免疫療法用製剤     (BCG intravesical)
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup
from clinosim.locale.loader import load_code_mapping

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
        ("BCG", "1344", "BCG"),
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
    "drug, yj_code, ja_substr",
    [
        ("Gemcitabine", "4224400", "ゲムシタビン"),
        ("Irinotecan", "4240401", "イリノテカン"),
        ("Nab-paclitaxel", "4291423", "パクリタキセル"),
        ("Temozolomide", "4291023", "テモゾロミド"),
        ("BCG", "6323400", "BCG"),
    ],
)
def test_jp_chemo_yj_registration_1280(drug, yj_code, ja_substr):
    jp_map = load_code_mapping("drug", "JP")
    assert jp_map.get(drug) == yj_code, f"JP drug map missing {drug} → {yj_code}"
    # Lookup via `yj` key with hot7 sibling fallback (Issue #415).
    ja = lookup("yj", yj_code, "ja")
    assert ja_substr in ja, f"JP display for {drug} ({yj_code}) missing substring {ja_substr!r}: got {ja!r}"


def test_bcg_is_registered_as_immunotherapy_shape():
    """BCG lands under RxNorm CUI 1344 (BCG Vaccine) — the same organism
    used for intravesical bladder immunotherapy. Guard against a future
    edit that would swap it to a different CUI (e.g. a specific SKU)."""
    us_map = load_code_mapping("drug", "US")
    assert us_map.get("BCG") == "1344"
    en = lookup("rxnorm", "1344", "en")
    assert "BCG" in en
