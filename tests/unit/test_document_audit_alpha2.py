"""Unit tests for document chain audit α-min-2 extensions (Task 13).

Covers:
- lift_firing_proof extended to 24+ checks (17 α-min-1 + 7 α-min-2)
- CARE_TEAM_ID_PREFIX canonical constant equality check
- 5 new no-drop invariants (CareTeam fields + encounter-type dispatch paths)
- 8 new clinical_acceptance keys (per spec §9.3 α-min-2)
- _check_care_team_coverage clinical axis gate exists in clinical.py
"""

from __future__ import annotations

import pytest

from clinosim.audit.registry import discover, get_registered
from clinosim.modules.output._fhir_care_team import CARE_TEAM_ID_PREFIX


def _get_spec():
    """Helper: ensure registry is populated and return document_chain spec."""
    discover()
    return get_registered()["document_chain"]


def _build_proof():
    """Helper: call the lift_firing_proof factory and return the result."""
    spec = _get_spec()
    assert spec.lift_firing_proof is not None
    return spec.lift_firing_proof()


@pytest.mark.unit
def test_lift_firing_proof_has_24_plus_checks():
    """α-min-2 extension: 17 α-min-1 + 7 α-min-2 = 24+ total equality_checks."""
    proof = _build_proof()
    checks = proof["equality_checks"]
    assert len(checks) >= 24, (
        f"Expected >= 24 equality_checks (17 α-min-1 + 7 α-min-2), got {len(checks)}"
    )


@pytest.mark.unit
def test_lift_firing_proof_includes_care_team_prefix():
    """CARE_TEAM_ID_PREFIX canonical constant equality check present and passing."""
    proof = _build_proof()
    checks = proof["equality_checks"]
    care_team_checks = [c for c in checks if "CARE_TEAM_ID_PREFIX" in c[0]]
    assert len(care_team_checks) >= 1, (
        f"No CARE_TEAM_ID_PREFIX check found in equality_checks labels: "
        f"{[c[0] for c in checks]}"
    )
    label, actual, expected = care_team_checks[0]
    assert actual == expected, (
        f"CARE_TEAM_ID_PREFIX check failed: actual={actual!r} != expected={expected!r}"
    )
    assert actual == CARE_TEAM_ID_PREFIX, (
        f"CARE_TEAM_ID_PREFIX check actual={actual!r} does not match imported constant "
        f"{CARE_TEAM_ID_PREFIX!r}"
    )


@pytest.mark.unit
def test_clinical_acceptance_has_alpha2_keys():
    """α-min-2 additions: 8 new clinical_acceptance keys per spec §9.3."""
    spec = _get_spec()
    expected_alpha2_keys = {
        "care_team_per_encounter",
        "triage_data_per_ed_encounter",
        "admission_nursing_assessment_per_inpatient_encounter",
        "nursing_shift_note_per_day_per_inpatient",
        "nursing_discharge_summary_per_completed_inpatient",
        "outpatient_soap_per_outpatient_encounter",
        "ed_note_per_ed_encounter",
        "ed_triage_note_per_ed_encounter",
    }
    actual_keys = set(spec.clinical_acceptance.keys())
    missing = expected_alpha2_keys - actual_keys
    assert not missing, (
        f"α-min-2 clinical_acceptance keys missing: {sorted(missing)}\n"
        f"  All present keys: {sorted(actual_keys)}"
    )


@pytest.mark.unit
def test_no_drop_invariants_include_alpha2():
    """5+ new no-drop invariants for α-min-2 flow paths.

    Checks for no_drop labels relating to care_team, triage_data,
    outpatient, emergency, and inpatient nursing dispatch paths.
    """
    proof = _build_proof()
    checks = proof["equality_checks"]
    no_drop_labels = [c[0] for c in checks if "no_drop" in c[0].lower()]
    alpha2_keywords = ("care_team", "triage", "outpatient", "emergency", "inpatient")
    alpha2_no_drop = [
        label for label in no_drop_labels
        if any(kw in label.lower() for kw in alpha2_keywords)
    ]
    assert len(alpha2_no_drop) >= 5, (
        f"Expected >= 5 α-min-2 no_drop invariants "
        f"(care_team/triage/outpatient/emergency/inpatient), "
        f"got {len(alpha2_no_drop)}: {alpha2_no_drop}"
    )


