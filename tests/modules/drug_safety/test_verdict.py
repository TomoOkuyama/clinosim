"""Unit tests for SafetyVerdict and SafetySkipEntry."""

from __future__ import annotations

import pytest

from clinosim.modules.drug_safety.verdict import (
    SEVERITY_RANK,
    SafetySkipEntry,
    SafetyVerdict,
)


def test_allowed_verdict_defaults() -> None:
    v = SafetyVerdict(
        severity="allowed",
        rule_id=None,
        matched_classes=None,
        matched_active_drug=None,
        rationale_en=None,
        rationale_ja=None,
        substitution_hint=None,
    )
    assert v.is_allowed is True
    assert v.default_action == "emit"


@pytest.mark.parametrize(
    "severity, expected_action",
    [
        ("allowed", "emit"),
        ("minor", "emit"),
        ("moderate", "emit_with_note"),
        ("major", "skip"),
        ("contraindicated", "skip"),
    ],
)
def test_default_action_mapping(severity: str, expected_action: str) -> None:
    v = SafetyVerdict(
        severity=severity,  # type: ignore[arg-type]
        rule_id="rule-x",
        matched_classes=("class.a", "class.b"),
        matched_active_drug="DrugA",
        rationale_en="en",
        rationale_ja="ja",
        substitution_hint=None,
    )
    assert v.default_action == expected_action
    assert v.is_allowed is (severity == "allowed")


def test_severity_rank_ordering() -> None:
    order = ["allowed", "minor", "moderate", "major", "contraindicated"]
    ranks = [SEVERITY_RANK[s] for s in order]  # type: ignore[index]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 5


def test_safety_skip_entry_frozen_fields() -> None:
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
    )
    assert entry.verdict.rule_id == "vka-plus-antiplatelet"
    assert entry.substituted_with == "Acetaminophen"
