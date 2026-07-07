"""FHIR builders must gate country on the canonical case-insensitive helpers
(``is_us`` / ``is_jp``), not a raw ``country == "US"`` / ``country != "US"``
comparison.

FP-UNIFY-4 (2026-07-06 FHIR completeness registry): production does not
normalize ``--country``, so a lowercase ``"us"`` reached these builders and the
raw comparison mis-routed it to the JP path (``"us" != "US"`` is True). Sibling
to FP-UNIFY-1 (test_fhir_hai_code_system.py), which fixed the same class in
_fhir_hai via ``system_key_for``.
"""

import pytest

from clinosim.modules.output._fhir_common import _map_diagnosis_code
from clinosim.modules.output._fhir_localization import _localize_drug_name

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("country", ["US", "us"])
def test_diagnosis_mapping_uses_us_leaf_any_case(country):
    # US maps the WHO category E10 to a billable ICD-10-CM leaf. A lowercase
    # "us" must not fall through to the JP identity mapping.
    assert _map_diagnosis_code("E10", country) == "E10.9"


@pytest.mark.parametrize("country", ["JP", "jp"])
def test_diagnosis_mapping_is_identity_for_jp_any_case(country):
    # JP keeps the WHO category as-is.
    assert _map_diagnosis_code("E10", country) == "E10"


@pytest.mark.parametrize("country", ["US", "us"])
def test_drug_name_stays_english_for_us_any_case(country):
    # US output must be 100% English — a lowercase "us" must not JP-localize.
    assert _localize_drug_name("aspirin", country) == "aspirin"


@pytest.mark.parametrize("country", ["JP", "jp"])
def test_drug_name_localizes_for_jp_any_case(country):
    assert _localize_drug_name("aspirin", country) == "アスピリン"
