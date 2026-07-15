"""Narrative generation subpackage (AD-65 Stage 2, unified in the N-chain).

Architecture: ``NarrativePass`` (``passes.py``) walks structural CIF in
(doc_type, language) group order and delegates content to a constructor-
injected ``NarrativeGenerator`` (Protocol in ``clinosim/types/document.py``).
Two generators exist:

- ``TemplateNarrativeGenerator`` — Stage 1 deterministic renderer (default;
  used by ``TemplateNarrativePass`` and as the base layer of the LLM path).
- ``LLMNarrativeGenerator`` — wraps the template generator and replaces
  ``DocumentTypeSpec.llm_enabled_sections`` via ``apply_replacement_strategy``
  → ``LLMService.complete_prompt`` (AD-11). Opt-in is the explicit CLI choice
  ``narrate --provider bedrock|ollama|mock`` (``LLMNarrativePass``); there is
  no env gate. Provider failure falls back to template output per document.

``NarrativeCache`` is the layer-1 in-memory cache (clinical-context +
template-seed-hash key) for cross-patient section reuse; the layer-2 disk
``PromptCache`` lives inside ``LLMService``.

Public API:
- TemplateNarrativeGenerator — Stage 1 deterministic generator
- LLMNarrativeGenerator — template base + per-section LLM replacement
- NarrativeCache — layer-1 in-memory cache for LLM-generated sections
- apply_replacement_strategy — section replacement dispatch
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
