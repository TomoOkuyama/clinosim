"""Regression guards for Issue #548 — MedicationRequest.category derivation.

`_derive_mr_category` is the single source of truth for the
medicationrequest-category (code, display) tuple emitted by both
`_build_medication_request` (order path) and
`_build_discharge_medication_request` (discharge path).

Prior to Issue #548 each caller used its own inline decision (5-branch
vs 2-branch), letting the discharge path silently misclassify
emergency-encounter discharge scripts as `community` when they are
actually episodic ED-treatment (HL7-canonical: `outpatient`).

These tests lock:

1. All 5 canonical decision-tree branches produce the expected
   (code, display) tuple across the full input space.
2. The discharge-path caller (is_home_med=False, is_episodic=False,
   is_discharge_intent=True) produces the intended per-encounter-type
   category tuples, INCLUDING the two documented shifts vs pre-#548
   behavior (emergency → outpatient; empty/unknown → inpatient).
3. The order-path caller's boolean derivation (from clinical_intent
   substrings) maps to the same tuples as before the extraction —
   proves the refactor is byte-neutral on the order side.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import _derive_mr_category

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "encounter_type,is_home_med,is_episodic,is_discharge_intent,expected",
    [
        # Rule 1: home_med always community (regardless of encounter type)
        ("inpatient", True, False, False, ("community", "Community")),
        ("outpatient", True, False, False, ("community", "Community")),
        ("emergency", True, False, False, ("community", "Community")),
        # Rule 1: outpatient non-episodic = community
        ("outpatient", False, False, False, ("community", "Community")),
        ("outpatient", False, False, True, ("community", "Community")),
        # Rule 2: outpatient episodic = outpatient (rule 1 fails on episodic=True)
        ("outpatient", False, True, False, ("outpatient", "Outpatient")),
        # Rule 2: emergency = outpatient (regardless of episodic flag)
        ("emergency", False, False, False, ("outpatient", "Outpatient")),
        ("emergency", False, True, False, ("outpatient", "Outpatient")),
        # Rule 3: inpatient with discharge intent
        ("inpatient", False, False, True, ("discharge", "Discharge")),
        # Rule 4: inpatient without discharge intent
        ("inpatient", False, False, False, ("inpatient", "Inpatient")),
        ("inpatient", False, True, False, ("inpatient", "Inpatient")),
        # Rule 5: unknown / empty fallback
        ("", False, False, False, ("inpatient", "Inpatient")),
        ("virtual", False, False, False, ("inpatient", "Inpatient")),
    ],
)
def test_derive_mr_category(
    encounter_type: str,
    is_home_med: bool,
    is_episodic: bool,
    is_discharge_intent: bool,
    expected: tuple[str, str],
) -> None:
    """Direct-input coverage for all five rules of ``_derive_mr_category``."""
    assert (
        _derive_mr_category(encounter_type, is_home_med, is_episodic, is_discharge_intent)
        == expected
    )


@pytest.mark.parametrize(
    "encounter_type,expected_code",
    [
        ("inpatient", "discharge"),  # no shift (rule 3)
        ("outpatient", "community"),  # no shift (rule 1)
        ("emergency", "outpatient"),  # SHIFT: was "community" pre-Issue-#548
        ("", "inpatient"),  # SHIFT edge: was "community" pre-Issue-#548
        ("virtual", "inpatient"),  # SHIFT edge (unknown encounter type)
    ],
)
def test_derive_mr_category_discharge_caller_shift(
    encounter_type: str, expected_code: str
) -> None:
    """Documented shifts introduced by the Issue #548 unification.

    The discharge path historically used a 2-branch decision (inpatient →
    discharge, else → community). The 5-rule unified logic corrects the
    ED-discharge case (episodic Rx should be ``outpatient``, not community)
    and the empty/unknown-encounter-type fallback (``inpatient`` matches
    the order path's fallback rather than defaulting to ``community``).
    """
    code, _display = _derive_mr_category(
        encounter_type=encounter_type,
        is_home_med=False,
        is_episodic=False,
        is_discharge_intent=True,
    )
    assert code == expected_code


@pytest.mark.parametrize(
    "encounter_type,clinical_intent,expected_code",
    [
        # Order path pre-Issue-#548 emitted these; refactor must preserve.
        ("inpatient", "home medication list", "community"),
        ("outpatient", "annual check-up", "community"),
        ("outpatient", "supportive: iv fluids", "outpatient"),
        ("emergency", "ed treatment: nebulizer", "outpatient"),
        ("inpatient", "discharge take-home", "discharge"),
        ("inpatient", "day 3 iv antibiotics", "inpatient"),  # episodic + inpatient = inpatient
        ("", "", "inpatient"),  # empty fallback
    ],
)
def test_order_caller_category_byte_neutral(
    encounter_type: str, clinical_intent: str, expected_code: str
) -> None:
    """Prove the order-path helper derivation reproduces pre-#548 behavior.

    The order caller derives is_home_med / is_episodic / is_discharge_intent
    from clinical_intent substrings; this test threads those same substrings
    through the derivation and asserts the resulting category matches what
    the pre-refactor inline decision tree at
    ``_build_medication_request:679-698`` would emit.
    """
    ci_lower = clinical_intent.lower()
    is_home_med = "home medication" in ci_lower
    episodic_kw = (
        "supportive:",
        "ed treatment:",
        "day ",
        "dvt_prophylaxis",
        "antibiotic",
        "escalation",
    )
    is_episodic = (not is_home_med) and any(kw in ci_lower for kw in episodic_kw)
    is_discharge_intent = "discharge" in ci_lower
    code, _display = _derive_mr_category(
        encounter_type, is_home_med, is_episodic, is_discharge_intent
    )
    assert code == expected_code
