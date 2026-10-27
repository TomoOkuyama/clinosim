"""Issue #2003 — FHIR Observation.category must draw from the canonical HL7
Observation Category CodeSystem (lower-case codes only).

The canonical value-set is
``http://terminology.hl7.org/CodeSystem/observation-category`` with the
member codes {``vital-signs``, ``survey``, ``laboratory``,
``social-history``, ``imaging``, ``procedure``, ``therapy``, ``activity``,
``exam``}. Prior to the fix the blood-type ABO/RhD Observation builder
emitted ``category.coding.code = "LAB"`` under the v2-0074 Diagnostic
Service Section system — a mis-selection of category CodeSystem that
produced 19,664 non-canonical ``LAB`` codes across the US p=10,000 QA
cohort.

These tests pin the canonical shape so a future regression (another
code path emitting ``"LAB"``) is caught at the unit layer.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.blood_type import _bb_blood_type

pytestmark = pytest.mark.unit


CANONICAL_OBSERVATION_CATEGORY_CODES = frozenset(
    {
        "vital-signs",
        "survey",
        "laboratory",
        "social-history",
        "imaging",
        "procedure",
        "therapy",
        "activity",
        "exam",
    }
)

CANONICAL_OBSERVATION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"


def _ctx(patient_data: dict, country: str = "US"):
    return SimpleNamespace(
        record={"encounters": []},
        country=country,
        patient_data=patient_data,
        patient_id="POP-000001",
        roster_map={},
        hospital_config={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="enc1",
        patient_sex="",
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_blood_type_observation_category_uses_canonical_system(country: str):
    """blood-type ABO + RhD Observations must emit the canonical
    HL7 Observation Category CodeSystem (not the v2-0074 Diagnostic
    Service Section system)."""
    ctx = _ctx({"blood_type": "A", "rh_factor": "+"}, country=country)
    resources = _bb_blood_type(ctx)
    assert resources, "blood-type builder should emit at least one Observation"
    for r in resources:
        for cat in r["category"]:
            for coding in cat["coding"]:
                assert coding["system"] == CANONICAL_OBSERVATION_CATEGORY_SYSTEM, (
                    f"Observation.category.coding.system must be the canonical "
                    f"HL7 Observation Category CodeSystem, got {coding['system']!r} "
                    f"in resource {r.get('id')!r}"
                )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_blood_type_observation_category_code_is_laboratory(country: str):
    """blood-type Observation.category.coding.code must be the lower-case
    canonical ``laboratory`` member — never the mis-cased ``LAB`` v2-0074
    code that triggered Issue #2003."""
    ctx = _ctx({"blood_type": "A", "rh_factor": "+"}, country=country)
    resources = _bb_blood_type(ctx)
    for r in resources:
        for cat in r["category"]:
            for coding in cat["coding"]:
                assert coding["code"] != "LAB", (
                    f"Observation.category.coding.code regressed to the "
                    f"non-canonical v2-0074 'LAB' in resource {r.get('id')!r}; "
                    f"expected canonical lower-case 'laboratory'"
                )
                assert coding["code"] in CANONICAL_OBSERVATION_CATEGORY_CODES, (
                    f"Observation.category.coding.code must be drawn from the "
                    f"canonical HL7 Observation Category value-set, got "
                    f"{coding['code']!r} in resource {r.get('id')!r}"
                )
        # The ABO + RhD Observations are lab results, so the laboratory
        # member of the canonical value-set is the one expected here.
        laboratory_codings = [c for cat in r["category"] for c in cat["coding"] if c.get("code") == "laboratory"]
        assert laboratory_codings, (
            f"blood-type Observation {r.get('id')!r} must carry the canonical 'laboratory' category coding"
        )
