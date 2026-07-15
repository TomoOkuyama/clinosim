"""Unit tests for narrative fact_extractor helpers (AD-65 E2, F-9 adv-1)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from clinosim.modules.document.narrative.fact_extractor import (
    extract_lab_facts,
    extract_medication_facts,
)


@dataclass
class _LabStub:
    """Minimal dataclass fixture for extract_lab_facts tests.

    Mimics the shape of OrderResult / LabResult but keeps the surface
    tiny so tests don't depend on the full production dataclass.
    """

    test_name: str
    value: float
    day_index: int


@dataclass
class _MedStub:
    drug_name: str
    dose: float


@pytest.mark.unit
def test_extract_lab_facts_emits_value_zero_dataclass() -> None:
    """F-9 adv-1 fix: dataclass with value=0.0 must produce a fact.

    Prior `getattr(lab, "value", None) or (lab.get("value") if ...)`
    short-circuited on 0.0 → None → fact silently dropped. This test
    pins the fixed behavior so a future regression to the truthy-or
    pattern would fail immediately.
    """
    labs = [_LabStub(test_name="Glucose", value=0.0, day_index=0)]
    facts = extract_lab_facts(labs)
    assert len(facts) == 1
    assert facts[0].key == "lab.glucose.day0"
    assert facts[0].value == "0.0"


@pytest.mark.unit
def test_extract_lab_facts_emits_value_zero_dict() -> None:
    """Dict-from-JSON path (production) should also handle value=0.0.

    The prior code's `lab.get("value")` branch actually worked for
    dicts (returns 0.0), but this test locks in the invariant for
    when the shared helper is the single edit point.
    """
    labs = [{"test_name": "Glucose", "value": 0.0, "day_index": 0}]
    facts = extract_lab_facts(labs)
    assert len(facts) == 1
    assert facts[0].value == "0.0"


@pytest.mark.unit
def test_extract_lab_facts_drops_none_value() -> None:
    """Actually-missing value (None) is dropped — NOT the same as 0.0."""

    @dataclass
    class _LabWithNone:
        test_name: str = "Glucose"
        value: float | None = None
        day_index: int = 0

    facts = extract_lab_facts([_LabWithNone()])
    assert facts == []


@pytest.mark.unit
def test_extract_medication_facts_dose_zero_dataclass() -> None:
    """F-9 adv-1 parallel fix: medication dose=0.0 falls through the
    else-branch (`administered` label) rather than raising, but the
    helper must not silently drop the medication entirely. Verifies
    the dose=0.0 case produces one fact for a valid drug_name.
    """
    facts = extract_medication_facts([_MedStub(drug_name="Insulin", dose=0.0)])
    assert len(facts) == 1
    assert facts[0].key == "med.insulin"
    # 0.0 is falsy → fallback label
    assert facts[0].value == "administered"


@pytest.mark.unit
def test_extract_medication_facts_dose_positive() -> None:
    facts = extract_medication_facts([_MedStub(drug_name="Vancomycin", dose=1000.0)])
    assert len(facts) == 1
    assert facts[0].value == "1000.0"
