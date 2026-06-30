"""Unit tests for document chain audit module (AD-60 plug-in #5, Tier 1 #3 α-min-1 Task 11).

The discover() call fires the side-effect that registers ModuleAuditSpec.
Tests call discover() to ensure the spec is loaded even after _reset_for_test()
clears the registry (same pattern as test_imaging_audit.py / test_order_audit.py).
"""

from __future__ import annotations

import pytest

from clinosim.audit.registry import discover, get_registered
from clinosim.modules.document import (
    ALLERGY_ID_PREFIX,
    CLINICAL_IMPRESSION_ID_PREFIX,
    COMPOSITION_ID_PREFIX,
    DOC_REFERENCE_ID_PREFIX,
)


@pytest.mark.unit
def test_document_chain_module_registered():
    """discover() finds and registers ModuleAuditSpec 'document_chain'."""
    discover()
    specs = get_registered()
    assert "document_chain" in specs, (
        f"'document_chain' not in registry after discover(); "
        f"registered: {sorted(specs)}"
    )


@pytest.mark.unit
def test_canonical_constants_correct():
    """ModuleAuditSpec.canonical_constants entries match actual module constants.

    Guards against constant drift where the audit records a stale expected
    value while the actual constant has changed (PR-90 Layer 1-2 defense).
    """
    discover()
    spec = get_registered()["document_chain"]
    cc = spec.canonical_constants

    assert "doc_reference_id_prefix" in cc, (
        "canonical_constants must contain 'doc_reference_id_prefix'"
    )
    assert cc["doc_reference_id_prefix"] == (DOC_REFERENCE_ID_PREFIX,), (
        f"doc_reference_id_prefix mismatch: {cc['doc_reference_id_prefix']!r} "
        f"vs actual {DOC_REFERENCE_ID_PREFIX!r}"
    )
    assert "composition_id_prefix" in cc, (
        "canonical_constants must contain 'composition_id_prefix'"
    )
    assert cc["composition_id_prefix"] == (COMPOSITION_ID_PREFIX,), (
        f"composition_id_prefix mismatch: {cc['composition_id_prefix']!r} "
        f"vs actual {COMPOSITION_ID_PREFIX!r}"
    )
    assert "allergy_id_prefix" in cc, (
        "canonical_constants must contain 'allergy_id_prefix'"
    )
    assert cc["allergy_id_prefix"] == (ALLERGY_ID_PREFIX,), (
        f"allergy_id_prefix mismatch: {cc['allergy_id_prefix']!r} "
        f"vs actual {ALLERGY_ID_PREFIX!r}"
    )
    assert "clinical_impression_id_prefix" in cc, (
        "canonical_constants must contain 'clinical_impression_id_prefix'"
    )
    assert cc["clinical_impression_id_prefix"] == (CLINICAL_IMPRESSION_ID_PREFIX,), (
        f"clinical_impression_id_prefix mismatch: {cc['clinical_impression_id_prefix']!r} "
        f"vs actual {CLINICAL_IMPRESSION_ID_PREFIX!r}"
    )


@pytest.mark.unit
def test_lift_firing_proof_is_callable():
    """lift_firing_proof must be a zero-arg callable (not a raw dict).

    Storing a raw dict bypasses the silent_no_op axis execution and is
    itself the PR-90 class bug in the audit framework (the proof never runs).
    """
    discover()
    spec = get_registered()["document_chain"]
    assert spec.lift_firing_proof is not None
    assert callable(spec.lift_firing_proof), (
        "lift_firing_proof must be a callable (zero-arg factory returning "
        "dict with equality_checks); storing a raw dict bypasses the "
        "silent_no_op axis and is the PR-90 class bug in the audit framework"
    )


@pytest.mark.unit
def test_lift_firing_proof_all_checks_pass():
    """All equality_checks must have actual == expected (no canonical drift or builder no-op)."""
    discover()
    spec = get_registered()["document_chain"]
    assert spec.lift_firing_proof is not None
    proof = spec.lift_firing_proof()
    assert "equality_checks" in proof, (
        f"proof must contain 'equality_checks' key; got keys: {sorted(proof.keys())}"
    )
    failures = [
        (label, actual, expected)
        for label, actual, expected in proof["equality_checks"]
        if actual != expected
    ]
    assert not failures, (
        "Some equality_checks failed (canonical drift or builder silent-no-op):\n"
        + "\n".join(
            f"  {label!r}: actual={actual!r} != expected={expected!r}"
            for label, actual, expected in failures
        )
    )


@pytest.mark.unit
def test_lift_firing_proof_has_at_least_15_checks():
    """The lift_firing_proof factory must return >= 15 equality_checks 3-tuples."""
    discover()
    spec = get_registered()["document_chain"]
    assert spec.lift_firing_proof is not None
    proof = spec.lift_firing_proof()
    assert "equality_checks" in proof, (
        f"proof must contain 'equality_checks' key; got keys: {sorted(proof.keys())}"
    )
    checks = proof["equality_checks"]
    assert len(checks) >= 15, (
        f"Expected >= 15 equality_checks, got {len(checks)}: {checks}"
    )
    # All checks must be (label, actual, expected) 3-tuples.
    for i, check in enumerate(checks):
        assert len(check) == 3, (
            f"equality_checks[{i}] must be (label, actual, expected), got: {check!r}"
        )


@pytest.mark.unit
def test_lift_firing_proof_includes_no_drop_invariants():
    """Section 3.4 CIF→FHIR no-drop gates must appear in equality_checks.

    Labels must contain 'no_drop' or 'preserved' to be counted.
    At least 5 such guards are required to cover:
      - ClinicalDocument.text -> DocumentReference.content.attachment.data
      - ClinicalDocument.sections -> Composition.section[]
      - ClinicalDocument.loinc_code -> DocumentReference.type.coding[].code
      - patient.allergies[].allergen_code -> AllergyIntolerance.code.coding[].code
      - ClinicalImpressionRecord.description -> ClinicalImpression.description
    """
    discover()
    spec = get_registered()["document_chain"]
    assert spec.lift_firing_proof is not None
    proof = spec.lift_firing_proof()
    checks = proof["equality_checks"]
    no_drop_checks = [
        (label, actual, expected)
        for label, actual, expected in checks
        if "no_drop" in label or "preserved" in label
    ]
    assert len(no_drop_checks) >= 5, (
        f"Expected >= 5 no_drop/preserved equality_checks, got {len(no_drop_checks)}.\n"
        f"Matching labels: {[label for label, _, _ in no_drop_checks]}\n"
        f"All labels: {[label for label, _, _ in checks]}"
    )
