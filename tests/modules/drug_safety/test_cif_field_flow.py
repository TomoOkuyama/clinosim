"""Verify safety_skip_log flows from PatientProfile into NarrativeContext."""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.drug_safety.verdict import SafetySkipEntry, SafetyVerdict


def test_patient_profile_has_safety_skip_log_default_empty() -> None:
    from clinosim.types.patient import PatientProfile

    assert "safety_skip_log" in PatientProfile.__dataclass_fields__
    default = PatientProfile.__dataclass_fields__["safety_skip_log"].default_factory()
    assert default == []


def test_narrative_context_has_safety_skips_default_empty() -> None:
    from clinosim.types.document import NarrativeContext

    assert "safety_skips" in NarrativeContext.__dataclass_fields__
    default = NarrativeContext.__dataclass_fields__["safety_skips"].default_factory()
    assert default == []


def test_build_narrative_context_filters_skips_by_encounter() -> None:
    from clinosim.modules.document.narrative.context import build_narrative_context
    from clinosim.types.document import DocumentType

    v = SafetyVerdict(
        severity="contraindicated",
        rule_id="vka-plus-antiplatelet",
        matched_classes=("anticoagulant.vka", "antiplatelet"),
        matched_active_drug="Warfarin",
        rationale_en="risk",
        rationale_ja="リスク",
        substitution_hint="pain_management",
    )
    entries = [
        SafetySkipEntry(
            encounter_id="ENC-1",
            candidate_drug="Ibuprofen",
            candidate_drug_ja="イブプロフェン",
            active_conflict="Warfarin",
            active_conflict_ja="ワルファリン",
            verdict=v,
            substituted_with="Acetaminophen",
            substituted_with_ja="アセトアミノフェン",
            context_hint="pain_management",
            timestamp="2026-01-01T09:00:00",
        ),
        SafetySkipEntry(
            encounter_id="ENC-2",  # different encounter — must be filtered out
            candidate_drug="Ibuprofen",
            candidate_drug_ja="イブプロフェン",
            active_conflict="Warfarin",
            active_conflict_ja="ワルファリン",
            verdict=v,
            substituted_with=None,
            substituted_with_ja=None,
            context_hint="pain_management",
            timestamp="2026-01-02T09:00:00",
        ),
    ]
    patient = SimpleNamespace(safety_skip_log=entries, allergies=[])
    record = SimpleNamespace(patient=patient)
    encounter = SimpleNamespace(id="ENC-1", encounter_type=None)

    ctx = build_narrative_context(
        record=record,
        encounter=encounter,
        document_type=DocumentType.PROGRESS_NOTE,
        day_index=0,
        country="jp",
    )
    assert len(ctx.safety_skips) == 1
    entry = ctx.safety_skips[0]
    assert entry["considered"] == "Ibuprofen"
    assert entry["substituted_with"] == "Acetaminophen"
    assert entry["severity"] == "contraindicated"
    assert entry["rationale_ja"] == "リスク"


def test_build_narrative_context_empty_when_no_log() -> None:
    from clinosim.modules.document.narrative.context import build_narrative_context
    from clinosim.types.document import DocumentType

    patient = SimpleNamespace(safety_skip_log=[], allergies=[])
    record = SimpleNamespace(patient=patient)
    encounter = SimpleNamespace(id="ENC-1", encounter_type=None)

    ctx = build_narrative_context(
        record=record,
        encounter=encounter,
        document_type=DocumentType.PROGRESS_NOTE,
        day_index=0,
        country="us",
    )
    assert ctx.safety_skips == []


def test_build_narrative_context_no_encounter_id_yields_empty() -> None:
    from clinosim.modules.document.narrative.context import build_narrative_context
    from clinosim.types.document import DocumentType

    v = SafetyVerdict(
        severity="contraindicated",
        rule_id="vka-plus-antiplatelet",
        matched_classes=("anticoagulant.vka", "antiplatelet"),
        matched_active_drug="Warfarin",
        rationale_en="risk",
        rationale_ja="リスク",
        substitution_hint="pain_management",
    )
    entries = [
        SafetySkipEntry(
            encounter_id="__home_med_derivation__",
            candidate_drug="Aspirin",
            candidate_drug_ja="アスピリン",
            active_conflict="Warfarin",
            active_conflict_ja="ワルファリン",
            verdict=v,
            substituted_with=None,
            substituted_with_ja=None,
            context_hint="home_med_derivation",
            timestamp="2026-01-01T00:00:00",
        )
    ]
    patient = SimpleNamespace(safety_skip_log=entries, allergies=[])
    record = SimpleNamespace(patient=patient)
    encounter = SimpleNamespace(id="ENC-99", encounter_type=None)

    ctx = build_narrative_context(
        record=record,
        encounter=encounter,
        document_type=DocumentType.PROGRESS_NOTE,
        day_index=0,
        country="jp",
    )
    # home_med_derivation sentinel doesn't match ENC-99
    assert ctx.safety_skips == []