@pytest.mark.unit
def test_all_proof_checks_pass():
    """Load-bearing self-check: every proof tuple actual == expected.

    A check failure here means either a canonical constant drifted or
    a FHIR builder is silently returning the wrong value (PR-90 class).
    """
    proof = _build_proof()
    checks = proof["equality_checks"]
    failures = [(label, actual, expected) for label, actual, expected in checks if actual != expected]
    assert not failures, (
        "Some equality_checks failed:\n"
        + "\n".join(
            f"  {label!r}: actual={actual!r} != expected={expected!r}"
            for label, actual, expected in failures
        )
    )


@pytest.mark.unit
def test_check_care_team_coverage_exists():
    """clinical axis has _check_care_team_coverage function."""
    from clinosim.audit.axes import clinical
    assert hasattr(clinical, "_check_care_team_coverage"), (
        "_check_care_team_coverage not found in clinosim.audit.axes.clinical; "
        "Task 13 CareTeam ref integrity gate missing"
    )
    assert callable(clinical._check_care_team_coverage), (
        "_check_care_team_coverage is not callable"
    )


@pytest.mark.unit
def test_canonical_constants_includes_care_team_prefix():
    """ModuleAuditSpec.canonical_constants must contain care_team_id_prefix."""
    spec = _get_spec()
    cc = spec.canonical_constants
    assert "care_team_id_prefix" in cc, (
        f"canonical_constants missing 'care_team_id_prefix'; "
        f"keys present: {sorted(cc.keys())}"
    )
    assert cc["care_team_id_prefix"] == (CARE_TEAM_ID_PREFIX,), (
        f"care_team_id_prefix canonical_constants value mismatch: "
        f"got {cc['care_team_id_prefix']!r}, expected {(CARE_TEAM_ID_PREFIX,)!r}"
    )


@pytest.mark.unit
def test_lift_firing_proof_includes_3shift_cadence_checks():
    """α-min-3: 3-per-day nursing shift cadence proof checks present and passing."""
    proof = _build_proof()
    labels = {c[0]: c for c in proof["equality_checks"]}
    for name in (
        "nursing_shift_note_3_per_day_count",
        "nursing_shift_note_shift_keys_complete",
        "nursing_shift_note_shift_hour_offsets",
    ):
        assert name in labels, f"missing α-min-3 proof check {name!r}"
        _, actual, expected = labels[name]
        assert actual == expected, (
            f"α-min-3 proof check {name!r} failed: {actual!r} != {expected!r}"
        )


@pytest.mark.unit
def test_lift_firing_proof_includes_admission_care_plan_checks():
    """chain 2: admission_care_plan dispatch proof (JP-only, inpatient/icu gate).

    adv-1 finding: the original proof omitted the icu case despite icu being
    one of only two encounter_types_supported values — jp_icu_count added.
    """
    proof = _build_proof()
    labels = {c[0]: c for c in proof["equality_checks"]}
    assert "admission_care_plan_jp_inpatient_count" in labels
    assert "admission_care_plan_jp_icu_count" in labels
    assert "admission_care_plan_us_inpatient_count" in labels
    assert "admission_care_plan_jp_rehab_inpatient_count" in labels
    for label in (
        "admission_care_plan_jp_inpatient_count",
        "admission_care_plan_jp_icu_count",
        "admission_care_plan_us_inpatient_count",
        "admission_care_plan_jp_rehab_inpatient_count",
    ):
        _, actual, expected = labels[label]
        assert actual == expected, f"{label}: {actual!r} != {expected!r}"


@pytest.mark.unit
def test_lift_firing_proof_includes_nutrition_care_plan_checks():
    """chain 2: nutrition_care_plan dispatch proof — LOS>7 gate, JP-only gate.

    Proves BOTH positive (LOS>7 fires) and negative (LOS<=7 does not fire)
    cases, per the admission_care_plan adv-1 lesson (design spec §5).
    """
    proof = _build_proof()
    labels = {c[0]: c for c in proof["equality_checks"]}
    expected_labels = (
        "nutrition_care_plan_jp_inpatient_los10_count",
        "nutrition_care_plan_jp_inpatient_los5_count",
        "nutrition_care_plan_jp_icu_los10_count",
        "nutrition_care_plan_us_inpatient_los10_count",
    )
    for label in expected_labels:
        assert label in labels, f"missing check {label!r}"
        _, actual, expected = labels[label]
        assert actual == expected, f"{label}: {actual!r} != {expected!r}"
