"""Shared leaf helpers — small, cohesive utilities used across section
builders that make no self-recursive dispatch back to the class.

Extracted from ``template_generator.TemplateNarrativeGenerator`` as step
C1s of the full-review Phase C renderer split (CRITICAL C1). Behavior is
byte-identical — the four class methods are now thin delegators.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from clinosim.codes.icd10 import condition_label, icd10_display
from clinosim.codes.procedures import procedure_code_display
from clinosim.codes.snomed_concepts import SURGICAL_PROCEDURE
from clinosim.locale.i18n import t
from clinosim.locale.loader import map_diagnosis_code
from clinosim.locale.loader import narrative_label as _label
from clinosim.modules._shared import get_attr_or_key as _o

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext


def pydantic_day_findings_to_dict(day_findings: Any) -> dict[str, Any]:
    """Convert a Pydantic PhysicalExamDayFindings to a plain dict."""
    if isinstance(day_findings, dict):
        return day_findings
    result: dict[str, Any] = {}
    for sys_key in ("general", "cardiovascular", "respiratory", "abdominal", "neurological", "psychiatric"):
        val = _o(day_findings, sys_key, None)
        if val is not None:
            if isinstance(val, str):
                result[sys_key] = val
            else:
                result[sys_key] = {
                    "mild": _o(val, "mild", ""),
                    "moderate": _o(val, "moderate", ""),
                    "severe": _o(val, "severe", ""),
                    "all": _o(val, "all", None),
                }
    return result


def format_physical_exam(phys_exam: dict[str, Any], severity: str, lang: str) -> str:
    """Format a physical exam findings dict to a single text string.

    Picks the most appropriate severity level per system:
      - prefer "all" (severity-agnostic) if present
      - else pick severity-matched text (mild/moderate/severe)
      - else pick any non-empty text
    """
    if not phys_exam:
        return ""

    parts = []
    for sys_key in ("general", "cardiovascular", "respiratory", "abdominal", "neurological", "psychiatric"):
        entry = phys_exam.get(sys_key)
        if entry is None:
            continue
        if isinstance(entry, str):
            text = entry
        elif isinstance(entry, dict):
            text = (
                entry.get("all")
                or entry.get(severity)
                or entry.get("moderate")
                or entry.get("mild")
                or entry.get("severe")
                or ""
            )
            if text is None:
                text = ""
        else:
            text = ""
        if text:
            label = _label("body_system", sys_key, lang, fallback=sys_key)
            parts.append(f"{label}: {text}")

    return t("list_sep.period_space", lang).join(parts)


def primary_surgical_procedure(ctx: NarrativeContext) -> Any | None:
    """Return the encounter's earliest surgical ProcedureRecord (or None).

    Mirrors the engine's ``per_surgical_encounter`` selection: filter
    ``ctx.procedures`` to entries whose ``encounter_id`` matches the
    current encounter AND whose SNOMED ``category_code`` is ``SURGICAL_PROCEDURE``
    (surgical procedure), then pick the earliest by ``start_datetime``.
    Bedside/diagnostic/therapeutic procedures never satisfy the
    category filter, so this is safe to call on non-surgical encounters
    (returns None). The engine's own choice of primary is deterministic
    and independent, so template + engine agree on which procedure
    the note describes.
    """
    enc_id = _o(ctx.encounter, "encounter_id", "") or ""
    candidates = [
        p
        for p in (ctx.procedures or [])
        if _o(p, "encounter_id", "") == enc_id and str(_o(p, "category_code", "") or "") == SURGICAL_PROCEDURE
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda p: _o(p, "start_datetime", None) or datetime(2000, 1, 1))


def resolve_procedure_display(proc: Any, lang: str) -> str:
    """Resolve procedure display via code_lookup (k-codes / cpt).

    Mirrors ``clinosim/modules/output/hospital_course_extractor._resolve_procedure_name``
    so the operative note reads the same authoritative code catalog as
    the FHIR emit path — a single edit of the k-codes yaml updates both
    (single-edit-point rule).
    """
    disp = procedure_code_display(
        (str(_o(proc, key, "") or "") for key in ("procedure_code", "procedure_code_jp", "procedure_code_us")), lang
    )
    if disp:
        return disp
    return str(_o(proc, "procedure_type", "") or "")


def chronic_condition_code(code: str, country: str, sex: str = "") -> str:
    """The code the output emits for a patient's chronic condition stored
    under the internal key ``code`` (``map_diagnosis_code``: US ``F00`` →
    ``F03.90``, JP identity)."""
    return map_diagnosis_code(code, country, sex=sex) or code


def chronic_condition_label(code: str, country: str, lang: str, sex: str = "") -> str | None:
    """Name of a chronic problem in prose (Issue #2994): the condition label
    (``codes.icd10.condition_label``: short name, else official display) of
    the code the output emits for it, so the narrative names the condition
    the FHIR ``Condition`` codes (US dementia ``F03.90`` "Dementia", not the
    ``F00`` category title "Dementia in Alzheimer disease"). ``None`` when
    the code has no label."""
    return condition_label(chronic_condition_code(code, country, sex), country, lang) if code else None


def chronic_condition_coded(code: str, country: str, lang: str, sex: str = "") -> tuple[str, str]:
    """``(emitted code, official display)`` of a chronic condition for a
    coded list ("display [code]"); the display falls back to the code."""
    emit = chronic_condition_code(code, country, sex)
    return emit, icd10_display(emit, country, lang) or emit
