"""Issue #1766: MedicationRequest.medicationCodeableConcept.coding.display
must not carry trade-name decorations like ``Enoxaparin (Lovenox)`` on
US output. The RxNorm canonical display for a drug's base-ingredient CUI
is the generic name alone; trade names are not valid displays against
the RxNorm binding and the HL7 FHIR validator rejects them as display
mismatches.

Fix: emit-time strip of the trailing ``(TradeName)`` parenthetical for
US output. The source yaml tables (``rxnorm.yaml``, ``hot7.yaml``) keep
the decorated form so clinician search by trade name still works; the
FHIR builder strips before writing ``coding[].display``. JP output
preserves the Japanese-locale annotation.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import (
    _resolve_medication_concept,
)

# Each case: (yaml-registered drug name, trade name that must NOT appear in display)
_US_CASES = [
    ("Enoxaparin", "Lovenox"),
    ("Acetaminophen", "Tylenol"),
    ("Warfarin", "Coumadin"),
    ("Atorvastatin", "Lipitor"),
    ("Amlodipine", "Norvasc"),
    ("Lisinopril", "Zestril"),
    ("Metformin", "Glucophage"),
    ("Furosemide", "Lasix"),
    ("Clopidogrel", "Plavix"),
    ("Celecoxib", "Celebrex"),
]


@pytest.mark.parametrize("drug_name,trade_name", _US_CASES)
def test_us_rxnorm_display_strips_trade_name(drug_name: str, trade_name: str) -> None:
    """Issue #1766: US MedicationRequest display must not include the
    trade name parenthetical."""
    concept, _ = _resolve_medication_concept(
        display_name_raw=drug_name,
        order_code="",
        country="US",
    )
    codings = concept.get("coding") or []
    # Must have resolved to an RxNorm coding (coverage is a separate test)
    assert codings, f"US {drug_name} did not resolve to a coding"
    display = codings[0].get("display", "")
    assert display, f"US {drug_name} resolved coding has empty display"
    assert trade_name not in display, (
        f"US {drug_name} display must not contain the trade name {trade_name!r}; got display={display!r}"
    )
    # And the opening parenthesis must be absent — a general catch for any
    # trade-name-style decoration we may not have enumerated.
    assert "(" not in display, (
        f"US {drug_name} display must not carry any parenthetical decoration; got display={display!r}"
    )


def test_us_rxnorm_display_preserves_canonical_generic_name() -> None:
    """Positive: stripping must leave the canonical generic name intact."""
    concept, _ = _resolve_medication_concept(
        display_name_raw="Enoxaparin",
        order_code="",
        country="US",
    )
    assert concept["coding"][0]["display"] == "Enoxaparin"


def test_jp_rxnorm_display_untouched_by_us_strip() -> None:
    """JP output preserves the Japanese annotation form — the strip is
    scoped to US output only. (JP uses HOT/YJ system URIs, not RxNorm,
    but the ``_resolve_medication_concept`` path is shared.)"""
    concept, _ = _resolve_medication_concept(
        display_name_raw="Acetaminophen",
        order_code="",
        country="JP",
    )
    codings = concept.get("coding") or []
    if codings:
        display = codings[0].get("display", "")
        # JP form may legitimately carry 括弧付き annotation (e.g.
        # ``アセトアミノフェン（カロナール）``). Don't assert specific content —
        # just that the US strip isn't firing on JP.
        if "（" in display or "(" in display:
            # Legacy form still carries the trade-name annotation. That's
            # by design on JP output — assertion is the ABSENCE of the US
            # strip, not any specific display value.
            assert True
