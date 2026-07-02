"""Scenario-driven narrative spine (AD-65 E1).

Extracts canonical clinical trajectory hints from DiseaseProtocol /
EncounterProtocol YAML into a NarrativeSpine dataclass. The spine is
used by TemplateNarrativeGenerator to anchor narrative to the archetype.
"""

from __future__ import annotations

from typing import Any

from clinosim.types.document import NarrativeSpine


def build_narrative_spine(
    disease_protocol: Any | None,
    encounter_protocol: Any | None,
    archetype: str,
) -> NarrativeSpine | None:
    """Return a NarrativeSpine or None if no source protocol available."""
    if disease_protocol is None and encounter_protocol is None:
        return None
    p = disease_protocol or encounter_protocol
    return NarrativeSpine(
        archetype=archetype or "",
        key_events=list(getattr(p, "key_events", []) or []),
        complications_expected=list(getattr(p, "complications", []) or []),
        outcome_benchmark=str(getattr(p, "outcome_benchmark", "") or ""),
        disease_narrative_hints=dict(getattr(p, "narrative_hints", {}) or {}),
    )
