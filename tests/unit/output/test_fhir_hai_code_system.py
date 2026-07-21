"""HAI Condition ICD code-system selection must go through the canonical
``system_key_for("diagnosis", country)`` single source of truth, not a
case-sensitive ``country == "US"`` inline branch.

FP-UNIFY-1 (2026-07-06 FHIR completeness chain 1): the inline branch picked
the wrong ICD code system (icd-10 instead of icd-10-cm) for a lowercase
``"us"`` country, because ``"us" == "US"`` is False. The canonical helper is
case-insensitive, matching every sibling diagnosis builder.
"""

import pytest

from clinosim.codes import get_system_uri
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.modules.output._fhir_hai import _build_hai_conditions

pytestmark = pytest.mark.unit


def _ctx(country: str) -> BundleContext:
    record = {
        "extensions": {
            "hai": [
                {
                    "icd10_code": "T80.211A",
                    "snomed_code": "434656007",
                    "hai_id": "hai-1",
                    "encounter_id": "E1",
                    "onset_date": "2026-01-05",
                }
            ],
        },
    }
    return BundleContext(
        record=record,
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="P1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="E1",
        patient_sex="M",
    )


def _icd_system(resources: list[dict]) -> str:
    cond = resources[0]
    # ICD coding is the primary (first) coding entry.
    return cond["code"]["coding"][0]["system"]


@pytest.mark.parametrize("country", ["US", "us"])
def test_hai_condition_uses_icd10cm_system_for_us_any_case(country):
    resources = _build_hai_conditions(_ctx(country))
    assert resources, "expected one HAI Condition"
    assert _icd_system(resources) == get_system_uri("icd-10-cm")


@pytest.mark.parametrize("country", ["JP", "jp"])
def test_hai_condition_uses_mhlw_icd10_system_for_jp_any_case(country):
    """Issue #350 (session 63): JP HAI Condition now emits the MHLW canonical
    ICD-10 URI (`http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full`),
    matching the JP Core `jp-condition-diagnosis` required binding. Previously
    this test pinned the WHO URI, which was a binding violation on JP output."""
    resources = _build_hai_conditions(_ctx(country))
    assert resources, "expected one HAI Condition"
    assert _icd_system(resources) == get_system_uri("icd-10-mhlw")
