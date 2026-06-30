"""Narrative generation subpackage (Tier 1 #3 α-min-1 PR1).

Public API:
- TemplateNarrativeGenerator — Stage 1 deterministic generator (Task 6)
- LLMNarrativeGenerator — Stage 2 LLM hook wrapper (Task 7, default OFF)
- NarrativeCache — in-memory cache for LLM-generated sections (Task 7)
- apply_replacement_strategy — section replacement dispatch (Task 7)
"""
from clinosim.modules.document.narrative.cache import NarrativeCache
from clinosim.modules.document.narrative.llm_generator import LLMNarrativeGenerator
from clinosim.modules.document.narrative.replacement_strategy import apply_replacement_strategy
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

__all__ = [
    "TemplateNarrativeGenerator",
    "LLMNarrativeGenerator",
    "NarrativeCache",
    "apply_replacement_strategy",
]
