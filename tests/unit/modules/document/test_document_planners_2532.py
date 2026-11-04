"""Document planners cover exactly the allowed generation frequencies
(Issue #2532): a frequency accepted at YAML load but without a planner would
silently emit no documents."""

from __future__ import annotations

from clinosim.modules.document.engine import _PLANNERS
from clinosim.modules.document.narrative.registry import GENERATION_FREQUENCIES, load_document_type_specs


def test_planners_match_the_allowed_frequencies() -> None:
    assert set(_PLANNERS) == set(GENERATION_FREQUENCIES)


def test_every_registered_spec_has_a_planner() -> None:
    assert {spec.generation_frequency for spec in load_document_type_specs().values()} <= set(_PLANNERS)
