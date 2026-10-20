"""Phase 4b.1 final-review fix — SBP yaml comments must not claim
a Layer-1 override that is not implemented.

Phase 4b.1 Task 6 Ruling: PersonRecord has no systolic_bp field, so the
plan's intended Layer-1 anchor override was skipped. The yaml comment
originally claimed the override exists ("overridden by Layer-1 systolic_bp
at base year; yaml's initial: block is dummy"). This test pins that the
stale claim is removed — if a future maintainer re-adds the override,
they also update the yaml header to match.
"""

from __future__ import annotations

from pathlib import Path

YAML = (
    Path(__file__).resolve().parents[3]
    / "clinosim"
    / "locale"
    / "shared"
    / "longitudinal"
    / "vitals"
    / "sbp_trajectory.yaml"
)


def test_sbp_yaml_header_does_not_claim_unimplemented_layer1_override():
    text = YAML.read_text(encoding="utf-8")
    # Phrases that falsely imply the override exists.
    forbidden_phrases = (
        "Layer-1 anchor override",
        "float(person.systolic_bp)",
        "overridden by Layer-1 systolic_bp",
        "yaml's initial: block is dummy",
    )
    hits = [p for p in forbidden_phrases if p in text]
    assert not hits, (
        f"sbp_trajectory.yaml claims a Layer-1 override that is not implemented: {hits}. "
        f"Either implement the override in population/engine.py or remove the claim."
    )
