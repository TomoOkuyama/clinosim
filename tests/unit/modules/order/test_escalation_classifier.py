"""Unit tests for classify_escalation_treatment (Issue #460).

Three-stage precedence:
  (1) explicit esc_drug["type"] wins
  (2) keyword fallback via classify_encounter_treatment on drug+dose display
  (3) default OrderType.MEDICATION
"""

from __future__ import annotations

from clinosim.modules.order.treatment_classifier import classify_escalation_treatment
from clinosim.types.encounter import OrderType


def test_explicit_type_procedure_wins_over_medication_default():
    esc = {"drug": "Mystery drug", "type": "procedure"}
    assert classify_escalation_treatment(esc) == OrderType.PROCEDURE


def test_explicit_type_medication_wins_over_keyword_hit():
    # keyword "hemodialysis" would hit, but explicit medication wins
    esc = {"drug": "Hemodialysis-adjacent drug", "type": "medication"}
    assert classify_escalation_treatment(esc) == OrderType.MEDICATION


def test_keyword_fallback_when_type_absent():
    esc = {"drug": "Hemodialysis", "dose": "3-4h"}
    assert classify_escalation_treatment(esc) == OrderType.PROCEDURE


def test_vertebroplasty_keyword_fallback():
    esc = {"drug": "Vertebroplasty", "dose": "under fluoroscopy"}
    assert classify_escalation_treatment(esc) == OrderType.PROCEDURE


def test_default_medication_when_no_type_no_keyword():
    esc = {"drug": "Vancomycin 1g", "dose": "q12h"}
    assert classify_escalation_treatment(esc) == OrderType.MEDICATION


def test_kyphoplasty_saved_by_explicit_type():
    # PROCEDURE_KEYWORDS does not cover "kyphoplasty" as of session 82.
    # Without explicit type, falls to (3) MEDICATION default.
    esc_no_type = {"drug": "Kyphoplasty", "dose": "under fluoroscopy"}
    assert classify_escalation_treatment(esc_no_type) == OrderType.MEDICATION
    # With explicit type, routes to PROCEDURE.
    esc_with_type = {
        "drug": "Kyphoplasty",
        "type": "procedure",
        "dose": "under fluoroscopy",
    }
    assert classify_escalation_treatment(esc_with_type) == OrderType.PROCEDURE


def test_catheter_directed_thrombolysis_saved_by_explicit_type():
    # No keyword coverage for "catheter-directed thrombolysis" (Issue #460).
    esc_no_type = {
        "drug": "Catheter-directed thrombolysis",
        "dose": "Urokinase via catheter",
    }
    assert classify_escalation_treatment(esc_no_type) == OrderType.MEDICATION
    esc_with_type = {"drug": "Catheter-directed thrombolysis", "type": "procedure"}
    assert classify_escalation_treatment(esc_with_type) == OrderType.PROCEDURE


def test_non_dict_input_returns_medication_default():
    # Defensive double-guard (inpatient.py:1220 already isinstance-guards).
    assert classify_escalation_treatment("bare string") == OrderType.MEDICATION  # type: ignore[arg-type]
    assert classify_escalation_treatment(None) == OrderType.MEDICATION  # type: ignore[arg-type]


def test_empty_dict_returns_medication_default():
    assert classify_escalation_treatment({}) == OrderType.MEDICATION


def test_display_name_built_from_drug_and_dose_for_keyword_match():
    # Uses "drug + dose" for keyword match — same string inpatient.py:1229 builds
    # for the Order display_name. "continuous renal replacement" spans the join.
    esc = {"drug": "Continuous", "dose": "renal replacement therapy"}
    assert classify_escalation_treatment(esc) == OrderType.PROCEDURE


def test_daily_loop_module_imports_new_classifier():
    """After Task 2 wiring, the daily-loop state machine imports
    classify_escalation_treatment.

    Smoke guard against silent revert. Behavioral verification lives in the
    integration test suite (test_escalation_procedure_emission.py).

    Issue #552 (2026-08-09) moved the daily-loop body out of inpatient.py
    to a sibling `daily_loop.py`; the classifier consumer moved with it.
    """
    import clinosim.simulator.daily_loop as daily_loop_mod

    assert hasattr(daily_loop_mod, "classify_escalation_treatment"), (
        "daily_loop.py must import classify_escalation_treatment from "
        "clinosim.modules.order.treatment_classifier (Issue #460 wiring)"
    )
