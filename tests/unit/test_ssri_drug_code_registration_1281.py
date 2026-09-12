"""Follow-up to #1281: SSRI drug code registration.

The chronic-medications SSRI block wired for F32 / F33 / F41.1 in #1281
used `Sertraline` / `Escitalopram` / `Fluoxetine` / `Paroxetine` /
`Citalopram` as internal drug names. Before this follow-up none of
those were in `codes/data/rxnorm.yaml` or the
`locale/{us,jp}/code_mapping_drug.yaml` files, so the FHIR emit path
rendered `MedicationRequest.medicationCodeableConcept.text` only.
This registration lets the standard drug-code lookup populate
`.coding` for the entire cohort.

RxNorm codes verified 2026-09-12 via `tx.fhir.org` `$lookup` against
`http://www.nlm.nih.gov/research/umls/rxnorm` (TTY=IN concepts).
JP YJ codes: class 1179 (精神神経用剤 / SSRI・SNRI). Fluoxetine and
Citalopram are omitted from the JP mapping — neither is
PMDA-approved in Japan; a JP patient whose F32 SSRI draw lands on
either drug falls back to text-only coding (unchanged from
pre-registration behaviour for those particular draws).
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup
from clinosim.locale.loader import load_code_mapping

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "drug, rxcui, display_en",
    [
        ("Sertraline", "36437", "sertraline"),
        ("Escitalopram", "321988", "escitalopram"),
        ("Fluoxetine", "4493", "fluoxetine"),
        ("Paroxetine", "32937", "paroxetine"),
        ("Citalopram", "2556", "citalopram"),
    ],
)
def test_us_rxnorm_registration(drug, rxcui, display_en):
    us_map = load_code_mapping("drug", "US")
    assert us_map.get(drug) == rxcui, f"US drug map missing {drug} → {rxcui}"
    # RxNorm CodeSystem yaml has the display for downstream FHIR emit
    assert lookup("rxnorm", rxcui, "en").lower() == display_en


@pytest.mark.parametrize(
    "drug, yj_code",
    [
        ("Sertraline", "1179044"),
        ("Escitalopram", "1179052"),
        ("Paroxetine", "1179040"),
    ],
)
def test_jp_yj_registration_pmda_approved(drug, yj_code):
    jp_map = load_code_mapping("drug", "JP")
    assert jp_map.get(drug) == yj_code, f"JP drug map missing {drug} → {yj_code}"
    # Available via `yj` key with hot7 sibling fallback (Issue #415).
    assert lookup("yj", yj_code, "ja"), f"JP display missing for {yj_code}"


@pytest.mark.parametrize("drug", ["Fluoxetine", "Citalopram"])
def test_jp_omits_non_pmda_approved(drug):
    """Fluoxetine / Citalopram are not PMDA-approved in Japan; a
    JP-side lookup returns nothing for them (the FHIR emit path
    then falls back to text-only coding, same as any unregistered
    chronic med)."""
    jp_map = load_code_mapping("drug", "JP")
    assert drug not in jp_map, (
        f"{drug} must NOT be in JP drug mapping — not PMDA-approved. If PMDA "
        f"approval status changes, update this test + the mapping in the same PR."
    )
