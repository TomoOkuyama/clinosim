"""AD-60 audit plug-in unit tests."""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.drug_safety.audit import AuditFinding, audit_drug_safety
from clinosim.modules.drug_safety.verdict import SafetySkipEntry, SafetyVerdict


def _patient(patient_id: str, drug_names: list[str], skip_log: list = None) -> SimpleNamespace:
    home_meds = [SimpleNamespace(drug_name=d) for d in drug_names]
    return SimpleNamespace(
        profile=SimpleNamespace(
            patient_id=patient_id,
            home_medications=home_meds,
            current_medications=home_meds,
            safety_skip_log=skip_log or [],
        ),
    )


def test_audit_flags_missed_gate_pair() -> None:
    """warfarin + aspirin present in home_meds AND no matching skip entry ⇒ finding."""
    p = _patient("PT-1", ["Warfarin", "Aspirin"], skip_log=[])
    findings = audit_drug_safety([p])
    assert len(findings) == 1
    assert findings[0].patient_id == "PT-1"
    assert "Warfarin" in findings[0].description
    assert "Aspirin" in findings[0].description
    assert findings[0].severity == "contraindicated"


def test_audit_passes_clean_case() -> None:
    """Warfarin alone with no partner drug ⇒ no finding."""
    p = _patient("PT-1", ["Warfarin"], skip_log=[])
    assert audit_drug_safety([p]) == []


def test_audit_skips_pair_with_matching_skip_log_entry() -> None:
    """Warfarin + Aspirin present but SafetySkipEntry logs the skip ⇒ no finding.
    (This is the expected steady state after Task 8 wires the activator gate:
    aspirin would not be in home_meds; we simulate a hypothetical state where
    it was retained with a matching skip entry to exercise the audit's
    dedup path.)"""
    v = SafetyVerdict(
        severity="contraindicated",
        rule_id="vka-plus-antiplatelet",
        matched_classes=("anticoagulant.vka", "antiplatelet"),
        matched_active_drug="Warfarin",
        rationale_en="risk",
        rationale_ja="リスク",
        substitution_hint="pain_management",
    )
    entry = SafetySkipEntry(
        encounter_id="__home_med_derivation__",
        candidate_drug="Aspirin",
        candidate_drug_ja="アスピリン",
        active_conflict="Warfarin",
        active_conflict_ja="ワルファリン",
        verdict=v,
        substituted_with=None,
        substituted_with_ja=None,
        context_hint="home_med_derivation",
        timestamp="",
    )
    p = _patient("PT-1", ["Warfarin", "Aspirin"], skip_log=[entry])
    # Both directions of the pair are excluded via the skipped_pairs set.
    assert audit_drug_safety([p]) == []


def test_audit_returns_multiple_findings_across_patients() -> None:
    p1 = _patient("PT-1", ["Warfarin", "Ibuprofen"], skip_log=[])
    p2 = _patient("PT-2", ["Selegiline", "Sertraline"], skip_log=[])
    findings = audit_drug_safety([p1, p2])
    ids = {f.patient_id for f in findings}
    assert ids == {"PT-1", "PT-2"}


def test_audit_returns_auditfinding_dataclass() -> None:
    p = _patient("PT-1", ["Warfarin", "Aspirin"])
    findings = audit_drug_safety([p])
    assert isinstance(findings[0], AuditFinding)
